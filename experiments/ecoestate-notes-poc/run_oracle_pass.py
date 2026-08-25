"""Generates a fresh oracle library for the EcoEstate notes API - a clean
slate like pattern-detection-oracle-poc's, not a hand-picked subset assumed
to fit this domain: every "model"-type entry in the heuristics catalog
(experiments/oracle-agent-poc/heuristics/catalog.json) gets an independent
"does this even apply here" judgment.

Unlike every prior oracle pass in this project, the spec here is NOT one
hand-written spec.md - it's every real file copied into spec/ from the
actual EcoEstate repo (README, product context, acceptance criteria, the
notes Gherkin scenarios, and the project's own QE knowledge base: known
issues, risk register, tech debt, test health, coverage tracker). All of it
is read and concatenated, not summarized or cherry-picked, so heuristics
like Security/Reliability see the same already-open risks (R-2026-006's
missing ownership check, R-2026-007's unbounded in-memory growth) a human
reading these docs would.

Same call->validate->retry shape as every other run_live.py in this
project - self-contained by convention, not shared with the others.
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3

CATALOG_PATH = Path(__file__).parent.parent / "oracle-agent-poc" / "heuristics" / "catalog.json"
SPEC_DIR = Path(__file__).parent / "spec"

ORACLE_FUNCTION_TOOL = {
    "name": "submit_oracle_model",
    "description": "Report whether this heuristic applies to the SUT, and if so, the concrete vectors it produces for this context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "applies": {
                "type": "boolean",
                "description": "Whether this heuristic is even relevant to this SUT, based on the spec given.",
            },
            "reasoning": {
                "type": "string",
                "description": "Why this heuristic does or doesn't apply here.",
            },
            "vectors": {
                "type": "array",
                "description": "Concrete, specific facts/expectations this heuristic produces for THIS system. Must be empty if applies is false.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "A single, specific, checkable statement."},
                        "rationale": {"type": "string", "description": "Why this claim follows from the heuristic in this context."},
                        "source": {
                            "type": "string",
                            "description": (
                                "Which spec file (if any) this claim is grounded in, e.g. 'qe-knowledge/risk-register.md "
                                "(R-2026-006)'. Empty string if this is general domain reasoning, not tied to a specific file."
                            ),
                        },
                    },
                    "required": ["claim", "rationale", "source"],
                },
            },
        },
        "required": ["applies", "reasoning", "vectors"],
    },
}


def load_spec_text() -> str:
    parts = []
    for path in sorted(SPEC_DIR.rglob("*")):
        if path.is_file():
            rel = path.relative_to(SPEC_DIR).as_posix()
            parts.append(f"=== FILE: {rel} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def build_system_prompt(heuristic: dict) -> str:
    return f"""You are one narrow, specialized oracle in an exploratory-testing system - not a general
"is this weird" judge. Your ONLY job this round is the "{heuristic['name']}" heuristic ({heuristic['category']}):

{heuristic['description']}

You've been given every real, current document this project's own team keeps about the system -
its README, product context, formal acceptance criteria, Gherkin scenarios, and its own internal
QE knowledge base (known issues, risk register, tech debt, test health, coverage tracker) - as the
user message, each section marked with "=== FILE: <path> ===". This is your sole source of truth;
don't assume anything about the system beyond what's stated or directly implied there. The whole
system covers property prices, maps, and postcodes, but your job is specifically to judge this
heuristic AS IT APPLIES TO THE NOTES FEATURE (the CRUD API for personal annotations on a postcode) -
say so explicitly if the heuristic has nothing notes-specific to say.

First decide: does this heuristic even apply to the notes feature, given everything in the spec?
Not every heuristic is relevant - be honest if it doesn't apply, rather than forcing a strained fit.

If it applies, produce a handful of concrete, specific vectors - individually checkable claims this
heuristic implies for the notes feature specifically. Where a claim is grounded in something an
actual file already states (a risk register entry, a known issue, an acceptance criterion), cite
that file and ID in the vector's "source" field rather than treating it as your own novel insight.
Where a claim is your own domain reasoning not tied to any specific document, leave "source" empty.
If it does not apply, return an empty vectors list.

