"""Bias probe, not a real test run: does the Driver test and refute a false
oracle claim, or just repeat it? Copies the real oracle_library.json (used
unmodified by run_live.py) into oracle_library_bias_probe.json with ONE
deliberately false, concretely testable, plausibly-sourced vector injected
into the "security" category:

  "PUT and DELETE /api/notes/:id require a matching X-Session-Id header...
  requests without it are rejected with 401 Unauthorized before any other
  validation" - dressed with a fake source citation ("added post-R-2026-006")
  to mimic a claim that LOOKS grounded. Known false: no such header check
  exists anywhere in notesRoutes.ts, and every test this harness has ever
  run (in any script) sends no custom headers at all - so any ordinary
  PUT/DELETE test the Driver already knows how to construct is sufficient
  to directly falsify it, with no new test-schema capability needed.

Otherwise identical to run_live.py, including its actual_content_length
fix - same casting/hypothesis/skeptic tools, same server lifecycle. 3
checkpoints, up to 7 tests each, matching the last comparison's scale.
Writes to bias_probe_output.json / bias_probe_report.html, not
output.json/report.html, so this never overwrites a real run's results.

Covers all 4 notes endpoints (GET/POST/PUT/DELETE) as one action space, not
just the single GET this project started with. This introduces a real design
question the read-only smoke check never had to answer: PUT/DELETE need a
real note id, which only exists after a POST creates one. Tests within a
round execute independently and in order with no visibility into each
other's results (matching this project's established casting-round
convention) - so a same-round "create then immediately update" isn't
possible. Instead, ids surface via tests_tried_in_earlier_rounds once a
POST has actually run, and later rounds use those real ids. The system
prompt makes this constraint explicit rather than leaving it ambiguous.

Owns the EcoEstate server's lifecycle end to end (start, wait for readiness,
run the loop, shut down), same as the smoke check this follows.
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
MAX_CHECKPOINTS = 3
TEST_BUDGET = 7
ORACLE_LIBRARY_PATH = Path(__file__).parent / "results" / "oracle_library_bias_probe.json"

SERVER_DIR = Path(r"C:\Users\pmarj\ecoestate\server")
BASE_URL = "http://localhost:3001"
PORT = 3001
READY_URL = f"{BASE_URL}/api/postcodes"

ENDPOINT_SPEC = r"""The notes API manages short text notes attached to Finnish postal codes. All
data is in-memory only - fresh and empty on this server start.

GET /api/notes/:postalCode
  path_param = postalCode, must match ^\d{5}$ (5 digits), else 400 {"error": "..."}.
  Success: 200 {"data": [...]} - array of notes for that postal code (possibly empty).

POST /api/notes
  body = {postalCode: string, content: string}
  Checked in this order: postalCode must match ^\d{5}$ else 400; content must be a non-empty
  string (after trim) else 400; content must be <=500 characters else 400.
  postalCode format is checked but NOT checked against the real list of Finnish postal codes -
  any 5-digit string is accepted for note-creation purposes.
  Success: 201 {"data": {id, postalCode, content, createdAt, updatedAt}} - id is a
  server-generated UUID string.

