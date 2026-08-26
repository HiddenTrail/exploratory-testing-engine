"""v3 of the consistency bench - responds directly to what v1/v2 measured:

1. DEDUP BEFORE SCORING (new, zero extra API calls). The noisiest v1/v2 ideas
   turned out to be near-duplicates - the same underlying fact restated under
   several different heuristic lenses ("data lost on restart" appeared under
   structure/reliability/platform/time/development). Scoring each restatement
   independently and expecting the same number back was fighting an
   unnecessary battle. A cheap, local, zero-cost Jaccard token-overlap pass
   clusters near-duplicate claims BEFORE they ever reach the model - real
   clusters found on this exact 42-idea set: non-deterministic list ordering
   (5 restatements), the ownership gap / R-2026-006 (3), restart data loss (3),
   and unbounded growth (3) - 14 ideas collapse into 4 canonical ones.

2. BACK TO 3 TIERS. v2's 4-tier scheme (prio1/prio2/maybe/not_relevant) didn't
   reduce flip-proneness on real data - it just moved the boundary-hugging
   problem to a new line at 60. Simpler is not worse here.

3. CITATION-GATING NARROWED, SELF-REPORTED CONFIDENCE DROPPED. Only
   `similarity` and `break_frequency` are genuinely ABOUT history - keep the
   code-verified "cite it or it's forced to 5" rule for those two only.
   `prob_of_fix` is forward-looking (would the team fix this), not
   historical, so the citation requirement was too strict there and was
   likely responsible for a lot of the pointless compression in v2 - it's
   back to a plain judgment axis. The self-reported "unknown" confidence tag
   from v2 is dropped entirely - it was asked for and never actually
   answered honestly (0-1/210 real uses across 10 runs), so it wasn't buying
   anything a self-report is supposed to buy. Confidence is reported
   separately now (citations_verified: X/2), never folded into the score -
   see the module docstring discussion this is the direct answer to.
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
DEDUP_THRESHOLD = 0.25

BASE_DIR = Path(__file__).parent
IDEA_SET_PATH = BASE_DIR / "results" / "idea_set.json"
QE_KNOWLEDGE_DIR = Path(__file__).parent.parent / "ecoestate-notes-poc" / "spec" / "qe-knowledge"

CITED_AXES = ["similarity", "break_frequency"]
JUDGMENT_AXES = ["gut", "customer_impact", "probability_of_occurrence", "distinctiveness", "ease_to_maintain", "prob_of_fix"]
ALL_AXES = JUDGMENT_AXES + CITED_AXES

CITATION_ID_RE = re.compile(r"\b(?:R|KI|TD|TH|AC)-[A-Z]*-?\d{3,4}-\d{2,3}\b", re.IGNORECASE)
STOPWORDS = set(
    "the a an is are was were be been being to of in on for with and or not no this that these those "
    "it its as by from at if when then must should returns return response request server client note "
    "notes api endpoint field content value should must may can".split()
)

HARNESS_CAPABILITIES = """The current test harness (ecoestate-notes-poc/run_live.py) can only construct tests
of this shape: an HTTP method (GET/POST/PUT/DELETE), a path parameter (postalCode or note id), and a
JSON body (postalCode/content for POST, content for PUT). It cannot: send custom headers, simulate two
different user sessions/identities, control server-side timing/concurrency, inspect server internals,
or run anything client-side (the notes UI itself is untested by this harness - it only calls the API)."""


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_ideas(ideas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Union-find clustering on claim-token Jaccard similarity. Returns
    (deduplicated_ideas, cluster_report) - the canonical member of each
    cluster is the one with the longest (most detailed) claim text."""
    n = len(ideas)
    tokens = [tokenize(idea["claim"]) for idea in ideas]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(tokens[i], tokens[j]) >= DEDUP_THRESHOLD:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    deduped = []
    cluster_report = []
    for members in clusters.values():
        canonical_idx = max(members, key=lambda m: len(ideas[m]["claim"]))
        canonical = dict(ideas[canonical_idx])
        absorbed = [m for m in members if m != canonical_idx]
        canonical["merged_from"] = [
            {"keyword": ideas[m]["keyword"], "category": ideas[m]["category"], "claim": ideas[m]["claim"]}
            for m in absorbed
        ]
        canonical["original_indices"] = members
        deduped.append(canonical)
        if absorbed:
            cluster_report.append({
                "canonical_keyword": ideas[canonical_idx]["keyword"],
                "canonical_claim": ideas[canonical_idx]["claim"],
                "absorbed": [{"keyword": ideas[m]["keyword"], "claim": ideas[m]["claim"]} for m in absorbed],
            })
    return deduped, cluster_report


