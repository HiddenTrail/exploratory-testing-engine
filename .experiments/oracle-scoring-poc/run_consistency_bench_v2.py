"""v2 of the consistency bench: adds the "know it or say 5" reliability
mechanism, plus the 4-tier grading model, over the same 42-idea set used by
v1 (run_consistency_bench.py) - so v1 and v2's results are directly
comparable, same ideas, same N_REPEATS, same model.

The reliability mechanism has two tiers, matched to how verifiable each axis
actually is - a self-reported "I don't know" isn't trusted on its own,
because that's exactly the kind of claim this project has already caught
being unreliable (the oracle bias probe) or just wrong (TD-2026-004):

  Tier 1 - similarity, break_frequency, prob_of_fix: these are SUPPOSED to be
  grounded in the project's own real QE history. Any score other than 5
  must come with a citation (e.g. "R-2026-006"). The citation is verified in
  CODE against the real qe-knowledge text, not trusted - if it's missing or
  doesn't actually appear there, the axis is force-overridden to 5 regardless
  of what number the model submitted. This makes "say 5 when you don't know"
  a hard, code-enforced constraint on these three axes, not a self-report.

  Tier 2 - gut, customer_impact, probability_of_occurrence, distinctiveness,
  ease_to_maintain: inherently judgment calls, not citation-checkable. Each
  gets a self-reported confidence tag (grounded/inferred/unknown) and the
  EFFECTIVE value used in the final score is shrunk toward 5 by how
  confident that tag is - grounded=full weight, inferred=partial, unknown=
  all the way to 5. This is Bayesian shrinkage toward a neutral prior when
  the evidence for a claim is genuinely weak, not a binary switch.

Grading model (this run's second change): 4 tiers instead of 3 -
  prio1 >=80, prio2 [60,80), maybe (25,60), not_relevant <=25
chosen for better test-budget allocation granularity at the top end. Real
per-idea data from v1 showed this specific boundary placement doesn't
reduce flip-proneness on its own (a new boundary at 60 sits in a dense part
of this dataset's score distribution) - the reliability mechanism above is
the part expected to actually reduce noise; the tier change is evaluated
here on its own separate merits (does it help prioritize?), not as a fix
for variance.
"""

import json
import os
import re
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

CITED_AXES = ["similarity", "break_frequency", "prob_of_fix"]
CONFIDENCE_AXES = ["gut", "customer_impact", "probability_of_occurrence", "distinctiveness", "ease_to_maintain"]
ALL_AXES = CONFIDENCE_AXES + CITED_AXES
CONFIDENCE_WEIGHT = {"grounded": 1.0, "inferred": 0.6, "unknown": 0.0}

# Real entry-ID pattern used across this project's QE knowledge base docs.
CITATION_ID_RE = re.compile(r"\b(?:R|KI|TD|TH|AC)-[A-Z]*-?\d{3,4}-\d{2,3}\b", re.IGNORECASE)

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
- customer_impact: how bad would it be for a real user if this claim turns out to be true?
- probability_of_occurrence: how likely is a real user to actually hit the scenario this idea covers?
- distinctiveness: is this a systemic pattern likely to recur elsewhere, or a narrow, local, one-off concern?
- ease_to_maintain: once written, would the resulting test be simple and stable, or fragile/flaky/multi-step?
- prob_of_fix: if confirmed real, would this actually get prioritized and fixed?
- similarity: has this CLASS of problem shown up before in this project's own real history?
- break_frequency: has this SPECIFIC feature had many confirmed issues before?

IMPORTANT - do not fabricate confidence you don't have. This rubric has two different honesty mechanisms
depending on the axis, because some axes are checkable against real documents and some aren't:

For gut, customer_impact, probability_of_occurrence, distinctiveness, ease_to_maintain: alongside each
1-10 score, also give a confidence tag - "grounded" (directly supported by something stated in the idea
or the real history below), "inferred" (a reasonable domain judgment, not directly evidenced), or
"unknown" (you genuinely have no real basis to judge this - the current material doesn't support any
confident answer). Do not use "unknown" as a way to avoid committing to a real judgment you actually
have grounds for; use it only when you truly have no basis. An honest "unknown" is scored as neutral (5)
automatically - you don't need to pick a fake middle number yourself, just tag it truthfully.

