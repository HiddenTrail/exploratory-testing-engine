"""Generates a fresh oracle library for the analyze-endpoint scenario -
deliberately NOT reusing the 5 heuristics already chosen for token_purchase
(a different SUT). Instead, every "model"-type entry in the heuristics
catalog (experiments/oracle-agent-poc/heuristics/catalog.json) gets a fresh,
independent "does this even apply here" judgment against spec/spec.md - a
clean slate, not a hand-picked subset assumed to fit this domain.

Same call->validate->retry shape as every other run_live.py in this project
(each is self-contained, by convention - not shared with the others).
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
"is this weird" judge. Your ONLY job this round is the "{heuristic['name']}" heuristic ({heuristic['category']}):

{heuristic['description']}

You've been given a written spec of a system under test (its API and one real executed example) as the
user message - your sole source of truth. Do not assume anything about the system beyond what the spec
states or directly implies.

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
    spec_text = (base_dir / "spec" / "spec.md").read_text(encoding="utf-8")

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    model_heuristics = [h for h in catalog if h["type"] == "model"]
    print(f"Read spec ({len(spec_text)} chars). Judging {len(model_heuristics)} model-type catalog entries fresh - none pre-selected for this domain.")

    modeled = {}
    for heuristic in model_heuristics:
        print(f"\nJudging: {heuristic['keyword']} ({heuristic['category']})...")
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
        if result["applies"]:
            for v in result["vectors"]:
                print(f"    - {v['claim']}")
        modeled[heuristic["keyword"]] = {**result, "category": heuristic["category"], "name": heuristic["name"]}

    applies_count = sum(1 for v in modeled.values() if v["applies"])
    output = {"sut": "analyze_endpoint", "modeled": modeled}

    out_dir = base_dir / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "oracle_library.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n{applies_count}/{len(model_heuristics)} heuristics judged applicable. Wrote oracle library to {out_path}")


if __name__ == "__main__":
    main()
