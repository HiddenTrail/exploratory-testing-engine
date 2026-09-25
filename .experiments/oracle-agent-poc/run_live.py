"""Oracle Agent PoC: a first, deliberately narrow slice of the "Oracle
layer" described in docs/exploratory-testing-engine-concept.md §3.4 -
distributing judgment across narrow, specialized heuristics instead of one
model just deciding "is this weird" alone.

This agent does NOT test the system - it never calls a live SUT. It runs a
heuristic pass over spec/spec.md (the sole input) and produces a single
JSON "oracle library": for each of 5 chosen heuristics (2 SFDIPOT
dimensions - Data, Function - plus 3 FEW HICCUPPS heuristics - Claims,
Comparable Products, Self-Consistency), it decides whether the heuristic
even applies to this SUT, and if so, produces concrete vectors (specific,
checkable facts/expectations) for this context.

The other 5 SFDIPOT dimensions (Structure, Interfacing, Platform,
Operations, Time) are deliberately not modeled in this PoC - explicitly
placeholdered in the output, not silently omitted, so a future phase can
fill them in without restructuring anything.

Explicitly deferred, not built here: the Driver updating this library as
it tests, and actually wiring it into the real token_purchase adapter's
onboarding_extra. This phase's job stops at producing a good library and
lightly checking it's the right shape to be useful later.
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# Model-generated text can contain non-ASCII characters that the default
# Windows console codec can't encode, crashing a plain print().
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3

HEURISTICS = [
    {
        "key": "data",
        "name": "Data (SFDIPOT)",
        "description": (
            "What KINDS of data does this system handle - financial values, PII-adjacent fields, "
            "categorical/enum fields, temporal fields, etc.? Focus on the nature and sensitivity of "
            "the data itself, not the operations performed on it."
        ),
    },
    {
        "key": "function",
        "name": "Function (SFDIPOT)",
        "description": (
            "What does this system's operations actually DO, semantically - not the literal field "
            "names, but the real-world actions/effects (e.g. 'authorizes and charges a payment "
            "method', 'applies tiered bulk pricing', 'tracks a running balance')."
        ),
    },
    {
        "key": "claims",
        "name": "Claims (spec-conformance)",
        "description": (
            "What EXPLICIT, documented claims does the spec make that can be mechanically checked "
            "against any real response? (e.g. 'decline_reason must be one of these N documented "
            "values', 'credits_purchased must be 0 if declined')."
        ),
    },
    {
        "key": "comparable_products",
        "name": "Comparable products",
        "description": (
            "Does this system belong to a recognizable category of real-world systems? If so, what "
            "conventions/behaviors do systems in that category typically get right (or wrong) that "
            "this system should be checked against, even if never explicitly documented?"
        ),
    },
    {
        "key": "self_consistency",
        "name": "Self-consistency (Product)",
        "description": (
            "What cross-field or cross-response invariants SHOULD hold within this system's own "
            "documented behavior, even if never explicitly stated as a single rule? (e.g. 'if status "
            "is declined, credits_purchased and total_charged must both be 0')."
        ),
    },
]

NOT_MODELED_DIMENSIONS = ["structure", "interfacing", "platform", "operations", "time"]

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
                    },
                    "required": ["claim", "rationale"],
                },
            },
        },
        "required": ["applies", "reasoning", "vectors"],
    },
}


def build_system_prompt(heuristic: dict) -> str:
    return f"""You are one narrow, specialized oracle in an exploratory-testing system - not a general
"is this weird" judge. Your ONLY job this round is the "{heuristic['name']}" heuristic:

{heuristic['description']}

You've been given a written spec of a system under test (its API, known data, and one real executed
example) as the user message - your sole source of truth. Do not assume anything about the system
beyond what the spec states or directly implies.

First decide: does this heuristic even apply to this system, given the spec? Not every heuristic is
relevant to every system - be honest if it doesn't apply here, rather than forcing a strained fit.

If it applies, produce a handful of concrete, specific vectors - individually checkable claims this
heuristic implies for THIS system, not generic textbook statements that would apply to any API. If it
does not apply, return an empty vectors list.

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

    return errors


def call_tool_with_retry(client, *, system, tools, tool_name, user_message, max_tokens, validate_fn):
    """Same call->validate->retry shape every experiment's run_live.py
    uses - retries feed the model's own malformed call and the concrete
    validation errors back as a tool_result, so a systematic
    misunderstanding has a chance to self-correct."""
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
    spec_path = base_dir / "spec" / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    print(f"Read spec from {spec_path} ({len(spec_text)} chars).")

    modeled = {}
    for heuristic in HEURISTICS:
        print(f"\nRunning heuristic: {heuristic['name']}...")
        result = call_tool_with_retry(
            client,
            system=build_system_prompt(heuristic),
            tools=[ORACLE_FUNCTION_TOOL],
            tool_name="submit_oracle_model",
            user_message=spec_text,
            max_tokens=1536,
            validate_fn=validate_oracle_response,
        )
        print(f"  applies: {result['applies']}")
        print(f"  reasoning: {result['reasoning']}")
        for v in result["vectors"]:
            print(f"    - {v['claim']}")
        modeled[heuristic["key"]] = result

    not_modeled = {
        dim: {"modeled": False, "reason": "Not implemented in this PoC - skipped by design."}
        for dim in NOT_MODELED_DIMENSIONS
    }

    output = {"sut": "token_purchase", "modeled": modeled, "not_modeled": not_modeled}

    out_dir = base_dir / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "oracle_library.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nWrote oracle library to {out_path}")


if __name__ == "__main__":
    main()
