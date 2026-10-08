"""Ask a saved run's casting round again, several times, without running its tests (#371).

A change to steering (blocking questions first #340, debrief promises #352, the follow-up
and free caps, the oracle ranking) acts on what the Driver casts. Measured through whole
runs, it drowns: after the first round every run goes its own way (#369). Asked again
from the same saved checkpoint, the round shows what the change does to it, at one call
a repetition:

    python -m trailhound.recast runs/<run> --adapter web_gui --checkpoint 2 --times 5 --out runs/<experiment>/<arm>

The call is rebuilt from the saved run the way the loop built it at the start of that
checkpoint: the test history, the previous review without parked claims, the debrief's
promises, the questions that come first, parked claims, run diagnostics and the oracle's
progress. Then the current code asks for the round N times. The loop's limits are applied
to each answer, and nothing is run. The repetitions share one spending limit, and after the
first they mostly read the cached prompt, so they're cheap.

Runs saved before #371 don't record their test budgets, model or the objections history
the Driver was given: --first-round-budget and --default-budget give the budgets, the
model is the default unless --model says otherwise, and the history is left out. The
round after a run's last checkpoint can be asked too (what would the Driver do after the
last debrief?), with no saved round to compare.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from trailhound import budget, diagnostics, steering
from trailhound.adapters.registry import available_adapters, load_adapter
from trailhound.ask import history_segments, saved_adapter
from trailhound.client import build_client, summarize_usage
from trailhound.config import RunConfig
from trailhound.loop import get_casting_round
from trailhound.run_summary import estimated_cost


def casting_call(output: dict, adapter, run_config: RunConfig, k: int) -> dict:
    """get_casting_round's arguments for checkpoint `k` of a saved run, as the loop had
    them, and what's needed to apply its limits to the answer."""
    checkpoints = (output.get("checkpoints") or [])[:k - 1]
    if len(checkpoints) < k - 1:
        raise SystemExit(f"The saved run has {len(output.get('checkpoints') or [])} checkpoint(s), so its "
                         f"checkpoint {k} can't be rebuilt.")
    # Without the "video" the runner adds to cited tests after the loop: the loop never sent
    # it, and it would tell the Driver which tests the run went on to rely on (as in #370).
    log = [{key: v for key, v in e.items() if key != "video"}
           for e in output.get("casting_log") or [] if e.get("checkpoint", 0) < k]
    parked = steering.parked_claims(checkpoints)
    parked_ids = steering.parked_ids(checkpoints, parked)
    first = k == 1
    prior = None if first else {"hypothesis": checkpoints[-1]["hypothesis"],
                                "skeptic_review": steering.without_parked(checkpoints[-1]["skeptic_review"], parked_ids)}
    ranked = list((adapter.onboarding_extra or {}).get("oracle_ranked") or [])
    idea_ids = frozenset(i.get("id") for i in ranked if i.get("id"))
    blocking = () if first else steering.blocking_ids(prior)
    promises = [] if first else steering.promises(prior, checkpoints[-1].get("debrief"))
    blocking += tuple(p["id"] for p in promises if p["id"] not in blocking)
    earlier = [o for cp in checkpoints for o in cp["hypothesis"].get("observations") or []]
    test_budget = run_config.first_round_test_budget if first else run_config.default_test_budget
    return {
        "args": (adapter, run_config, output.get("happy_day_example") or {}, history_segments(adapter, log), prior),
        "kwargs": {
            "test_budget": test_budget, "is_first_round": first,
            "run_diagnostics": None if first else diagnostics.for_model(diagnostics.diagnose(log)),
            "follow_up_ids": frozenset({o["id"] for o in earlier}
                                       | {g["id"] for cp in checkpoints for g in cp["skeptic_review"]["gaps"]}),
            "parked": steering.for_driver(checkpoints, parked), "idea_ids": idea_ids,
            "oracle_progress": steering.oracle_progress(ranked, log, checkpoints) if ranked else None,
            "blocking": blocking, "promises": promises,
        },
        "limits": {"test_budget": test_budget, "parked_ids": parked_ids, "idea_ids": idea_ids, "blocking": blocking,
                   "promised": tuple(p["id"] for p in promises)},
    }


def measure(answer: dict, limits: dict) -> dict:
    """What one casting round does, after the loop's limits (steering.limit), as counts."""
    budget_, blocking = limits["test_budget"], limits["blocking"]
    tests = answer.get("candidate_tests") or []
    salvaged = answer.get("dropped_tests") or []          # what the last-attempt salvage took out (#288)
    to_run, over = steering.limit(tests, steering.follow_up_cap(budget_), limits["parked_ids"],
                                  steering.free_cap(budget_) if limits["idea_ids"] else None, blocking,
                                  steering.blocking_needed(blocking, budget_))
    answered = steering.blocking_answered(to_run, blocking)
    ideas = [t.get("oracle_claim_id") for t in to_run if t.get("oracle_claim_id")]
    return {
        "gave_up": bool(answer.get("give_up")), "cast": len(tests) + len(salvaged), "to_run": len(to_run),
        "dropped": len(salvaged) + len(over),
        "follow_ups": sum(1 for t in to_run if t.get("follows_up")),
        "first_needed": steering.blocking_needed(blocking, budget_),
        "first_answered": len(answered),
        "promises_answered": sum(1 for p in limits["promised"] if p in answered),
        "promises": len(limits["promised"]),
        "oracle_tests": len(ideas), "oracle_ideas": len(set(ideas)),
        "free": sum(1 for t in to_run if not t.get("follows_up") and not t.get("oracle_claim_id")),
        # Where a test starts is the adapter's business; one without a start field shows "-".
        "starts": (len({str(t.get("start") or t.get("state_id") or t.get("state")) for t in to_run})
                   if any(t.get("start") or t.get("state_id") or t.get("state") for t in to_run) else "-"),
    }