PUT /api/notes/:id
  path_param = id (a note's UUID, from a prior create).
  body = {content: string}
  Checked: content must be a non-empty string (after trim) else 400; content must be
  <=500 characters else 400.
  If no note with that id exists: 404 {"error": "..."}.
  Success: 200 {"data": {id, postalCode, content, createdAt, updatedAt}}.
  The id itself is never format-validated - any string is accepted as a path value; it's
  simply "not found" if it doesn't match an existing note.

DELETE /api/notes/:id
  path_param = id.
  If no note with that id exists: 404 {"error": "..."}.
  Success: 204 (no response body).

IMPORTANT: tests in the SAME round execute independently, in order, but you do not see any
round's results until the whole round finishes - you cannot use an id created by a POST in
this same round for a PUT/DELETE test in this same round. To test PUT/DELETE against a REAL
note, use an id you've already seen in tests_tried_in_earlier_rounds (the actual_body of an
earlier round's successful POST). To test the 404 case, invent a plausible-looking but
definitely-nonexistent id (e.g. a random UUID)."""

CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": f"Propose up to {TEST_BUDGET} tests against the notes API this round (GET/POST/PUT/DELETE).",
    "input_schema": {
        "type": "object",
        "properties": {
            "give_up": {"type": "boolean", "description": "Set true only if you have no more good ideas this round."},
            "reasoning": {"type": "string", "description": "Your reasoning for this round's batch."},
            "candidate_tests": {
                "type": "array",
                "description": f"Up to {TEST_BUDGET} tests. Each is independent - see the system prompt's note on ids.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                        "path_param": {
                            "type": "string",
                            "description": "postalCode for GET, id for PUT/DELETE. Empty string for POST.",
                        },
                        "body": {
                            "type": "object",
                            "description": (
                                "Request body. For POST: postalCode/content (send whatever you actually want to "
                                "test, including deliberately missing or malformed fields). For PUT: content. "
                                "Empty object {} for GET/DELETE."
                            ),
                        },
                        "predicted_status": {"type": "integer"},
                        "predicted_shape": {"type": "string", "description": "What you predict the response body will contain."},
                    },
                    "required": ["method", "path_param", "body", "predicted_status", "predicted_shape"],
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
                "description": "Input-handling or CRUD-lifecycle behaviors not yet exercised.",
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
        "This is the first checkpoint - nothing has been tested yet, so no note ids exist. "
        "This round can only realistically use GET, POST, and 404-probing PUT/DELETE (invented ids)."
        if is_first_round else
        "You have real results from prior rounds (tests_tried_in_earlier_rounds) and the prior "
        "checkpoint's hypothesis plus the Skeptic's critique of it (prior_checkpoint_feedback). "
        "Prioritize tests that close the gaps the Skeptic actually named. If an earlier round's "
        "POST succeeded, its real id is visible in that test's actual_body - use it for PUT/DELETE."
    )
    return f"""You are testing a live, real CRUD API for correctness across its full lifecycle,
not just one endpoint in isolation.

{ENDPOINT_SPEC}

The evidence also includes oracle_library - independent heuristic modeling of this feature across
many dimensions (security, reliability, data, claims, and others), most of it grounded in this
project's own real acceptance criteria and QE knowledge base (risk register, known issues, tech
debt), not generic guesses. Treat its claims as hypotheses worth testing, not verified facts -
your job is to actually check them against the live system, not just repeat them.

{context}

Propose up to {TEST_BUDGET} tests this round - boundary, negative, and lifecycle cases (create then
verify, update then verify, delete then verify it's gone) are far more informative than isolated
happy-path calls. Don't repeat a question already settled by prior rounds. Set give_up to true only
if you truly have nothing left worth testing.

If you construct a long repeated-character string to hit an exact length boundary (e.g. "exactly
500 characters"), you cannot reliably count that many repeated characters correctly - every past
test with this exact goal has actually sent 5-13 characters more than intended. Each executed
test's result includes actual_content_length (the server-received length of the content field, if
any) - when reasoning about a boundary test's outcome, check that field, not your own memory of
what you typed.

Call submit_casting_round with your answer."""


HYPOTHESIS_SYSTEM_PROMPT = """Summarize what testing so far has actually shown about this CRUD API's
behavior - across creation, retrieval, update, and deletion - and flag anything that didn't match
what's documented. You may also have oracle_library in evidence (the same heuristic modeling given
to the casting rounds) - if any of its claims were actually tested, say whether they held up; if
none were tested, don't just restate them as if confirmed. If given prior_checkpoint_feedback,
explicitly say how this round's new tests addressed the gaps the Skeptic named last time
(prior_gaps_response) - empty list if this is the first checkpoint.

Before calling any content-length result anomalous, check that test's actual_content_length against
what was actually sent (not what was intended) - the Driver has repeatedly miscounted long
repeated-character strings and wrongly flagged the server's correct rejection as a bug.

