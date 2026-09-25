"""Consistency test bench for the oracle-prioritization scoring rubric: if we
score the SAME fixed set of ideas N independent times, how much does each
idea's score actually move around? This is the "test-retest reliability"
half of validating the scorer - not whether it agrees with a human, just
whether it agrees with itself.

The 42-idea set (results/idea_set.json) is a deterministic, real selection -
2 vectors per applicable heuristic category from ecoestate-notes-poc's
already-generated, already-verified oracle_library.json. Nothing here is
invented; every idea is a real claim that oracle pass produced.

Rubric (8 axes, 1-10 each, averaged and x10 for a 0-100 final score; "ease
to write" is deliberately NOT in that average - it's a separate testable_now
flag, so a high-value idea the current harness can't act on yet doesn't get
diluted into a mediocre score):
  gut, customer_impact, probability_of_occurrence, distinctiveness,
  prob_of_fix, ease_to_maintain, similarity, break_frequency

All 42 ideas are scored together in ONE call per repeat (not one call per
idea) to keep the call count sane - N_REPEATS calls total, not N_REPEATS x 42.
Each repeat is an independent, fresh call (no shared conversation history),
so any spread across repeats is genuine model stochasticity, not drift from
accumulated context.
"""

import json
import os
import statistics
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3
N_REPEATS = 10

BASE_DIR = Path(__file__).parent
IDEA_SET_PATH = BASE_DIR / "results" / "idea_set.json"
QE_KNOWLEDGE_DIR = Path(__file__).parent.parent / "ecoestate-notes-poc" / "spec" / "qe-knowledge"

AXES = [
    "gut", "customer_impact", "probability_of_occurrence", "distinctiveness",
    "prob_of_fix", "ease_to_maintain", "similarity", "break_frequency",
]

HARNESS_CAPABILITIES = """The current test harness (ecoestate-notes-poc/run_live.py) can only construct tests
of this shape: an HTTP method (GET/POST/PUT/DELETE), a path parameter (postalCode or note id), and a
JSON body (postalCode/content for POST, content for PUT). It cannot: send custom headers, simulate two
different user sessions/identities, control server-side timing/concurrency, inspect server internals,
or run anything client-side (the notes UI itself is untested by this harness - it only calls the API)."""


def build_system_prompt(qe_knowledge_text: str) -> str:
    return f"""You are scoring a fixed list of candidate test ideas for a notes CRUD API, using this
rubric. Score EVERY idea independently on its own merits - do not let one idea's score anchor another.

Rate each of these 8 axes 1 (lowest) to 10 (highest):
- gut: holistic "is this worth a test slot" first impression, independent of the other axes below.
- customer_impact: how bad would it be for a real user if this claim turns out to be true (i.e. the
  system actually behaves as the claim/risk describes)?
- probability_of_occurrence: how likely is a real user to actually hit the scenario this idea covers?
- distinctiveness: is this a systemic pattern likely to recur elsewhere in the codebase, or a narrow,
  local, one-off concern?
- prob_of_fix: if confirmed real, would this actually get prioritized and fixed? Use the real severity/
  priority already recorded in the project's own QE knowledge base below when the idea traces to a
  specific entry there - don't re-guess a severity that's already documented.
- ease_to_maintain: once written, would the resulting test be a simple, stable, deterministic check, or
  something fragile/flaky/multi-step?
- similarity: has this CLASS of problem shown up before in this project's own real history (below)?
- break_frequency: has this SPECIFIC feature had many confirmed issues before, per the real history below?

Also decide testable_now (true/false) and a short testability_note: can the CURRENT test harness
actually construct a test for this idea right now, given what it can do?

{HARNESS_CAPABILITIES}

This project's own real QE knowledge base (known issues, risk register, tech debt, test health) -
use this for similarity/break_frequency/prob_of_fix, don't invent history that isn't here:

{qe_knowledge_text}

Score every idea in the list you're given. Call submit_scores with one entry per idea_index."""


SCORING_TOOL = {
    "name": "submit_scores",
    "description": "Score every given idea on the 8-axis rubric plus testable_now.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idea_index": {"type": "integer"},
                        **{axis: {"type": "integer", "description": f"1-10, see system prompt for {axis}."} for axis in AXES},
                        "testable_now": {"type": "boolean"},
                        "testability_note": {"type": "string"},
                    },
                    "required": ["idea_index", *AXES, "testable_now", "testability_note"],
                },
            },
        },
        "required": ["scores"],
    },
}


