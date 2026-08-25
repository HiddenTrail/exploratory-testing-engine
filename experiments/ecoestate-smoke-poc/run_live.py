"""EcoEstate dress rehearsal, one step past the pure smoke check: a real
Driver+Skeptic checkpoint loop (2 checkpoints, up to TEST_BUDGET tests each) against a
real, running server - still no oracle library, still just the single
GET /api/notes/:postalCode endpoint. The point isn't deep coverage yet (that's
what the eventual notes adapter is for) - it's proving the full loop mechanics
(batched casting, hypothesis-forming, cold Skeptic review, feedback into the
next round) work end to end against this real app before building on them.

Owns the EcoEstate server's lifecycle end to end (start, wait for readiness,
run the loop, shut down) - same start/verify/shutdown sequence as the smoke
check this extends.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3
MAX_CHECKPOINTS = 2
TEST_BUDGET = 8

SERVER_DIR = Path(r"C:\Users\pmarj\ecoestate\server")
BASE_URL = "http://localhost:3001"
PORT = 3001
READY_URL = f"{BASE_URL}/api/postcodes"

ENDPOINT_SPEC = """GET /api/notes/:postalCode - returns all notes saved for a Finnish postal code.

Path parameter:
  postalCode: string - must match ^\\d{5}$ (exactly 5 digits).

Responses:
  200 {"data": [...]} - a (possibly empty) array of note objects, if postalCode is well-formed.
  400 {"error": "..."} - if postalCode is not exactly 5 digits.

This endpoint is read-only and the note store is in-memory and freshly started - every
well-formed postal code will return an empty array, since nothing has created any notes yet.
There is no data to explore here, only input-handling behavior: what counts as well-formed,
and what happens at the edges of that definition."""

CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": f"Propose up to {TEST_BUDGET} tests against GET /api/notes/:postalCode this round.",
    "input_schema": {
        "type": "object",
        "properties": {
            "give_up": {"type": "boolean", "description": "Set true only if you have no more good ideas this round."},
            "reasoning": {"type": "string", "description": "Your reasoning for this round's batch."},
            "candidate_tests": {
                "type": "array",
                "description": f"Up to {TEST_BUDGET} tests. Each is independent - they don't depend on each other's outcomes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "postal_code": {"type": "string", "description": "The postal code path value to send."},
                        "predicted_status": {"type": "integer"},
                        "predicted_shape": {"type": "string", "description": "What you predict the response body will contain."},
                    },
                    "required": ["postal_code", "predicted_status", "predicted_shape"],
                },
            },
        },
        "required": ["give_up", "reasoning", "candidate_tests"],
    },
}

HYPOTHESIS_TOOL = {
    "name": "submit_checkpoint_hypothesis",
    "description": "Summarize what's been observed so far and flag anything anomalous.",
    "input_schema": {
        "type": "object",
        "properties": {
            "observed_behavior": {"type": "string", "description": "What the tests so far actually showed."},
            "anomalies": {
                "type": "array", "items": {"type": "string"},
                "description": "Anything that didn't match documented/expected behavior. Empty list if none.",
            },
            "untested_areas": {
                "type": "array", "items": {"type": "string"},
                "description": "Input-handling behaviors not yet exercised.",
            },
            "prior_gaps_response": {
                "type": "array", "items": {"type": "string"},
                "description": "If given prior_checkpoint_feedback, how this round's tests addressed its named gaps. Empty list on the first checkpoint.",
            },
        },
        "required": ["observed_behavior", "anomalies", "untested_areas", "prior_gaps_response"],
    },
}

SKEPTIC_TOOL = {
    "name": "submit_skeptic_review",
    "description": "Give a cold, critical review of a hypothesis you did not form yourself.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["strong_enough", "weak"]},
            "gaps": {"type": "array", "items": {"type": "string"}, "description": "What's still missing before this should be trusted."},
            "critique": {"type": "string", "description": "Coverage breadth AND inference validity - is the claimed behavior actually supported by what was tested?"},
        },
        "required": ["verdict", "gaps", "critique"],
    },
}


def casting_system_prompt(is_first_round: bool) -> str:
    context = (
        "This is the first checkpoint - nothing has been tested yet."
        if is_first_round else
        "You have real results from prior rounds (tests_tried_in_earlier_rounds) and the prior "
        "checkpoint's hypothesis plus the Skeptic's critique of it (prior_checkpoint_feedback). "
        "Prioritize tests that close the gaps the Skeptic actually named."
    )
    return f"""You are testing a live, real API endpoint for input-handling correctness.

