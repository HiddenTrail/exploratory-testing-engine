"""Measures whether the oracle library wired into ecoestate-notes-poc changes
real Driver+Skeptic checkpoint-loop outcomes on the notes CRUD API - same
paired-trial idea as token-purchase-oracle-value and pattern-detection-
oracle-poc, adapted to a script that owns a real Node server's lifecycle
rather than a mock Python SUT or a single-shot call.

No ground truth exists for the notes feature (same limitation as
token_purchase) - this measures proxy signals: Skeptic-satisfaction rate on
an identical budget, anomaly-yield consistency, and whether specific themes
from the oracle library (most notably R-2026-006's ownership gap, which has
gone untested across every prior manual run of this project) get tested more
often with the oracle present than without.

Includes the actual_content_length fix found live in ecoestate-notes-poc:
the Driver repeatedly miscounted its own intended-length boundary strings
and treated the server's correct rejection as a bug. Both arms get the fix
identically, so it isn't a confound - it just keeps the comparison's
anomaly counts meaningful instead of contaminated by a Driver-side quirk
unrelated to the oracle library.

Owns the EcoEstate server's lifecycle end to end, restarted fresh before
every individual trial (in-memory state must not carry over between runs).
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
N_TRIALS = 5

ORACLE_LIBRARY_PATH = Path(__file__).parent.parent / "ecoestate-notes-poc" / "results" / "oracle_library.json"
SERVER_DIR = Path(r"C:\Users\pmarj\ecoestate\server")
BASE_URL = "http://localhost:3001"
PORT = 3001
READY_URL = f"{BASE_URL}/api/postcodes"
RESULTS_DIR = Path(__file__).parent / "results"

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


def casting_system_prompt(is_first_round: bool, with_oracle: bool) -> str:
    context = (
        "This is the first checkpoint - nothing has been tested yet, so no note ids exist. "
        "This round can only realistically use GET, POST, and 404-probing PUT/DELETE (invented ids)."
        if is_first_round else
        "You have real results from prior rounds (tests_tried_in_earlier_rounds) and the prior "
        "checkpoint's hypothesis plus the Skeptic's critique of it (prior_checkpoint_feedback). "
        "Prioritize tests that close the gaps the Skeptic actually named. If an earlier round's "
        "POST succeeded, its real id is visible in that test's actual_body - use it for PUT/DELETE."
    )
    oracle_para = ""
    if with_oracle:
        oracle_para = """
The evidence also includes oracle_library - independent heuristic modeling of this feature across
many dimensions (security, reliability, data, claims, and others), most of it grounded in this
project's own real acceptance criteria and QE knowledge base (risk register, known issues, tech
debt), not generic guesses. Treat its claims as hypotheses worth testing, not verified facts -
your job is to actually check them against the live system, not just repeat them.
"""
    return f"""You are testing a live, real CRUD API for correctness across its full lifecycle,
not just one endpoint in isolation.

{ENDPOINT_SPEC}
{oracle_para}
{context}