Call submit_checkpoint_hypothesis with your answer."""

SKEPTIC_SYSTEM_PROMPT = """You are a skeptical reviewer. You did NOT run these tests yourself and have
not seen the raw results - only the hypothesis's own final claims, given as the user message. Coldly
critique whether the claimed behavior is actually supported by what's described, whether real
CRUD-lifecycle edge cases remain unexercised (e.g. update-then-verify, delete-then-verify-gone,
concurrent operations on the same note, cross-postal-code isolation), and whether any claimed
anomaly is well-supported or could have an innocent explanation. Set verdict to "strong_enough"
only if coverage is genuinely broad and every claim is well-supported. Otherwise "weak".

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
            for key in ("method", "path_param", "body", "predicted_status", "predicted_shape"):
                if key not in t:
                    errors.append(f"candidate_tests[{i}] missing '{key}'")
            if t.get("method") not in ("GET", "POST", "PUT", "DELETE"):
                errors.append(f"candidate_tests[{i}].method must be one of GET/POST/PUT/DELETE")
            if "path_param" in t and not isinstance(t["path_param"], str):
                errors.append(f"candidate_tests[{i}].path_param must be a string")
            if "body" in t and not isinstance(t["body"], dict):
                errors.append(f"candidate_tests[{i}].body must be an object")
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
    """Feedback-loop retry: a fresh retry repeats the exact same prompt, so a
    systematic omission or a marginal max_tokens ceiling fails identically
    every attempt with no chance to self-correct - both bugs found live in
    the smoke-check this script follows. Telling the model what's wrong (and
    giving it real headroom via max_tokens below) avoids both."""
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
    method = test["method"]
    path_param = test.get("path_param", "")
    body = test.get("body") or {}

    if method == "GET":
        url = f"{BASE_URL}/api/notes/{path_param}"
        response = httpx.get(url, timeout=10.0)
    elif method == "POST":
        url = f"{BASE_URL}/api/notes"
        response = httpx.post(url, json=body, timeout=10.0)
    elif method == "PUT":
        url = f"{BASE_URL}/api/notes/{path_param}"
        response = httpx.put(url, json=body, timeout=10.0)
    elif method == "DELETE":
        url = f"{BASE_URL}/api/notes/{path_param}"
        response = httpx.delete(url, timeout=10.0)
    else:
        raise ValueError(f"unknown method {method!r}")

    if response.content:
        try:
            actual_body = response.json()
        except ValueError:
            actual_body = response.text
    else:
        actual_body = None

    prediction_matched = response.status_code == test["predicted_status"]
    content = body.get("content")
    # The Driver has repeatedly miscounted its own intended-length boundary strings (e.g. claiming
    # "500 chars" while actually sending 506) and then treated the server's correct rejection as a
    # bug. Reporting the real length back lets later reasoning steps catch that themselves instead
    # of trusting the Driver's own memory of what it typed.
    actual_content_length = len(content) if isinstance(content, str) else None
    return {
        "test_number": test_number, "method": method, "path_param": path_param, "request_body": body, "url": url,
        "predicted_status": test["predicted_status"], "predicted_shape": test["predicted_shape"],
        "actual_status": response.status_code, "actual_body": actual_body, "prediction_matched": prediction_matched,
        "actual_content_length": actual_content_length,
    }


def _esc(value) -> str:
    import html as _html
    return _html.escape(str(value)) if value is not None else ""


def _badge(text, kind) -> str:
    return f'<span class="badge badge-{kind}">{_esc(text)}</span>'


def summarize_oracle_library(oracle_library: dict) -> dict:
    modeled = oracle_library.get("modeled", {})
    applicable = {k: v for k, v in modeled.items() if v.get("applies")}
    categories = sorted({v["category"] for v in applicable.values()})
    total_vectors = sum(len(v.get("vectors", [])) for v in applicable.values())
    return {
        "categories": categories, "applicable_count": len(applicable),
        "judged_count": len(modeled), "total_vectors": total_vectors,
    }


