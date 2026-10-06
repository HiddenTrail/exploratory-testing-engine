"""Layer 4: Oracle-creation job.

Reads the three upstream layers -
  1. heuristics/             - the heuristic library: every generic heuristic,
                               tagged by surface, feature and quality (issue #128)
  2. adapters/<sut>/oracle_library.json - per-SUT domain-grounded claims
  3. context_<sut>.json      - test results / jira / risk assessments
- and produces one ranked list of test ideas: domain-grounded claims first
(scored up/down by what context says about them), generic heuristic probes
after (always available as a lower-priority fallback set). The library is far
bigger than any prompt should carry, so only the heuristics that fit the SUT's
surface are kept, those matching its features rank higher, and the caller can
cap how many it takes.

This is intentionally flat-file and dependency-free (no DB, no service) -
Phase 0 is about proving the ranking loop works, not about infrastructure.
Run: python -m engine.ontology.oracle_creator --sut token_purchase
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ONTOLOGY_DIR = Path(__file__).parent
ADAPTERS_DIR = ONTOLOGY_DIR.parent / "adapters"
HEURISTICS_DIR = ONTOLOGY_DIR / "heuristics"

# Score deltas applied to a grounded claim's base score depending on what
# context (yesterday's results + jira) says about it.
UNTESTED_BONUS = 1.0
CONFIRMED_STALE_PENALTY = -2.0
REFUTED_BONUS = 4.0
JIRA_MATCH_BONUS = 3.0
GROUNDED_BASE_SCORE = 5.0
# A heuristic tagged with one of the SUT's features. Base weights are 1 to 3, so
# even with this a heuristic stays below every grounded claim.
FEATURE_MATCH_BONUS = 1.0
# An idea about a screen the engine knows how to reach (#311) is worth more than one about
# a place it may not get to: the oracle's top ideas were about screens no test reached.
REACHABLE_BONUS = 1.5
# A heuristic written for the SUT's surface (tagged "gui" for a GUI SUT) beats an
# equally weighted one that fits any surface. Without it a GUI run's top slice was
# all field-level checks, and ones like overlay_blocking never made the cut.
SURFACE_MATCH_BONUS = 0.5


def load_vocabulary() -> dict[str, Any]:
    return json.loads((HEURISTICS_DIR / "vocabulary.json").read_text(encoding="utf-8"))


def load_heuristics() -> list[dict[str, Any]]:
    """Every heuristic in the library, in file order, each with the source of the
    file it came from. One file per source (HTSM, Hendrickson, WCAG, ...)."""
    heuristics = []
    for path in sorted(HEURISTICS_DIR.glob("*.json")):
        if path.name == "vocabulary.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        heuristics.extend({**h, "source": data["source"]} for h in data["heuristics"])
    return heuristics


def select_heuristics(heuristics: list[dict[str, Any]], surfaces=None, features=(),
                      limit: int | None = None) -> list[tuple[dict[str, Any], float]]:
    """The heuristics that fit a SUT, best first, as (heuristic, score) pairs.

    surfaces: e.g. ("gui",). A heuristic with no surface tag fits every surface;
    None keeps them all; one tagged with a given surface gets SURFACE_MATCH_BONUS.
    features: e.g. ("login", "search"); a heuristic tagged with one of them gets
    FEATURE_MATCH_BONUS. Ties keep the library's order."""
    surface_tags = set(load_vocabulary()["tags"]["surface"])
    features = set(features)
    fitting = []
    for h in heuristics:
        own_surfaces = surface_tags & set(h["tags"])
        if surfaces is not None and own_surfaces and not own_surfaces & set(surfaces):
            continue
        score = float(h["base_weight"])
        if surfaces is not None and own_surfaces & set(surfaces):
            score += SURFACE_MATCH_BONUS
        if features & set(h["tags"]):
            score += FEATURE_MATCH_BONUS
        fitting.append((h, score))
    fitting.sort(key=lambda pair: pair[1], reverse=True)
    return fitting[:limit] if limit is not None else fitting


