"""Paired-trial comparison: does injecting a fresh, domain-judged oracle
library into the Driver's evidence change pattern-detection hypothesis
quality? Unlike token_purchase, sequence.json carries a real, known
ground_truth (withheld from every model call here) - so this can be scored
for actual correctness, not just "did behavior change."

Two arms, N trials each, evidence differing ONLY by whether oracle_library
is present - the Driver's PATTERN_TOOL/SYSTEM_PROMPT are byte-identical to
pattern-detection-poc/run.py in both arms, so the oracle library's presence
is the sole manipulated variable. Each trial's hypothesis then gets a cold
Skeptic review, which - mirroring engine.loop's Skeptic, which never sees
onboarding_extra either - never sees the oracle library, only the Driver's
final structured claims.

Self-contained by this project's convention (every run_live.py hand-copies
this shape rather than importing a shared module).
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 5
N_TRIALS = 6

PATTERN_TOOL = {
    "name": "submit_pattern_hypothesis",
    "description": (
        "Submit the pattern you noticed across the call sequence, which call breaks "
        "it, a hypothesis for why, a competing explanation, and a confirm/disconfirm "
        "test pair designed to discriminate between them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "observed_pattern": {
                "type": "string",
                "description": "The general trend noticed across the sequence of calls.",
            },
            "anomalous_call_index": {
                "type": "integer",
                "description": "The index of the call that breaks the observed pattern.",
            },
            "claim": {
                "type": "string",
                "description": "The primary, narrow, falsifiable hypothesis for why that call breaks the pattern.",
            },
            "competing_explanation": {
                "type": "string",
                "description": "The most plausible alternative explanation a careful engineer would also consider.",
            },
            "severity_if_true": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "confirm_action": {"type": "string", "description": "The concrete action/request that would confirm the claim."},
            "confirm_predicted_outcome": {"type": "string", "description": "What you predict that action would show if the claim is true."},
            "disconfirm_action": {
                "type": "string",
                "description": "A concrete action whose outcome would genuinely surprise you if the claim were true.",
            },
            "disconfirm_predicted_outcome": {"type": "string", "description": "What you predict that action would show if the claim is false."},
            "why_this_discriminates": {
                "type": "string",
                "description": "Explain why the disconfirm test's outcome would differ between the claim and the competing explanation, not just repeat the same check.",
            },
        },
        "required": [
            "observed_pattern", "anomalous_call_index", "claim", "competing_explanation", "severity_if_true",
            "confirm_action", "confirm_predicted_outcome", "disconfirm_action", "disconfirm_predicted_outcome",
            "why_this_discriminates",
        ],
    },
}

SYSTEM_PROMPT = """You are investigating a sequence of API calls made against a system under test (SUT).
Nothing in the data is pre-flagged as anomalous - you are given the raw sequence of requests and
responses and must notice any pattern yourself, and notice if any call breaks that pattern.
You do NOT have access to ground truth - form your best hypothesis using only the evidence given.

Produce:
1. The general pattern you notice across the sequence.
2. Which single call breaks that pattern.
3. The most likely, narrow, falsifiable hypothesis for why that call breaks the pattern - not
   just an extension of the general pattern's explanation.
4. The most plausible competing explanation for the same evidence - a genuine alternative a
   careful engineer would also consider, not a strawman.
5. A confirm test and a disconfirm test. The disconfirm test must be designed so its outcome
   would differ depending on which explanation is true - not simply repeat the same check.

Call submit_pattern_hypothesis with your answer."""


def validate_pattern_hypothesis(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]

    required_top = [
        "observed_pattern", "anomalous_call_index", "claim", "competing_explanation", "severity_if_true",
        "confirm_action", "confirm_predicted_outcome", "disconfirm_action", "disconfirm_predicted_outcome",
        "why_this_discriminates",
    ]
    for key in required_top:
        if key not in data:
            errors.append(f"missing required field '{key}'")
        elif key != "anomalous_call_index" and not isinstance(data[key], str):
            errors.append(f"'{key}' must be a string")

    if "anomalous_call_index" in data and not isinstance(data["anomalous_call_index"], int):
        errors.append("'anomalous_call_index' must be an integer")

    if data.get("severity_if_true") not in ("high", "medium", "low"):
        errors.append("'severity_if_true' must be one of high/medium/low")

    return errors


SKEPTIC_TOOL = {
    "name": "submit_skeptic_review",
    "description": "Give a cold, critical review of a pattern hypothesis you did not form yourself.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["strong_enough", "weak"]},
            "claim_vs_competing_critique": {
                "type": "string",
                "description": "Is the primary claim genuinely distinct from, and better supported by the evidence than, the competing explanation? Say why or why not.",
            },
            "discrimination_critique": {
                "type": "string",
                "description": "Would the disconfirm test's predicted outcome actually differ between the claim and the competing explanation, or would both predict the same outcome (making it non-discriminating)?",
            },
            "unconsidered_alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any plausible alternative explanations for the anomalous call that neither the claim nor the competing_explanation considered.",
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional evidence that would be needed before this hypothesis could be considered strong.",
            },
        },
        "required": ["verdict", "claim_vs_competing_critique", "discrimination_critique", "unconsidered_alternatives", "gaps"],
    },
}

SKEPTIC_SYSTEM_PROMPT = """You are a skeptical reviewer. You did NOT form this hypothesis yourself and have
not seen the raw call sequence - only the hypothesis's own final claims, given as the user message. Your
job is to coldly critique it on its own terms:

