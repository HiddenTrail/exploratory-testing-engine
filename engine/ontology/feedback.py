"""Closes the loop: reads a Driver run's output.json (casting_log) and writes
each executed test's oracle_claim_id + prediction_matched into layer 3's
context_<sut>.json as a test_result, keyed by claim id. Existing entries for
the same claim are overwritten (latest run wins) rather than duplicated.

Run: python -m engine.ontology.feedback --sut token_purchase --run runs/ontology_phase0_driver/output.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from engine.ontology.oracle_creator import ONTOLOGY_DIR, load_context


def extract_results(output: dict) -> list[dict]:
    """Only tests the Driver explicitly tied to a ranked oracle idea
    (oracle_claim_id set) are feedback-worthy - linked_hypothesis alone is
    free text the Driver writes itself and can't be matched back to an
    oracle claim reliably (see docs/ontology-todo.md's former "known gap")."""
    results = []
    for entry in output.get("casting_log", []):
        claim_id = entry.get("oracle_claim_id")
        if not claim_id:
            continue
        results.append({
            "claim_id": claim_id,
            "verified": entry.get("prediction_matched"),
            "timestamp": date.today().isoformat(),
        })
    return results


def merge_results(context: dict, new_results: list[dict]) -> dict:
    by_claim_id = {r["claim_id"]: r for r in context.get("test_results", [])}
    for result in new_results:
        by_claim_id[result["claim_id"]] = result
    context["test_results"] = list(by_claim_id.values())
    return context


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed a Driver run's results back into layer 3 (context).")
    parser.add_argument("--sut", required=True)
    parser.add_argument("--run", required=True, help="Path to the run's output.json")
    args = parser.parse_args()

    output = json.loads(Path(args.run).read_text(encoding="utf-8"))
    new_results = extract_results(output)

    context = load_context(args.sut)
    context = merge_results(context, new_results)

    context_path = ONTOLOGY_DIR / f"context_{args.sut}.json"
    context_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    print(f"Merged {len(new_results)} test result(s) into {context_path} (total now {len(context['test_results'])})")


if __name__ == "__main__":
    main()
