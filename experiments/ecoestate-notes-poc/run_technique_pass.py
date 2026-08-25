"""Demonstration: oracles that are more than the specs. Applies 4 HTSM
General Test Techniques (domain_testing, stress_testing, risk_testing,
scenario_testing - cataloged in oracle-agent-poc/heuristics/catalog.json,
never used in any run so far) against a deliberately BARE shape description
of the notes API - method, path, field name, inferred type only. No
validation rules, no business docs, none of the acceptance-criteria/risk-
register/known-issues material every other oracle pass in this project has
read. Just "it's an API, it's a GET/POST/PUT/DELETE, it's a string."

Point of the exercise: if this independently surfaces the same real concerns
(ownership gap, unbounded growth, no persistence) that the doc-grounded
pass only found by reading actual project docs, that's real evidence
shape-driven reasoning finds genuine things on its own - not just
paraphrasing what it was shown.

Each idea also gets a `prerequisite` field, not a pass/fail: an idea that
needs information or a harness capability not available right now (a real
note id, custom-header support, multi-session simulation) is held, not
discarded - worth revisiting once a longer-running engagement has that
information, rather than lost the moment it can't be acted on immediately.

Self-contained per this project's convention.
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

# Deliberately bare - no docs, no validation rules, no examples of real values.
# Exactly the "it's an API, it's a GET/POST/PUT/DELETE, it's a string" framing.
BARE_SHAPE = """A resource called "notes", exposed over HTTP as 4 endpoints:

GET  /api/notes/:postalCode   - postalCode: string
POST /api/notes                - body: { postalCode: string, content: string }
PUT  /api/notes/:id            - id: string, body: { content: string }
DELETE /api/notes/:id          - id: string

That is the entire interface. No other information about this system, its
validation rules, its storage, or its intended users has been provided."""

TECHNIQUES = [
    {
        "keyword": "domain_testing",
        "name": "Domain Testing",
        "description": (
            "Partition the data: look at data the product processes (including outputs, not just "
            "inputs), decide which specific values to test with (boundary, typical, convenient, "
            "invalid, best-representative), consider combinations worth testing together, and use "
            "inputs that force the whole range of possible outputs to occur."
        ),
    },
    {
        "keyword": "stress_testing",
        "name": "Stress Testing",
        "description": (
            "Overwhelm the product: look for sub-systems or functions vulnerable to overload or "
            "breakage under challenging data or constrained resources, then select or generate "
            "challenging conditions to test with (large or complex data, high loads, long runs, "
            "many test cases, low memory)."
        ),
    },
    {
        "keyword": "risk_testing",
        "name": "Risk Testing",
        "description": (
            "Imagine a problem, then look for it: what kinds of problems could the product have, "
            "which matter most, how would you detect them if present, and design tests "
            "specifically to reveal them - consulting experts, design docs, past bug reports, or "
            "risk heuristics as needed."
        ),
    },
    {
        "keyword": "scenario_testing",
        "name": "Scenario Testing",
        "description": (
            "Test to a compelling story: think about everything going on around the product, "
            "design tests involving meaningful and complex interactions with it, where a good "
            "scenario is a compelling story of how someone who matters might do something that "
            "matters with the product."
        ),
    },
]

TECHNIQUE_TOOL = {
    "name": "submit_technique_ideas",
    "description": "Report concrete test ideas produced by applying this ONE technique to the bare shape given.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "description": "A handful of concrete, specific test ideas - not generic textbook advice.",
                "items": {
                    "type": "object",
                    "properties": {
                        "idea": {"type": "string", "description": "A single, specific, concrete test idea."},
                        "technique_reasoning": {
                            "type": "string",
                            "description": "How applying this technique's procedure led to this specific idea.",
                        },
                        "prerequisite": {
                            "type": "string",
                            "description": (
                                "What's missing to act on this idea right now, if anything - e.g. 'requires a "
                                "real note id from a prior create', 'requires the harness to support custom "
                                "headers', 'requires knowing the actual max length'. Empty string if it's "
                                "immediately actionable with only what's given above."
                            ),
                        },
                    },
                    "required": ["idea", "technique_reasoning", "prerequisite"],
                },
            },
        },
        "required": ["ideas"],
    },
}


def build_system_prompt(technique: dict) -> str:
    return f"""You are applying ONE specific general test-design technique to a system you know almost
nothing about - not reasoning from any project documentation, business rules, or specification,
because none has been given to you. Your only input is the bare interface shape below.

{BARE_SHAPE}

Your technique - "{technique['name']}":

{technique['description']}

Apply this technique's procedure literally to the shape above. Draw only on general knowledge of
what systems with fields and methods of these general kinds (a string field, a GET/POST/PUT/DELETE
resource, a path parameter that looks like an identifier) commonly need testing for - not on any
assumption about what THIS particular system's business rules, validation, or storage actually are,
since you don't know any of that. If an idea needs something you don't have (a real id, a known
value range, a harness capability), say so in "prerequisite" rather than dropping the idea - it may
become answerable later as more information becomes available in a longer-running engagement.

Call submit_technique_ideas with your answer."""


def validate_technique_response(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    ideas = data.get("ideas")
    if not isinstance(ideas, list) or not ideas:
        errors.append("'ideas' must be a non-empty list")
    else:
        for i, idea in enumerate(ideas):
            if not isinstance(idea, dict):
                errors.append(f"ideas[{i}] must be an object")
                continue
            for key in ("idea", "technique_reasoning", "prerequisite"):
                if key not in idea or not isinstance(idea[key], str):
                    errors.append(f"ideas[{i}].{key} must be a string")
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
            print(f"  attempt {attempt}: no tool call - retrying")
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call the tool. Try again."})
            continue
        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input
        print(f"  attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result", "tool_use_id": tool_use.id,
                "content": "Invalid: " + "; ".join(errors) + ". Fix and call the tool again.",
                "is_error": True,
            }],
        })
    raise RuntimeError(f"Gave up after {MAX_ATTEMPTS} attempts")


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    results = {}
    for technique in TECHNIQUES:
        print(f"\n=== {technique['name']} ===")
        result = call_tool_with_retry(
            client, system=build_system_prompt(technique), tools=[TECHNIQUE_TOOL],
            tool_name="submit_technique_ideas", user_message="Apply the technique now.",
            max_tokens=2048, validate_fn=validate_technique_response,
        )
        for idea in result["ideas"]:
            prereq = f" [needs: {idea['prerequisite']}]" if idea["prerequisite"] else ""
            print(f"  - {idea['idea']}{prereq}")
        results[technique["keyword"]] = result["ideas"]

    out_path = Path(__file__).parent / "results" / "technique_ideas.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