For similarity, break_frequency, and prob_of_fix specifically: these three are meant to reflect this
project's own REAL documented history, not general impressions. Give a citation (e.g. "R-2026-006",
"KI-2026-008", "TD-2026-004") to a SPECIFIC entry in the QE knowledge base below whenever your score is
anything other than a neutral 5. If no specific entry actually supports a non-neutral score, don't invent
one - score it 5 and leave the citation empty. Citations are checked against the real document text, so
an invented or approximate citation will be caught and the score discarded anyway - there's no advantage
to guessing one.

Also decide testable_now (true/false) and a short testability_note: can the CURRENT test harness
actually construct a test for this idea right now, given what it can do?

{HARNESS_CAPABILITIES}

This project's own real QE knowledge base (known issues, risk register, tech debt, test health):

{qe_knowledge_text}

Score every idea in the list you're given. Call submit_scores with one entry per idea_index."""


SCORING_TOOL = {
    "name": "submit_scores",
    "description": "Score every given idea on the 8-axis rubric, with confidence tags or citations as required, plus testable_now.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idea_index": {"type": "integer"},
                        **{
                            axis: {"type": "integer", "description": f"1-10, see system prompt for {axis}."}
                            for axis in CONFIDENCE_AXES
                        },
                        **{
                            f"{axis}_confidence": {"type": "string", "enum": ["grounded", "inferred", "unknown"]}
                            for axis in CONFIDENCE_AXES
                        },
                        **{
                            axis: {"type": "integer", "description": f"1-10, see system prompt for {axis}."}
                            for axis in CITED_AXES
                        },
                        **{
                            f"{axis}_citation": {"type": "string", "description": "Real entry ID, or empty string if score is 5."}
                            for axis in CITED_AXES
                        },
                        "testable_now": {"type": "boolean"},
                        "testability_note": {"type": "string"},
                    },
                    "required": [
                        "idea_index",
                        *ALL_AXES,
                        *(f"{a}_confidence" for a in CONFIDENCE_AXES),
                        *(f"{a}_citation" for a in CITED_AXES),
                        "testable_now", "testability_note",
                    ],
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
        for axis in ALL_AXES:
            v = s.get(axis)
            if not isinstance(v, int) or not (1 <= v <= 10):
                errors.append(f"scores[{i}].{axis} must be an integer 1-10")
        for axis in CONFIDENCE_AXES:
            v = s.get(f"{axis}_confidence")
            if v not in ("grounded", "inferred", "unknown"):
                errors.append(f"scores[{i}].{axis}_confidence must be grounded/inferred/unknown")
        for axis in CITED_AXES:
            if not isinstance(s.get(f"{axis}_citation"), str):
                errors.append(f"scores[{i}].{axis}_citation must be a string (may be empty)")
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


def citation_is_real(citation: str, qe_text: str) -> bool:
    """Extract a real-looking entry ID from the model's citation and check it
    actually appears in the real QE knowledge text - don't trust the string
    verbatim (the model could paraphrase or slightly misremember an ID)."""
    if not citation:
        return False
    match = CITATION_ID_RE.search(citation)
    if not match:
        return False
    return match.group(0).upper() in qe_text.upper()


def effective_axis_values(entry: dict, qe_text: str) -> dict:
    """Returns {axis: (effective_value, basis)} - basis explains why the raw
    score was kept, shrunk, or overridden, for auditability."""
    out = {}
    for axis in CONFIDENCE_AXES:
        raw = entry[axis]
        conf = entry.get(f"{axis}_confidence", "unknown")
        weight = CONFIDENCE_WEIGHT.get(conf, 0.0)
        effective = weight * raw + (1 - weight) * 5
        out[axis] = (effective, f"confidence={conf} (weight={weight})")
    for axis in CITED_AXES:
        raw = entry[axis]
        citation = entry.get(f"{axis}_citation", "")
        if citation_is_real(citation, qe_text):
            out[axis] = (raw, f"cited={citation} (verified)")
        else:
            reason = "no citation given" if not citation else f"citation '{citation}' not found in real docs"
            out[axis] = (5, f"forced to 5: {reason}")
    return out