{ENDPOINT_SPEC}

{context}

Propose up to {TEST_BUDGET} tests this round - boundary and negative cases are far more informative
than happy-path calls here, since the happy path always returns the same empty result. Don't repeat
a question already settled by prior rounds. Set give_up to true only if you truly have nothing left
worth testing.

Call submit_casting_round with your answer."""


HYPOTHESIS_SYSTEM_PROMPT = """Summarize what testing so far has actually shown about this endpoint's
input-handling behavior, and flag anything that didn't match what's documented. If given
prior_checkpoint_feedback, explicitly say how this round's new tests addressed the gaps the Skeptic
named last time (prior_gaps_response) - empty list if this is the first checkpoint.

Call submit_checkpoint_hypothesis with your answer."""

SKEPTIC_SYSTEM_PROMPT = """You are a skeptical reviewer. You did NOT run these tests yourself and have
not seen the raw results - only the hypothesis's own final claims, given as the user message. Coldly
critique whether the claimed behavior is actually supported by what's described, whether real
input-handling edge cases remain unexercised, and whether any claimed anomaly is well-supported or
could have an innocent explanation. Set verdict to "strong_enough" only if coverage is genuinely
broad and every claim is well-supported. Otherwise "weak".

Call submit_skeptic_review with your answer."""


def validate_casting(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    for key in ("give_up", "reasoning", "candidate_tests"):
        if key not in data:
            errors.append(f"missing required field '{key}'")
    tests = data.get("candidate_tests")
    if not isinstance(tests, list):
        errors.append("'candidate_tests' must be a list")
    elif not data.get("give_up") and not tests:
        errors.append("'candidate_tests' must be non-empty unless give_up is true")
    else:
        for i, t in enumerate(tests or []):
            if not isinstance(t, dict):
                errors.append(f"candidate_tests[{i}] must be an object")
                continue
            for key in ("postal_code", "predicted_status", "predicted_shape"):
                if key not in t:
                    errors.append(f"candidate_tests[{i}] missing '{key}'")
            if "postal_code" in t and not isinstance(t["postal_code"], str):
                errors.append(f"candidate_tests[{i}].postal_code must be a string")
            if "predicted_status" in t and not isinstance(t["predicted_status"], int):
                errors.append(f"candidate_tests[{i}].predicted_status must be an integer")
    return errors


def validate_hypothesis(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    for key in ("observed_behavior", "anomalies", "untested_areas", "prior_gaps_response"):
        if key not in data:
            errors.append(f"missing required field '{key}'")
    for key in ("anomalies", "untested_areas", "prior_gaps_response"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"'{key}' must be a list")
    return errors


def validate_skeptic(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    for key in ("verdict", "gaps", "critique"):
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if data.get("verdict") not in ("strong_enough", "weak"):
        errors.append("'verdict' must be 'strong_enough' or 'weak'")
    if "gaps" in data and not isinstance(data["gaps"], list):
        errors.append("'gaps' must be a list")
    return errors


def call_tool_with_retry(client, *, system, tools, tool_name, user_message, max_tokens, validate_fn):
    """Feedback-loop retry (unlike the smoke-check's fresh-retry version this
    replaces): a fresh retry repeats the exact same prompt, so a systematic
    omission (the model consistently dropping one required field, found live
    on checkpoint 2's hypothesis call) fails identically every attempt with
    no chance to self-correct. Telling it what's missing does the trick."""
    messages = [{"role": "user", "content": user_message}]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system, tools=tools,
            tool_choice={"type": "tool", "name": tool_name}, messages=messages,
        )
        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            print(f"    attempt {attempt}: no tool call - retrying")
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call the tool. Try again."})
            continue
        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input
        print(f"    attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result", "tool_use_id": tool_use.id,
                "content": "Invalid: " + "; ".join(errors) + ". Fix and call the tool again with a corrected, complete answer.",
                "is_error": True,
            }],
        })
    raise RuntimeError(f"Gave up after {MAX_ATTEMPTS} attempts")


def _powershell(command: str) -> str:
    result = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True, timeout=15)
    return result.stdout.strip()


