"""Closes the loop: reads a Driver run's output.json (casting_log) and writes
each executed test's oracle_claim_id + prediction_matched into layer 3's
context_<sut>.json as a test_result, keyed by claim id. Existing entries for
the same claim are overwritten (latest run wins) rather than duplicated.
An id that isn't one of the SUT's ranked ideas is dropped and reported: the
Driver makes ids up, for example from gap ids, when it has no oracle to cite
(issue #107).

Run: python -m engine.ontology.feedback --sut token_purchase --run runs/ontology_phase0_driver/output.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from engine.ontology.oracle_creator import ONTOLOGY_DIR, build_product_ideas, build_ranked_ideas, load_context


def known_ids(sut: str, product: str | None = None) -> set[str]:
    """The ids a test can really cite: the SUT's ranked ideas (domain claims and
    generic heuristics), or a product's whole seeded oracle."""
    ideas = build_product_ideas(product) if product else build_ranked_ideas(sut)
    return {idea["id"] for idea in ideas["ranked_ideas"]}


def extract_results(output: dict, known: set[str]) -> tuple[list[dict], list[str]]:
    """Only tests the Driver explicitly tied to a ranked oracle idea
    (oracle_claim_id set) are feedback-worthy - linked_hypothesis alone is
    free text the Driver writes itself and can't be matched back to an
    oracle claim reliably (see docs/ontology-todo.md's former "known gap").
    Returns the results and the cited ids that aren't in `known`, which are
    left out rather than recorded against a claim that doesn't exist."""
    results, dropped = [], []
    for entry in output.get("casting_log", []):
        claim_id = entry.get("oracle_claim_id")
        if not claim_id:
            continue
        if claim_id not in known:
            dropped.append(claim_id)
            continue
        results.append({
            "claim_id": claim_id,
            "verified": entry.get("prediction_matched"),
            "timestamp": date.today().isoformat(),
        })
    return results, dropped


def extract_discoveries(output: dict) -> list[dict]:
    """The screens a run reached that its map doesn't have (issue #157), one record per
    test that reached one, from the full results in output.json."""
    found = []
    for entry in output.get("casting_log", []):
        record = (entry.get("result") or {}).get("discovered")
        if record:
            found.append({**record, "test_number": entry.get("test_number")})
    return found


def merge_discoveries(context: dict, found: list[dict], run: str) -> dict:
    """Add a run's discoveries to the context, by screen. Each keeps where it was first
    reached from (its path), its latest controls, how many times and in how many runs it
    was reached, and a status: 'seen once' until it's reached again, then 'reproduced'
    (the bar #148 sets for trusting anything once)."""
    by_id = {d["id"]: d for d in context.get("discoveries", [])}
    for record in found:
        known = by_id.get(record["id"])
        if known is None:
            known = by_id[record["id"]] = {
                "id": record["id"], "signature": record["signature"], "url": record["url"],
                "title": record["title"], "path": record["path"], "from_state": record["from_state"],
                "via": record["via"], "first_seen": run, "runs": [], "times_reached": 0,
            }
        known["times_reached"] += 1
        if run not in known["runs"]:
            known["runs"].append(run)
        known["last_seen"] = run
        known["elements"] = record["elements"]
        known["controls_offered"] = record["controls_offered"]
        known["status"] = "reproduced" if known["times_reached"] >= 2 else "seen once"
    context["discoveries"] = list(by_id.values())
    return context


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
    parser.add_argument("--product", default=None,
                        help="for a product with a wiki (e.g. juice-shop): its context file is keyed by product")
    args = parser.parse_args()

    output = json.loads(Path(args.run).read_text(encoding="utf-8"))
    new_results, dropped = extract_results(output, known_ids(args.sut, args.product))

    key = args.product or args.sut
    context = load_context(key)
    context = merge_results(context, new_results)
    found = extract_discoveries(output)
    if found:
        context = merge_discoveries(context, found, run=output.get("run_id") or Path(args.run).parent.name)

    context_path = ONTOLOGY_DIR / f"context_{key}.json"
    context_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    print(f"Merged {len(new_results)} test result(s) into {context_path} (total now {len(context['test_results'])})")
    if found:
        reproduced = sum(1 for d in context["discoveries"] if d["status"] == "reproduced")
        print(f"Recorded {len(found)} reach(es) of {len({d['id'] for d in found})} screen(s) beyond the map "
              f"({len(context['discoveries'])} known, {reproduced} reproduced)")
    if dropped:
        print(f"Dropped {len(dropped)} made-up id(s) that aren't ranked ideas for {args.sut}: {', '.join(sorted(set(dropped)))}")


if __name__ == "__main__":
    main()