def load_domain_claims(sut: str) -> list[dict[str, Any]]:
    """Flattens adapters/<sut>/oracle_library.json's {category: {vectors: [...]}}
    shape into one list of {id, category, claim, rationale} dicts. id is a
    stable, deterministic slug (category + position within it) - not the
    claim text itself - so it survives the Driver paraphrasing the claim in
    its own words when it cites one (see score_grounded_claim)."""
    path = ADAPTERS_DIR / sut / "oracle_library.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    claims = []
    for category, body in data.get("modeled", {}).items():
        if not body.get("applies", True):
            continue
        for index, vector in enumerate(body.get("vectors", []), start=1):
            claims.append({
                "id": f"claim:{category}:{index:02d}",
                "category": category,
                "claim": vector["claim"],
                "rationale": vector.get("rationale", ""),
            })
    return claims


def context_path(key: str) -> Path:
    """Where a SUT's or product's context file lives: next to this module, or in
    ENGINE_CONTEXT_DIR when that's set, so a benchmark can learn into a scratch folder
    instead of changing a committed context file."""
    folder = os.environ.get("ENGINE_CONTEXT_DIR", "").strip()
    return (Path(folder) if folder else ONTOLOGY_DIR) / f"context_{key}.json"


def load_context(sut: str) -> dict[str, Any]:
    path = context_path(sut)
    if not path.exists():
        return {"test_results": [], "jira_entries": [], "risk_assessments": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _find_result(claim_id: str, test_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for result in test_results:
        if result.get("claim_id") == claim_id:
            return result
    return None


def _jira_mentions(claim: str, jira_entries: list[dict[str, Any]]) -> bool:
    claim_lower = claim.lower()
    for entry in jira_entries:
        summary = f"{entry.get('title', '')} {entry.get('description', '')}".lower()
        if any(word in summary for word in claim_lower.split() if len(word) > 4):
            return True
    return False


def score_grounded_claim(claim: dict[str, Any], context: dict[str, Any]) -> tuple[float, str]:
    """Returns (score, status) for one domain-grounded claim."""
    delta, status = _context_delta(claim["id"], context)
    score = GROUNDED_BASE_SCORE + delta

    if _jira_mentions(claim["claim"], context.get("jira_entries", [])):
        score += JIRA_MATCH_BONUS
        status = f"{status}+jira"

    return score, status


def _context_delta(idea_id: str, context: dict[str, Any]) -> tuple[float, str]:
    """What context (earlier results) adds to an idea's score, and its status."""
    result = _find_result(idea_id, context.get("test_results", []))
    if result is None:
        return UNTESTED_BONUS, "untested"
    if result.get("verified") is False:
        return REFUTED_BONUS, "refuted"
    return CONFIRMED_STALE_PENALTY, "confirmed"


# With a run focus, at most this share of the Driver's slots goes to ideas with a focus tag.
FOCUS_SHARE = 1 / 3


def build_product_ideas(product: str, limit: int | None = None, focus: tuple = ()) -> dict[str, Any]:
    """A product's oracle, built by engine/ontology/seeder.py from the heuristic
    library and the product's wiki, scored with its context (context_<product>.json)
    and ranked. With a limit, the pick takes turns across seeds (pick_across_seeds).

    focus: library tags this run looks at first, e.g. ("security",) (#278). Ideas from
    heuristics with a focus tag get up to FOCUS_SHARE of the limit, best first, and the
    rest still take turns across seeds, so a focused run stays a rounded one. Without
    it, the Standards seed's two or so slots went to accessibility, and no security
    heuristic reached the Driver."""
    from engine.ontology.seeder import build_oracle, pick_across_seeds  # it imports this module

    from engine.ontology.product import context_screens
    context = load_context(product)
    tags_of = {h["id"]: set(h["tags"]) for h in load_heuristics()}
    route_of = {s["slug"]: s["route"] for s in context_screens(product) if s.get("route")}
    ideas = []
    for e in build_oracle(product)["expectations"]:
        delta, status = _context_delta(e["id"], context)
        heuristic = next((s.split(":", 1)[1] for s in e["sources"] if s.startswith("heuristic:")), None)
        focused = sorted(set(focus) & tags_of.get(heuristic, set()))
        where = route_of.get(e["entity"], "")
        ideas.append({
            "id": e["id"], "tier": e["tier"], "score": e["score"] + delta + (REACHABLE_BONUS if where else 0.0),
            "status": status, "category": e["seed"], "entity": e["entity"], "claim": e["claim"],
            # Where to start testing it (#311): the screen's route, from Spoor's map.
            **({"where": where} if where else {}),
            # The expectation's sources stay in the built oracle; the Driver doesn't need them.
            "rationale": f"{e['seed_name']}. Check: {e['check']}"
                         + (f" (this run's focus: {', '.join(focused)})" if focused else ""),
            "source": "seeded_oracle",
            **({"focus": focused} if focused else {}),
        })
    if limit is None:
        ideas = sorted(ideas, key=lambda i: i["score"], reverse=True)
    elif focus:
        in_focus = sorted((i for i in ideas if i.get("focus")), key=lambda i: i["score"], reverse=True)
        first = in_focus[:int(limit * FOCUS_SHARE)]
        chosen = {i["id"] for i in first}
        rest = pick_across_seeds([i for i in ideas if i["id"] not in chosen], limit - len(first))
        ideas = sorted(first + rest, key=lambda i: i["score"], reverse=True)
    else:
        ideas = pick_across_seeds(ideas, limit)
    for rank, idea in enumerate(ideas, start=1):
        idea["rank"] = rank
    return {"sut": product, "generated_at": datetime.now(timezone.utc).isoformat(), "ranked_ideas": ideas}


def build_ranked_ideas(sut: str, surfaces=None, features=(), heuristic_limit: int | None = None) -> dict[str, Any]:
    """surfaces, features and heuristic_limit pick the heuristics (see
    select_heuristics). Domain claims are never filtered. A product with a wiki
    gets build_product_ideas instead."""
    heuristics = select_heuristics(load_heuristics(), surfaces, features, heuristic_limit)
    domain_claims = load_domain_claims(sut)
    context = load_context(sut)

    ideas: list[dict[str, Any]] = []

    for claim in domain_claims:
        score, status = score_grounded_claim(claim, context)
        ideas.append({
            "id": claim["id"],
            "tier": "grounded",
            "score": score,
            "status": status,
            "category": claim["category"],
            "claim": claim["claim"],
            "rationale": claim["rationale"],
            "source": "domain_oracle",
        })

    for heuristic, score in heuristics:
        ideas.append({
            "id": f"heuristic:{heuristic['id']}",
            "tier": "generic",
            "score": score,
            "status": "n/a",
            "category": heuristic["kind"],
            "claim": heuristic["description"],
            "rationale": f"Heuristic: {heuristic['name']}. Try: {heuristic['apply']}",
            "source": "heuristic_library",
        })

    ideas.sort(key=lambda idea: idea["score"], reverse=True)
    for rank, idea in enumerate(ideas, start=1):
        idea["rank"] = rank

    return {
        "sut": sut,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranked_ideas": ideas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Layer 4: build a ranked oracle test-idea list.")
    parser.add_argument("--sut", required=True, help="SUT name, e.g. token_purchase")
    parser.add_argument("--out", default=None, help="Output path (default: runs/ontology/<sut>/oracle_ranked.json)")
    args = parser.parse_args()

    ranked = build_ranked_ideas(args.sut)

    out_path = Path(args.out) if args.out else Path("runs/ontology") / args.sut / "oracle_ranked.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ranked, indent=2), encoding="utf-8")
    print(f"Wrote {len(ranked['ranked_ideas'])} ranked ideas to {out_path}")


if __name__ == "__main__":
    main()