def build_system_prompt(qe_knowledge_text: str) -> str:
    return f"""You are scoring a fixed list of candidate test ideas for a notes CRUD API, using this
rubric. Score EVERY idea independently on its own merits - do not let one idea's score anchor another.

Rate each of these 8 axes 1 (lowest) to 10 (highest):
- gut: holistic "is this worth a test slot" first impression, independent of the other axes below.
- customer_impact: how bad would it be for a real user if this claim turns out to be true?
- probability_of_occurrence: how likely is a real user to actually hit the scenario this idea covers?
- distinctiveness: is this a systemic pattern likely to recur elsewhere, or a narrow, local, one-off concern?
- ease_to_maintain: once written, would the resulting test be simple and stable, or fragile/flaky/multi-step?
- prob_of_fix: if confirmed real, would this actually get prioritized and fixed? A plain judgment call -
  use real severity from the QE knowledge base below if the idea traces to a specific entry, otherwise
  use your own reasonable judgment about this project's priorities. No citation required for this one.
- similarity: has this CLASS of problem shown up before in this project's own real history (below)?
- break_frequency: has this SPECIFIC feature had many confirmed issues before, per the real history below?

For similarity and break_frequency specifically - and ONLY these two - a score other than a neutral 5
must come with a citation (e.g. "R-2026-006", "KI-2026-008") to a SPECIFIC entry in the QE knowledge base
below. These two axes are genuinely about documented history, not general impression - if no specific
entry supports a non-neutral score, score it 5 and leave the citation empty rather than guessing. The
other 6 axes are plain judgment calls - just give your honest best number, no citation needed.

Also decide testable_now (true/false) and a short testability_note: can the CURRENT test harness
actually construct a test for this idea right now, given what it can do?

{HARNESS_CAPABILITIES}

This project's own real QE knowledge base (known issues, risk register, tech debt, test health):

{qe_knowledge_text}

Score every idea in the list you're given. Call submit_scores with one entry per idea_index."""