def start_server() -> subprocess.Popen:
    print(f"Starting EcoEstate server in {SERVER_DIR} ...")
    proc = subprocess.Popen("npm run dev", cwd=SERVER_DIR, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(1, 31):
        try:
            r = httpx.get(READY_URL, timeout=2.0)
            if r.status_code == 200:
                print(f"  up after {i}s")
                return proc
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise RuntimeError("Server did not become ready in time")


def stop_server(proc: subprocess.Popen) -> None:
    pid = _powershell(
        f"Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess"
    )
    if pid:
        parent_pid = _powershell(f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ParentProcessId")
        _powershell(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
        if parent_pid:
            _powershell(f"Stop-Process -Id {parent_pid} -Force -ErrorAction SilentlyContinue")
    proc.terminate()
    print("Server stopped.")


def execute_test(test: dict, test_number: int) -> dict:
    url = f"{BASE_URL}/api/notes/{test['postal_code']}"
    response = httpx.get(url, timeout=10.0)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    prediction_matched = response.status_code == test["predicted_status"]
    return {
        "test_number": test_number, "postal_code": test["postal_code"], "url": url,
        "predicted_status": test["predicted_status"], "predicted_shape": test["predicted_shape"],
        "actual_status": response.status_code, "actual_body": body, "prediction_matched": prediction_matched,
    }


def _esc(value) -> str:
    import html as _html
    return _html.escape(str(value)) if value is not None else ""


def _badge(text, kind) -> str:
    return f'<span class="badge badge-{kind}">{_esc(text)}</span>'


def render_report(output: dict) -> str:
    tests_html = "".join(f"""
    <tr>
      <td>#{t['test_number']}</td>
      <td><code>{_esc(t['postal_code'])}</code></td>
      <td>{_badge(t['predicted_status'], 'muted')}</td>
      <td>{_badge(t['actual_status'], 'good' if t['actual_status'] < 400 else 'warn')}</td>
      <td>{_badge('matched', 'good') if t['prediction_matched'] else _badge('MISSED', 'bad')}</td>
      <td><pre>{_esc(json.dumps(t['actual_body']))}</pre></td>
    </tr>
    """ for t in output["casting_log"])

    checkpoints_html = ""
    for c in output["checkpoints"]:
        h, s = c["hypothesis"], c["skeptic_review"]
        anomalies = "".join(f"<li>{_esc(a)}</li>" for a in h["anomalies"]) or "<li class='muted'>None</li>"
        untested = "".join(f"<li>{_esc(a)}</li>" for a in h["untested_areas"]) or "<li class='muted'>None</li>"
        gaps = "".join(f"<li>{_esc(g)}</li>" for g in s["gaps"]) or "<li class='muted'>None</li>"
        verdict_kind = "good" if s["verdict"] == "strong_enough" else "bad"
        checkpoints_html += f"""
        <div class="checkpoint">
          <h3>Checkpoint {c['checkpoint']}</h3>
          <p><strong>Observed behavior</strong></p>
          <p>{_esc(h['observed_behavior'])}</p>
          <p><strong>Anomalies noticed ({len(h['anomalies'])})</strong></p>
          <ul>{anomalies}</ul>
          <p><strong>Untested areas named</strong></p>
          <ul>{untested}</ul>
          <h4>Skeptic review {_badge(s['verdict'], verdict_kind)}</h4>
          <p><strong>Gaps identified</strong></p>
          <ul>{gaps}</ul>
          <p><strong>Critique</strong></p>
          <p>{_esc(s['critique'])}</p>
        </div>
        """

    stopped_kind = "good" if output["stopped_reason"] == "skeptic_satisfied" else "warn"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>EcoEstate Smoke PoC - GET /api/notes/:postalCode</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  h3 {{ margin-top: 2rem; border-bottom: 2px solid #eee; padding-bottom: 0.3rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.5rem; font-size: 0.9rem; }}
  td, th {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
  code, pre {{ font-family: Consolas, monospace; font-size: 0.85rem; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
  .badge {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }}
  .badge-good {{ background: #d4edda; color: #155724; }}
  .badge-bad {{ background: #f8d7da; color: #721c24; }}
  .badge-warn {{ background: #fff3cd; color: #856404; }}
  .badge-muted {{ background: #e2e3e5; color: #383d41; }}
  .checkpoint {{ background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 1rem 1.25rem; margin: 1rem 0; }}
  .muted {{ color: #888; }}
  ul {{ margin: 0.3rem 0 0.8rem; padding-left: 1.3rem; }}
</style></head>
<body>
  <h1>EcoEstate Smoke PoC &mdash; GET /api/notes/:postalCode</h1>
  <p>Stopped: {_badge(output['stopped_reason'], stopped_kind)} &middot; {len(output['casting_log'])} tests across {len(output['checkpoints'])} checkpoint(s)</p>

  <h3>All tests</h3>
  <table>
    <tr><th>#</th><th>postal_code</th><th>predicted</th><th>actual</th><th></th><th>body</th></tr>
    {tests_html}
  </table>

  {checkpoints_html}
</body></html>"""


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    server = start_server()
    try:
        casting_log = []
        checkpoints = []
        prior_feedback = None
        test_counter = 1
        stopped_reason = "checkpoints_exhausted"

        for checkpoint_num in range(1, MAX_CHECKPOINTS + 1):
            is_first = checkpoint_num == 1
            print(f"\n=== Checkpoint {checkpoint_num}/{MAX_CHECKPOINTS} ===")

            evidence = {"tests_tried_in_earlier_rounds": casting_log}
            if prior_feedback is not None:
                evidence["prior_checkpoint_feedback"] = prior_feedback
            print("Asking Claude for a casting round...")
            casting = call_tool_with_retry(
                client, system=casting_system_prompt(is_first), tools=[CASTING_TOOL], tool_name="submit_casting_round",
                user_message=json.dumps(evidence, indent=2), max_tokens=2048, validate_fn=validate_casting,
            )

            if casting["give_up"]:
                print(f"  Claude gave up: {casting['reasoning']}")
            else:
                print(f"  round reasoning: {casting['reasoning']}")
                for test in casting["candidate_tests"]:
                    result = execute_test(test, test_counter)
                    test_counter += 1
                    print(f"  test #{result['test_number']}: postal_code={test['postal_code']!r} "
                          f"-> {result['actual_status']} (predicted {test['predicted_status']}) "
                          f"{'matched' if result['prediction_matched'] else 'MISSED'}")
                    casting_log.append(result)

            prior_skeptic_review = prior_feedback["skeptic_review"] if prior_feedback else None
            print("Forming a hypothesis...")
            hyp_evidence = {"all_tests_this_session": casting_log}
            if prior_skeptic_review is not None:
                hyp_evidence["prior_skeptic_review"] = prior_skeptic_review
            hypothesis = call_tool_with_retry(
                client, system=HYPOTHESIS_SYSTEM_PROMPT, tools=[HYPOTHESIS_TOOL], tool_name="submit_checkpoint_hypothesis",
                # 1024 was enough at TEST_BUDGET=3 but proved marginal at 8 tests/checkpoint plus
                # a prior_skeptic_review in evidence - measured stop_reason="max_tokens" truncating
                # the last field (prior_gaps_response) 2/3 times at this evidence size.
                user_message=json.dumps(hyp_evidence, indent=2), max_tokens=2048, validate_fn=validate_hypothesis,
            )
            print(f"  observed_behavior: {hypothesis['observed_behavior']}")
            print(f"  anomalies noticed: {len(hypothesis['anomalies'])}")

            print("Asking Skeptic for a cold review...")
            skeptic_evidence = {
                "observed_behavior": hypothesis["observed_behavior"], "anomalies": hypothesis["anomalies"],
                "untested_areas": hypothesis["untested_areas"],
            }
            skeptic_review = call_tool_with_retry(
                client, system=SKEPTIC_SYSTEM_PROMPT, tools=[SKEPTIC_TOOL], tool_name="submit_skeptic_review",
                user_message=json.dumps(skeptic_evidence, indent=2), max_tokens=1536, validate_fn=validate_skeptic,
            )
            print(f"  skeptic verdict: {skeptic_review['verdict']}")

            checkpoints.append({"checkpoint": checkpoint_num, "hypothesis": hypothesis, "skeptic_review": skeptic_review})

            if skeptic_review["verdict"] == "strong_enough":
                stopped_reason = "skeptic_satisfied"
                break
            prior_feedback = {"hypothesis": hypothesis, "skeptic_review": skeptic_review}

        output = {"casting_log": casting_log, "checkpoints": checkpoints, "stopped_reason": stopped_reason}
        out_dir = Path(__file__).parent / "results"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "output.json"
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nStopped: {stopped_reason}. Wrote {out_path}")

        report_path = out_dir / "report.html"
        report_path.write_text(render_report(output), encoding="utf-8")
        print(f"Wrote {report_path}")
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