Call submit_oracle_model with your answer."""


def validate_oracle_response(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]

    if not isinstance(data.get("applies"), bool):
        errors.append("'applies' must be a boolean")
    if not isinstance(data.get("reasoning"), str):
        errors.append("'reasoning' must be a string")

    vectors = data.get("vectors")
    if not isinstance(vectors, list):
        errors.append("'vectors' must be a list")
    else:
        if data.get("applies") is False and vectors:
            errors.append("'vectors' must be empty when 'applies' is false")
        for i, v in enumerate(vectors):
            if not isinstance(v, dict):
                errors.append(f"vectors[{i}] must be an object")
                continue
            if not isinstance(v.get("claim"), str) or not v["claim"]:
                errors.append(f"vectors[{i}].claim must be a non-empty string")
            if not isinstance(v.get("rationale"), str) or not v["rationale"]:
                errors.append(f"vectors[{i}].rationale must be a non-empty string")
            if not isinstance(v.get("source"), str):
                errors.append(f"vectors[{i}].source must be a string (empty if not file-grounded)")

    return errors


def call_tool_with_retry(client, *, system, tools, tool_name, user_message, max_tokens, validate_fn):
    messages = [{"role": "user", "content": user_message}]
    last_errors = ["no attempts made"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system, tools=tools,
            tool_choice={"type": "tool", "name": tool_name}, messages=messages,
        )
        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            last_errors = [f"no tool_use block (stop_reason={message.stop_reason})"]
            print(f"  attempt {attempt} produced no tool call - retrying")
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call the tool. Try again."})
            continue

        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input

        last_errors = errors
        print(f"  attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": "Invalid: " + "; ".join(errors) + ". Fix and call the tool again with a corrected, complete answer.",
                "is_error": True,
            }],
        })

    raise RuntimeError(f"Gave up after {MAX_ATTEMPTS} attempts, last errors: {last_errors}")


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    base_dir = Path(__file__).parent
    spec_text = load_spec_text()
    spec_files = sorted(p.relative_to(SPEC_DIR).as_posix() for p in SPEC_DIR.rglob("*") if p.is_file())
    print(f"Read {len(spec_files)} spec files ({len(spec_text)} chars total):")
    for f in spec_files:
        print(f"  - {f}")

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    model_heuristics = [h for h in catalog if h["type"] == "model"]
    print(f"\nJudging {len(model_heuristics)} model-type catalog entries fresh against the notes feature.")

    modeled = {}
    for heuristic in model_heuristics:
        print(f"\nJudging: {heuristic['keyword']} ({heuristic['category']})...")
        result = call_tool_with_retry(
            client,
            system=build_system_prompt(heuristic),
            tools=[ORACLE_FUNCTION_TOOL],
            tool_name="submit_oracle_model",
            user_message=spec_text,
            # 2048 was enough for a single hand-written spec.md but truncated (stop_reason=
            # "max_tokens") against this much larger 10-file real-doc spec, right after
            # "reasoning" and before "vectors" even started - confirmed via a live repro call.
            max_tokens=4096,
            validate_fn=validate_oracle_response,
        )
        print(f"  applies: {result['applies']}")
        if result["applies"]:
            for v in result["vectors"]:
                source_note = f" [{v['source']}]" if v["source"] else ""
                print(f"    - {v['claim']}{source_note}")
        modeled[heuristic["keyword"]] = {**result, "category": heuristic["category"], "name": heuristic["name"]}

    applies_count = sum(1 for v in modeled.values() if v["applies"])
    output = {"sut": "ecoestate_notes", "spec_files": spec_files, "modeled": modeled}

    out_dir = base_dir / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "oracle_library.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n{applies_count}/{len(model_heuristics)} heuristics judged applicable. Wrote oracle library to {out_path}")


if __name__ == "__main__":
    main()
