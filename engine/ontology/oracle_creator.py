"""Layer 4: Oracle-creation job.

Reads the three upstream layers -
  1. heuristics.json         - generic, domain-agnostic heuristic vocabulary
  2. adapters/<sut>/oracle_library.json - per-SUT domain-grounded claims
  3. context_<sut>.json      - test results / jira / risk assessments
- and produces one ranked list of test ideas: domain-grounded claims first
(scored up/down by what context says about them), generic heuristic probes
after (always available as a lower-priority fallback set).

This is intentionally flat-file and dependency-free (no DB, no service) -
Phase 0 is about proving the ranking loop works, not about infrastructure.
Run: python -m engine.ontology.oracle_creator --sut token_purchase
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ONTOLOGY_DIR = Path(__file__).parent
ADAPTERS_DIR = ONTOLOGY_DIR.parent / "adapters"

# Score deltas applied to a grounded claim's base score depending on what
# context (yesterday's results + jira) says about it.
UNTESTED_BONUS = 1.0
CONFIRMED_STALE_PENALTY = -2.0
REFUTED_BONUS = 4.0
JIRA_MATCH_BONUS = 3.0
GROUNDED_BASE_SCORE = 5.0


def load_heuristics() -> list[dict[str, Any]]:
    data = json.loads((ONTOLOGY_DIR / "heuristics.json").read_text(encoding="utf-8"))
    return data["heuristics"]


def load_domain_claims(sut: str) -> list[dict[str, Any]]:
    """Flattens adapters/<sut>/oracle_library.json's {category: {vectors: [...]}}
    shape into one list of {category, claim, rationale} dicts."""
    path = ADAPTERS_DIR / sut / "oracle_library.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    claims = []
    for category, body in data.get("modeled", {}).items():
        if not body.get("applies", True):
            continue
        for vector in body.get("vectors", []):
            claims.append({
                "category": category,
                "claim": vector["claim"],
                "rationale": vector.get("rationale", ""),
            })
    return claims


def load_context(sut: str) -> dict[str, Any]:
    path = ONTOLOGY_DIR / f"context_{sut}.json"
    if not path.exists():
        return {"test_results": [], "jira_entries": [], "risk_assessments": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _find_result(claim: str, test_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for result in test_results:
        if result.get("claim") == claim:
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
    score = GROUNDED_BASE_SCORE
    result = _find_result(claim["claim"], context.get("test_results", []))
    if result is None:
        score += UNTESTED_BONUS
        status = "untested"
    elif result.get("verified") is False:
        score += REFUTED_BONUS
        status = "refuted"
    else:
        score += CONFIRMED_STALE_PENALTY
        status = "confirmed"

    if _jira_mentions(claim["claim"], context.get("jira_entries", [])):
        score += JIRA_MATCH_BONUS
        status = f"{status}+jira"

    return score, status


def build_ranked_ideas(sut: str) -> dict[str, Any]:
    heuristics = load_heuristics()
    domain_claims = load_domain_claims(sut)
    context = load_context(sut)

    ideas: list[dict[str, Any]] = []

    for claim in domain_claims:
        score, status = score_grounded_claim(claim, context)
        ideas.append({
            "tier": "grounded",
            "score": score,
            "status": status,
            "category": claim["category"],
            "claim": claim["claim"],
            "rationale": claim["rationale"],
            "source": "domain_oracle",
        })

    for heuristic in heuristics:
        ideas.append({
            "tier": "generic",
            "score": float(heuristic["base_weight"]),
            "status": "n/a",
            "category": heuristic["category"],
            "claim": heuristic["description"],
            "rationale": f"Generic heuristic: {heuristic['id']}",
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