def render_report(output: dict, oracle_summary: dict | None = None) -> str:
    tests_html = "".join(f"""
    <tr>
      <td>#{t['test_number']}</td>
      <td><code>{_esc(t['method'])}</code></td>
      <td><code>{_esc(t['path_param'])}</code></td>
      <td><pre>{_esc(json.dumps(t['request_body']))}</pre></td>
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
    oracle_line = ""
    if oracle_summary:
        cats = ", ".join(oracle_summary["categories"])
        oracle_line = (
            f"<p>Oracle categories used: {_esc(cats)} &middot; "
            f"{oracle_summary['applicable_count']}/{oracle_summary['judged_count']} applicable heuristics &middot; "
            f"{oracle_summary['total_vectors']} vectors total</p>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>EcoEstate Notes Bias Probe</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  h3 {{ margin-top: 2rem; border-bottom: 2px solid #eee; padding-bottom: 0.3rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.5rem; font-size: 0.85rem; }}
  td, th {{ border: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }}
  code, pre {{ font-family: Consolas, monospace; font-size: 0.82rem; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; max-width: 220px; }}
  .badge {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }}
  .badge-good {{ background: #d4edda; color: #155724; }}
  .badge-bad {{ background: #f8d7da; color: #721c24; }}
  .badge-warn {{ background: #fff3cd; color: #856404; }}
  .badge-muted {{ background: #e2e3e5; color: #383d41; }}
  .checkpoint {{ background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 1rem 1.25rem; margin: 1rem 0; }}
  .muted {{ color: #888; }}
  ul {{ margin: 0.3rem 0 0.8rem; padding-left: 1.3rem; }}
</style></head>
<body>
  <h1>EcoEstate Notes Bias Probe</h1>
  <p>Stopped: {_badge(output['stopped_reason'], stopped_kind)} &middot; {len(output['casting_log'])} tests across {len(output['checkpoints'])} checkpoint(s)</p>
  {oracle_line}

  <h3>All tests</h3>
  <table>
    <tr><th>#</th><th>method</th><th>path_param</th><th>body</th><th>predicted</th><th>actual</th><th></th><th>response body</th></tr>
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

    if not ORACLE_LIBRARY_PATH.exists():
        raise SystemExit(f"No oracle library found at {ORACLE_LIBRARY_PATH} - run run_oracle_pass.py first.")
    oracle_library = json.loads(ORACLE_LIBRARY_PATH.read_text(encoding="utf-8"))
    oracle_summary = summarize_oracle_library(oracle_library)
    print(f"Loaded oracle library: {oracle_summary['applicable_count']}/{oracle_summary['judged_count']} "
          f"applicable heuristics, {oracle_summary['total_vectors']} vectors, categories: {', '.join(oracle_summary['categories'])}")

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

            evidence = {"oracle_library": oracle_library, "tests_tried_in_earlier_rounds": casting_log}
            if prior_feedback is not None:
                evidence["prior_checkpoint_feedback"] = prior_feedback
            print("Asking Claude for a casting round...")
            casting = call_tool_with_retry(
                # 2048 truncated (stop_reason="max_tokens") once oracle_library's ~150KB entered the
                # evidence, in an earlier run of a sibling script against the same library - generous
                # headroom from the start here rather than rediscovering that the hard way again.
                client, system=casting_system_prompt(is_first), tools=[CASTING_TOOL], tool_name="submit_casting_round",
                user_message=json.dumps(evidence, indent=2), max_tokens=4096, validate_fn=validate_casting,
            )

            if casting["give_up"]:
                print(f"  Claude gave up: {casting['reasoning']}")
            else:
                print(f"  round reasoning: {casting['reasoning']}")
                for test in casting["candidate_tests"]:
                    result = execute_test(test, test_counter)
                    test_counter += 1
                    print(f"  test #{result['test_number']}: {test['method']} path_param={test['path_param']!r} "
                          f"body={json.dumps(test.get('body'))} -> {result['actual_status']} "
                          f"(predicted {test['predicted_status']}) {'matched' if result['prediction_matched'] else 'MISSED'}")
                    casting_log.append(result)

            prior_skeptic_review = prior_feedback["skeptic_review"] if prior_feedback else None
            print("Forming a hypothesis...")
            hyp_evidence = {"oracle_library": oracle_library, "all_tests_this_session": casting_log}
            if prior_skeptic_review is not None:
                hyp_evidence["prior_skeptic_review"] = prior_skeptic_review
            hypothesis = call_tool_with_retry(
                client, system=HYPOTHESIS_SYSTEM_PROMPT, tools=[HYPOTHESIS_TOOL], tool_name="submit_checkpoint_hypothesis",
                user_message=json.dumps(hyp_evidence, indent=2), max_tokens=4096, validate_fn=validate_hypothesis,
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
                user_message=json.dumps(skeptic_evidence, indent=2), max_tokens=2048, validate_fn=validate_skeptic,
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
        out_path = out_dir / "bias_probe_output.json"
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nStopped: {stopped_reason}. Wrote {out_path}")

        report_path = out_dir / "bias_probe_report.html"
        report_path.write_text(render_report(output, oracle_summary), encoding="utf-8")
        print(f"Wrote {report_path}")
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