def final_score(entry: dict, qe_text: str) -> float:
    values = effective_axis_values(entry, qe_text)
    return round(sum(v for v, _ in values.values()) / len(values) * 10, 1)


def tier(score: float) -> str:
    if score >= 80:
        return "prio1"
    if score >= 60:
        return "prio2"
    if score > 25:
        return "maybe"
    return "not_relevant"


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
            user_message=ideas_payload, max_tokens=20000,
            validate_fn=lambda d: validate_scores(d, len(ideas)),
        )
        by_index = {s["idea_index"]: s for s in result["scores"]}
        all_runs.append(by_index)
        tiers = [tier(final_score(by_index[i], qe_knowledge_text)) for i in range(len(ideas))]
        forced_count = sum(
            1 for i in range(len(ideas))
            for axis in CITED_AXES
            if "forced" in effective_axis_values(by_index[i], qe_knowledge_text)[axis][1]
        )
        unknown_count = sum(
            1 for i in range(len(ideas))
            for axis in CONFIDENCE_AXES
            if by_index[i].get(f"{axis}_confidence") == "unknown"
        )
        print(f"  tiers: prio1={tiers.count('prio1')} prio2={tiers.count('prio2')} maybe={tiers.count('maybe')} not_relevant={tiers.count('not_relevant')}")
        print(f"  {forced_count}/{len(ideas) * len(CITED_AXES)} cited-axis scores forced to 5 (uncited/unverifiable); {unknown_count}/{len(ideas) * len(CONFIDENCE_AXES)} confidence-axis scores tagged 'unknown'")

    out_path = BASE_DIR / "results" / "consistency_runs_v2.json"
    out_path.write_text(json.dumps(all_runs, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_runs)} runs to {out_path}")

    # Per-idea variance summary, using EFFECTIVE (post-shrinkage/override) values
    summary = []
    for i, idea in enumerate(ideas):
        final_scores = [final_score(run[i], qe_knowledge_text) for run in all_runs]
        tiers_per_run = [tier(s) for s in final_scores]
        axis_stats = {}
        for axis in ALL_AXES:
            eff_values = [effective_axis_values(run[i], qe_knowledge_text)[axis][0] for run in all_runs]
            axis_stats[axis] = {"mean": round(statistics.mean(eff_values), 2), "stdev": round(statistics.pstdev(eff_values), 2)}
        testable_votes = [run[i]["testable_now"] for run in all_runs]
        confidence_tags = {axis: [run[i].get(f"{axis}_confidence") for run in all_runs] for axis in CONFIDENCE_AXES}
        citations = {axis: [run[i].get(f"{axis}_citation") for run in all_runs] for axis in CITED_AXES}
        summary.append({
            "idea_index": i, "keyword": idea["keyword"], "claim": idea["claim"][:120],
            "final_score_mean": round(statistics.mean(final_scores), 1),
            "final_score_stdev": round(statistics.pstdev(final_scores), 1),
            "final_score_range": [min(final_scores), max(final_scores)],
            "tiers_seen": sorted(set(tiers_per_run)),
            "tier_flipped": len(set(tiers_per_run)) > 1,
            "testable_now_agreement": f"{sum(testable_votes)}/{len(testable_votes)}",
            "axis_stats": axis_stats,
            "confidence_tags": confidence_tags,
            "citations": citations,
        })

    summary_path = BASE_DIR / "results" / "consistency_summary_v2.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote per-idea variance summary to {summary_path}")

    flipped = [s for s in summary if s["tier_flipped"]]
    print(f"\n{len(flipped)}/{len(ideas)} ideas flipped tier across {N_REPEATS} runs (v2, 4-tier).")


if __name__ == "__main__":
    main()