Propose up to {TEST_BUDGET} tests this round - boundary, negative, and lifecycle cases (create then
verify, update then verify, delete then verify it's gone) are far more informative than isolated
happy-path calls. Don't repeat a question already settled by prior rounds. Set give_up to true only
if you truly have nothing left worth testing.

If you construct a long repeated-character string to hit an exact length boundary (e.g. "exactly
500 characters"), you cannot reliably count that many repeated characters correctly. Each executed
test's result includes actual_content_length (the server-received length of the content field, if
any) - when reasoning about a boundary test's outcome, check that field, not your own memory of
what you typed.

Call submit_casting_round with your answer."""


def hypothesis_system_prompt(with_oracle: bool) -> str:
    oracle_note = (
        "\nYou may also have oracle_library in evidence (the same heuristic modeling given to the "
        "casting rounds) - if any of its claims were actually tested, say whether they held up; if "
        "none were tested, don't just restate them as if confirmed."
        if with_oracle else ""
    )
    return f"""Summarize what testing so far has actually shown about this CRUD API's behavior -
across creation, retrieval, update, and deletion - and flag anything that didn't match what's
documented.{oracle_note} If given prior_checkpoint_feedback, explicitly say how this round's new
tests addressed the gaps the Skeptic named last time (prior_gaps_response) - empty list if this is
the first checkpoint.

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
    proc = subprocess.Popen("npm run dev", cwd=SERVER_DIR, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(1, 31):
        try:
            r = httpx.get(READY_URL, timeout=2.0)
            if r.status_code == 200:
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
    actual_content_length = len(content) if isinstance(content, str) else None
    return {
        "test_number": test_number, "method": method, "path_param": path_param, "request_body": body, "url": url,
        "predicted_status": test["predicted_status"], "predicted_shape": test["predicted_shape"],
        "actual_status": response.status_code, "actual_body": actual_body, "prediction_matched": prediction_matched,
        "actual_content_length": actual_content_length,
    }


def run_one_trial(client, arm: str, trial: int, oracle_library: dict | None) -> dict:
    with_oracle = arm == "with_oracle"
    server = start_server()
    try:
        casting_log = []
        checkpoints = []
        round_reasonings = []
        prior_feedback = None
        test_counter = 1
        stopped_reason = "checkpoints_exhausted"

        for checkpoint_num in range(1, MAX_CHECKPOINTS + 1):
            is_first = checkpoint_num == 1
            evidence = {"tests_tried_in_earlier_rounds": casting_log}
            if with_oracle:
                evidence["oracle_library"] = oracle_library
            if prior_feedback is not None:
                evidence["prior_checkpoint_feedback"] = prior_feedback
            casting = call_tool_with_retry(
                client, system=casting_system_prompt(is_first, with_oracle), tools=[CASTING_TOOL],
                tool_name="submit_casting_round", user_message=json.dumps(evidence, indent=2),
                max_tokens=4096, validate_fn=validate_casting,
            )
            round_reasonings.append(casting["reasoning"])

            if not casting["give_up"]:
                for test in casting["candidate_tests"]:
                    result = execute_test(test, test_counter)
                    test_counter += 1
                    casting_log.append(result)

            prior_skeptic_review = prior_feedback["skeptic_review"] if prior_feedback else None
            hyp_evidence = {"all_tests_this_session": casting_log}
            if with_oracle:
                hyp_evidence["oracle_library"] = oracle_library
            if prior_skeptic_review is not None:
                hyp_evidence["prior_skeptic_review"] = prior_skeptic_review
            hypothesis = call_tool_with_retry(
                client, system=hypothesis_system_prompt(with_oracle), tools=[HYPOTHESIS_TOOL],
                tool_name="submit_checkpoint_hypothesis", user_message=json.dumps(hyp_evidence, indent=2),
                max_tokens=4096, validate_fn=validate_hypothesis,
            )

            skeptic_evidence = {
                "observed_behavior": hypothesis["observed_behavior"], "anomalies": hypothesis["anomalies"],
                "untested_areas": hypothesis["untested_areas"],
            }
            skeptic_review = call_tool_with_retry(
                client, system=SKEPTIC_SYSTEM_PROMPT, tools=[SKEPTIC_TOOL], tool_name="submit_skeptic_review",
                user_message=json.dumps(skeptic_evidence, indent=2), max_tokens=2048, validate_fn=validate_skeptic,
            )

            checkpoints.append({"checkpoint": checkpoint_num, "hypothesis": hypothesis, "skeptic_review": skeptic_review})
            print(f"    checkpoint {checkpoint_num}: {len(casting_log)} cumulative tests, "
                  f"anomalies={len(hypothesis['anomalies'])}, verdict={skeptic_review['verdict']}")

            if skeptic_review["verdict"] == "strong_enough":
                stopped_reason = "skeptic_satisfied"
                break
            prior_feedback = {"hypothesis": hypothesis, "skeptic_review": skeptic_review}

        output = {
            "trial": trial, "arm": arm, "casting_log": casting_log, "checkpoints": checkpoints,
            "round_reasonings": round_reasonings, "stopped_reason": stopped_reason,
        }
    finally:
        stop_server(server)

    out_dir = RESULTS_DIR / f"trial_{trial}_{arm}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "output.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    final = output["checkpoints"][-1]
    return {
        "trial": trial, "arm": arm, "stopped_reason": stopped_reason,
        "checkpoints_used": len(output["checkpoints"]), "tests_run": len(casting_log),
        "final_skeptic_verdict": final["skeptic_review"]["verdict"], "anomaly_count": len(final["hypothesis"]["anomalies"]),
        "round_reasonings": round_reasonings,
    }


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    oracle_library = json.loads(ORACLE_LIBRARY_PATH.read_text(encoding="utf-8"))

    summary = []
    for trial in range(1, N_TRIALS + 1):
        for arm in ("without_oracle", "with_oracle"):
            print(f"\n=== trial {trial}/{N_TRIALS} [{arm}] ===")
            result = run_one_trial(client, arm, trial, oracle_library)
            print(f"  {result['checkpoints_used']} checkpoints, {result['tests_run']} tests, "
                  f"verdict={result['final_skeptic_verdict']}, anomalies={result['anomaly_count']}")
            summary.append(result)

    out_path = RESULTS_DIR / "comparison_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote summary of {len(summary)} runs to {out_path}")


if __name__ == "__main__":
    main()