def saved_round(output: dict, k: int, limits: dict) -> dict:
    """The saved run's own round k, counted the same way: the tests it ran, and its drops.
    None for the round after the run's last checkpoint, which it never cast."""
    cp = next((c for c in output.get("checkpoints") or [] if c.get("checkpoint") == k), None)
    if cp is None:
        return None
    ran = [e["cast_test"] for e in output.get("casting_log") or [] if e.get("checkpoint") == k and "cast_test" in e]
    counts = measure({"candidate_tests": ran}, limits)
    counts.update(cast=len(ran) + len(cp.get("dropped_tests") or []), dropped=len(cp.get("dropped_tests") or []))
    return counts


HEADER = ("| Round | Tests cast | Run | Dropped | Follow-ups | First: answered / needed | Promises answered | "
          "Oracle tests (ideas) | Free | Start points | Retries | Cost |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def row(name: str, m: dict | None, retries="", cost="") -> str:
    if m is None:
        return f"| {name} | never cast: the run ended before this round |" + " |" * 10
    return (f"| {name} | {m['cast']} | {m['to_run']} | {m['dropped']} | {m['follow_ups']} | "
            f"{m['first_answered']} / {m['first_needed']} | {m['promises_answered']} / {m['promises']} | "
            f"{m['oracle_tests']} ({m['oracle_ideas']}) | {m['free']} | {m['starts']} | {retries} | {cost} |")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Ask a saved run's casting round again, several times, without running it.")
    ap.add_argument("run_dir", type=Path, help="the saved run's folder (with output.json)")
    ap.add_argument("--adapter", required=True, choices=available_adapters())
    ap.add_argument("--checkpoint", type=int, required=True, help="which checkpoint's round, from 1")
    ap.add_argument("--times", type=int, default=5, help="how many repetitions (default 5)")
    ap.add_argument("--out", type=Path, required=True, help="where to write rounds.json")
    ap.add_argument("--model", default=None)
    ap.add_argument("--first-round-budget", type=int, default=None, dest="first_round_test_budget",
                    help="for a run saved before #371, which doesn't record it")
    ap.add_argument("--default-budget", type=int, default=None, dest="default_test_budget")
    args = ap.parse_args(argv)
    if args.times < 1 or args.checkpoint < 1:
        ap.error("--times and --checkpoint must be at least 1")
    output = json.loads((args.run_dir / "output.json").read_text(encoding="utf-8"))
    saved = output.get("settings") or {}
    if not saved and (args.first_round_test_budget is None or args.default_test_budget is None):
        ap.error("this run was saved before #371 and doesn't record its test budgets: give --first-round-budget "
                 "and --default-budget (the benchmark settings are 10 and 6)")
    adapter = saved_adapter(load_adapter(args.adapter), output)
    run_config = RunConfig.for_adapter(
        adapter, model=args.model or saved.get("model"),
        first_round_test_budget=args.first_round_test_budget or saved.get("first_round_test_budget"),
        default_test_budget=args.default_test_budget or saved.get("default_test_budget"),
        skeptic_history=saved.get("skeptic_history"), lean="lean" in output,
        lean_with=(output.get("lean") or {}).get("with") or ())
    call = casting_call(output, adapter, run_config, args.checkpoint)
    limits = budget.start_run()
    print(f"Spending limit for all {args.times} repetition(s): about ${limits.max_cost_usd:.2f} "
          f"or {limits.max_calls} model calls.")
    client = build_client()
    rows, rounds = [row("saved", saved_round(output, args.checkpoint, call["limits"]))], []
    for n in range(1, args.times + 1):
        print(f"\n=== Casting checkpoint {args.checkpoint} of {args.run_dir} again ({n} of {args.times}) ===")
        usage: list[dict] = []
        try:
            answer = get_casting_round(client, *call["args"], usage_sink=usage, **call["kwargs"])
        except budget.BudgetExceeded as e:
            print(e)
            break
        except RuntimeError as e:
            print(f"  this repetition failed: {e}")
            answer = {"failed": str(e), "candidate_tests": []}
        counts = measure(answer, call["limits"])
        rounds.append({"repetition": n, "answer": answer, "counts": counts, "usage": usage})
        rows.append(row(f"r{n}", counts, sum(1 for u in usage if u.get("rejected")),
                        f"${estimated_cost(summarize_usage(usage)):.3f}"))
        # After every repetition, so what was paid for is kept if a later one breaks.
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "rounds.json").write_text(json.dumps({"source": str(args.run_dir), "checkpoint": args.checkpoint,
                                                          "rounds": rounds}, indent=2), encoding="utf-8")
    print("\n" + HEADER + "\n" + "\n".join(rows))
    print(f"\nFiles: {(args.out / 'rounds.json').resolve()}")


if __name__ == "__main__":
    main()