1. Is the primary claim genuinely distinct from, and better supported than, the competing explanation -
   or is the "competing explanation" a strawman that doesn't seriously threaten the claim?
2. Would the disconfirm test's predicted outcome actually differ depending on which explanation is true?
   A test whose outcome would be the same either way is not discriminating, regardless of what
   why_this_discriminates claims.
3. Are there plausible alternative explanations that neither the claim nor the competing_explanation
   considered at all?
4. What's still missing before this hypothesis should be trusted?

Set verdict to "strong_enough" only if the claim is well-distinguished from real alternatives and the
disconfirm test is genuinely discriminating. Otherwise "weak".

Call submit_skeptic_review with your answer."""


def call_tool_with_retry(client, *, system, tools, tool_name, user_message, max_tokens, validate_fn):
    """Fresh retry each attempt (no accumulated conversation history) - matches
    pattern-detection-poc/run.py's proven approach for this tool schema, rather
    than the feedback-loop retry used elsewhere in this project. That variant
    turned out to make this particular tool schema (nested confirm_test/
    disconfirm_test objects) degrade into malformed output after one retry."""
    last_errors = ["no attempts made"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system, tools=tools,
            tool_choice={"type": "tool", "name": tool_name}, messages=[{"role": "user", "content": user_message}],
        )
        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            last_errors = [f"no tool_use block (stop_reason={message.stop_reason})"]
            print(f"    attempt {attempt}: no tool call - retrying")
            continue

        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input

        last_errors = errors
        print(f"    attempt {attempt} produced malformed output: {errors} - retrying")

    raise RuntimeError(f"Gave up after {MAX_ATTEMPTS} attempts, last errors: {last_errors}")


def run_driver(client, scenario: dict, oracle_library: dict | None) -> dict:
    evidence = {"scenario": scenario["scenario"], "calls": scenario["calls"]}
    if oracle_library is not None:
        evidence["oracle_library"] = oracle_library
    return call_tool_with_retry(
        client, system=SYSTEM_PROMPT, tools=[PATTERN_TOOL], tool_name="submit_pattern_hypothesis",
        user_message=json.dumps(evidence, indent=2), max_tokens=4096, validate_fn=validate_pattern_hypothesis,
    )


def run_skeptic(client, hypothesis: dict) -> dict:
    evidence = {k: hypothesis[k] for k in [
        "observed_pattern", "anomalous_call_index", "claim", "competing_explanation", "severity_if_true",
        "confirm_action", "confirm_predicted_outcome", "disconfirm_action", "disconfirm_predicted_outcome",
        "why_this_discriminates",
    ]}
    return call_tool_with_retry(
        client, system=SKEPTIC_SYSTEM_PROMPT, tools=[SKEPTIC_TOOL], tool_name="submit_skeptic_review",
        user_message=json.dumps(evidence, indent=2), max_tokens=1024,
        validate_fn=lambda d: [] if isinstance(d, dict) and d.get("verdict") in ("strong_enough", "weak") else ["invalid skeptic response"],
    )


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    base_dir = Path(__file__).parent
    poc_dir = base_dir.parent / "pattern-detection-poc"
    scenario = json.loads((poc_dir / "sequence.json").read_text(encoding="utf-8"))
    ground_truth = scenario.pop("ground_truth")  # never sent to any model call below

    oracle_library = json.loads((base_dir / "results" / "oracle_library.json").read_text(encoding="utf-8"))

    trials = []
    for i in range(1, N_TRIALS + 1):
        print(f"\n=== Trial {i}/{N_TRIALS} ===")
        print("  driver (without oracle)...")
        without_hyp = run_driver(client, scenario, None)
        print("  skeptic (without)...")
        without_skeptic = run_skeptic(client, without_hyp)
        print(f"    verdict: {without_skeptic['verdict']}")

        print("  driver (with oracle)...")
        with_hyp = run_driver(client, scenario, oracle_library)
        print("  skeptic (with)...")
        with_skeptic = run_skeptic(client, with_hyp)
        print(f"    verdict: {with_skeptic['verdict']}")

        trials.append({
            "trial": i,
            "without_oracle": {"hypothesis": without_hyp, "skeptic_review": without_skeptic},
            "with_oracle": {"hypothesis": with_hyp, "skeptic_review": with_skeptic},
        })

    out_dir = base_dir / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "comparison.json"
    out_path.write_text(json.dumps({"ground_truth": ground_truth, "trials": trials}, indent=2), encoding="utf-8")
    print(f"\nWrote {N_TRIALS} paired trials to {out_path}")
    print("Ground truth (for scoring only, was never sent to any model call above):")
    print(f"  {ground_truth}")


if __name__ == "__main__":
    main()