def validate_scores(data, expected_count: int) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    scores = data.get("scores")
    if not isinstance(scores, list) or len(scores) != expected_count:
        errors.append(f"'scores' must be a list of exactly {expected_count} entries, got {len(scores) if isinstance(scores, list) else type(scores).__name__}")
        return errors
    seen_indices = set()
    for i, s in enumerate(scores):
        if not isinstance(s, dict):
            errors.append(f"scores[{i}] must be an object")
            continue
        idx = s.get("idea_index")
        if not isinstance(idx, int):
            errors.append(f"scores[{i}].idea_index must be an integer")
        else:
            seen_indices.add(idx)
        for axis in AXES:
            v = s.get(axis)
            if not isinstance(v, int) or not (1 <= v <= 10):
                errors.append(f"scores[{i}].{axis} must be an integer 1-10")
        if "testable_now" in s and not isinstance(s["testable_now"], bool):
            errors.append(f"scores[{i}].testable_now must be a boolean")
    if seen_indices != set(range(expected_count)):
        errors.append(f"idea_index values must cover exactly 0..{expected_count - 1} with no gaps or repeats")
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


def final_score(entry: dict) -> float:
    return round(sum(entry[axis] for axis in AXES) / len(AXES) * 10, 1)


def tier(score: float) -> str:
    if score >= 75:
        return "test_it"
    if score >= 25:
        return "maybe"
    return "nope"


def main():
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    client = Anthropic(api_key=api_key)

    ideas = json.loads(IDEA_SET_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(ideas)} real ideas from {IDEA_SET_PATH.name}")

    qe_knowledge_text = "\n\n".join(
        f"=== {p.name} ===\n{p.read_text(encoding='utf-8')}" for p in sorted(QE_KNOWLEDGE_DIR.glob("*.md"))
    )
    system = build_system_prompt(qe_knowledge_text)

    ideas_payload = json.dumps([
        {"idea_index": i, "keyword": idea["keyword"], "category": idea["category"],
         "claim": idea["claim"], "rationale": idea["rationale"], "source": idea["source"]}
        for i, idea in enumerate(ideas)
    ], indent=2)

    all_runs = []
    for run_num in range(1, N_REPEATS + 1):
        print(f"\n=== Scoring run {run_num}/{N_REPEATS} ===")
        result = call_tool_with_retry(
            client, system=system, tools=[SCORING_TOOL], tool_name="submit_scores",
            user_message=ideas_payload, max_tokens=12000,
            validate_fn=lambda d: validate_scores(d, len(ideas)),
        )
        by_index = {s["idea_index"]: s for s in result["scores"]}
        all_runs.append(by_index)
        tiers = [tier(final_score(by_index[i])) for i in range(len(ideas))]
        print(f"  tiers: test_it={tiers.count('test_it')} maybe={tiers.count('maybe')} nope={tiers.count('nope')}")

    out_path = BASE_DIR / "results" / "consistency_runs.json"
    out_path.write_text(json.dumps(all_runs, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_runs)} runs to {out_path}")

    # Per-idea variance summary
    summary = []
    for i, idea in enumerate(ideas):
        final_scores = [final_score(run[i]) for run in all_runs]
        tiers_per_run = [tier(s) for s in final_scores]
        axis_stats = {}
        for axis in AXES:
            values = [run[i][axis] for run in all_runs]
            axis_stats[axis] = {"mean": round(statistics.mean(values), 2), "stdev": round(statistics.pstdev(values), 2)}
        testable_votes = [run[i]["testable_now"] for run in all_runs]
        summary.append({
            "idea_index": i, "keyword": idea["keyword"], "claim": idea["claim"][:120],
            "final_score_mean": round(statistics.mean(final_scores), 1),
            "final_score_stdev": round(statistics.pstdev(final_scores), 1),
            "final_score_range": [min(final_scores), max(final_scores)],
            "tiers_seen": sorted(set(tiers_per_run)),
            "tier_flipped": len(set(tiers_per_run)) > 1,
            "testable_now_agreement": f"{sum(testable_votes)}/{len(testable_votes)}",
            "axis_stats": axis_stats,
        })

    summary_path = BASE_DIR / "results" / "consistency_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote per-idea variance summary to {summary_path}")

    flipped = [s for s in summary if s["tier_flipped"]]
    print(f"\n{len(flipped)}/{len(ideas)} ideas flipped tier across {N_REPEATS} runs.")


if __name__ == "__main__":
    main()