SCORING_TOOL = {
    "name": "submit_scores",
    "description": "Score every given idea on the 8-axis rubric, with citations for similarity/break_frequency, plus testable_now.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idea_index": {"type": "integer"},
                        **{axis: {"type": "integer", "description": f"1-10, see system prompt for {axis}."} for axis in JUDGMENT_AXES},
                        **{axis: {"type": "integer", "description": f"1-10, see system prompt for {axis}."} for axis in CITED_AXES},
                        **{f"{axis}_citation": {"type": "string", "description": "Real entry ID, or empty string if score is 5."} for axis in CITED_AXES},
                        "testable_now": {"type": "boolean"},
                        "testability_note": {"type": "string"},
                    },
                    "required": [
                        "idea_index", *ALL_AXES, *(f"{a}_citation" for a in CITED_AXES),
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
        if isinstance(idx, int):
            seen_indices.add(idx)
        else:
            errors.append(f"scores[{i}].idea_index must be an integer")
        for axis in ALL_AXES:
            v = s.get(axis)
            if not isinstance(v, int) or not (1 <= v <= 10):
                errors.append(f"scores[{i}].{axis} must be an integer 1-10")
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
    if not citation:
        return False
    match = CITATION_ID_RE.search(citation)
    if not match:
        return False
    return match.group(0).upper() in qe_text.upper()


def effective_axis_values(entry: dict, qe_text: str) -> dict:
    out = {}
    for axis in JUDGMENT_AXES:
        out[axis] = (entry[axis], "judgment (face value)")
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


def citations_verified_count(entry: dict, qe_text: str) -> int:
    values = effective_axis_values(entry, qe_text)
    return sum(1 for axis in CITED_AXES if "verified" in values[axis][1])


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

    original_ideas = json.loads(IDEA_SET_PATH.read_text(encoding="utf-8"))
    ideas, cluster_report = dedup_ideas(original_ideas)
    print(f"Deduplicated {len(original_ideas)} -> {len(ideas)} ideas ({len(cluster_report)} clusters merged)")
    for c in cluster_report:
        print(f"  kept [{c['canonical_keyword']}], absorbed {[a['keyword'] for a in c['absorbed']]}")

    cluster_path = BASE_DIR / "results" / "dedup_clusters_v3.json"
    cluster_path.write_text(json.dumps(cluster_report, indent=2), encoding="utf-8")

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
            user_message=ideas_payload, max_tokens=16000,
            validate_fn=lambda d: validate_scores(d, len(ideas)),
        )
        by_index = {s["idea_index"]: s for s in result["scores"]}
        all_runs.append(by_index)
        tiers = [tier(final_score(by_index[i], qe_knowledge_text)) for i in range(len(ideas))]
        forced = sum(
            1 for i in range(len(ideas)) for axis in CITED_AXES
            if "forced" in effective_axis_values(by_index[i], qe_knowledge_text)[axis][1]
        )
        print(f"  tiers: test_it={tiers.count('test_it')} maybe={tiers.count('maybe')} nope={tiers.count('nope')}")
        print(f"  {forced}/{len(ideas) * len(CITED_AXES)} cited-axis scores forced to 5")

    out_path = BASE_DIR / "results" / "consistency_runs_v3.json"
    out_path.write_text(json.dumps(all_runs, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_runs)} runs to {out_path}")

    summary = []
    for i, idea in enumerate(ideas):
        final_scores = [final_score(run[i], qe_knowledge_text) for run in all_runs]
        tiers_per_run = [tier(s) for s in final_scores]
        axis_stats = {}
        for axis in ALL_AXES:
            eff_values = [effective_axis_values(run[i], qe_knowledge_text)[axis][0] for run in all_runs]
            axis_stats[axis] = {"mean": round(statistics.mean(eff_values), 2), "stdev": round(statistics.pstdev(eff_values), 2)}
        testable_votes = [run[i]["testable_now"] for run in all_runs]
        citations_verified = [citations_verified_count(run[i], qe_knowledge_text) for run in all_runs]
        summary.append({
            "idea_index": i, "keyword": idea["keyword"], "claim": idea["claim"],
            "merged_from": idea.get("merged_from", []),
            "final_score_mean": round(statistics.mean(final_scores), 1),
            "final_score_stdev": round(statistics.pstdev(final_scores), 1),
            "final_score_range": [min(final_scores), max(final_scores)],
            "tiers_seen": sorted(set(tiers_per_run)),
            "tier_flipped": len(set(tiers_per_run)) > 1,
            "testable_now_agreement": f"{sum(testable_votes)}/{len(testable_votes)}",
            "citations_verified_agreement": f"{round(statistics.mean(citations_verified), 1)}/2",
            "axis_stats": axis_stats,
        })

    summary_path = BASE_DIR / "results" / "consistency_summary_v3.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote per-idea variance summary to {summary_path}")

    flipped = [s for s in summary if s["tier_flipped"]]
    avg_sd = statistics.mean(s["final_score_stdev"] for s in summary)
    print(f"\n{len(flipped)}/{len(ideas)} ideas flipped tier across {N_REPEATS} runs (v3). Avg stdev: {avg_sd:.2f}")


if __name__ == "__main__":
    main()
