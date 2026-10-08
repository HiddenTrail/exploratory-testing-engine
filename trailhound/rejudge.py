"""Re-judge a saved run: the same tests, only the judging calls again, several times (#370).

A change to the hypothesis, the Skeptic or the debrief is hard to measure with whole runs:
the tests differ from run to run, and that swamps the change (runs with the same code
found 0 to 3 known problems, #369). Re-judging keeps the saved run's tests and results
and runs only the judging again, through the loop's own code, so what's left is the
judging's own randomness:

    python -m trailhound.rejudge runs/<run> --adapter web_gui --times 3 --out runs/<experiment>/<arm>

Nothing touches the system under test. A lean run is re-judged lean, with the same parts
switched on; --with switches more on. All repetitions share one spending limit
(TRAILHOUND_MAX_COST_USD), and each is written to <out>/r<N> in the run's own shape, so
the report and run_summary read it as they are. At the end it prints one row per
repetition, next to the saved run's own row.

Accepted limits: a repetition starts with no "objections from earlier runs" history,
whatever the saved run had, so both arms of an experiment start the same. Bug replays,
videos and bug reports need the live system and are left out. A run saved before #177
has no cast tests to replay and is refused.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from trailhound import budget
from trailhound.adapters.registry import available_adapters, load_adapter
from trailhound.ask import saved_adapter
from trailhound.config import RunConfig
from trailhound.lean import PARTS as LEAN_PARTS
from trailhound.run_summary import estimated_cost
from trailhound.runner import run
from trailhound.tools import summary_verdict_errors

# What the loop adds to each casting-log entry around the adapter's result, and what the
# runner adds after the loop: "video" goes only on the tests the run cited, so handing it
# back would tell the judging which tests the saved judging relied on (found in review).
_LOOP_KEYS = ("checkpoint", "round", "round_reasoning", "linked_hypothesis", "oracle_claim_id", "follows_up",
              "rules_out_if", "cast_test", "video")


def saved_replay(output: dict, source: str) -> dict:
    """What runner.run needs to re-judge `output`: each checkpoint's round (reasoning,
    tests as cast, dropped tests), the saved results by test number, the happy-day
    example and the test numbers in order."""
    log = output.get("casting_log") or []
    if any("cast_test" not in e for e in log):
        raise SystemExit(f"{source} was saved before cast tests were kept (#177), so its tests can't be replayed.")
    rounds = {cp["checkpoint"]: {"reasoning": "", "tests": [], "dropped_tests": list(cp.get("dropped_tests") or [])}
              for cp in output.get("checkpoints") or []}
    results = {}
    for e in log:
        saved = rounds.setdefault(e["checkpoint"], {"reasoning": "", "tests": [], "dropped_tests": []})
        saved["reasoning"] = e.get("round_reasoning", "")
        saved["tests"].append(e["cast_test"])
        results[e["test_number"]] = {k: v for k, v in e.items() if k not in _LOOP_KEYS}
    return {"rounds": rounds, "results": results, "test_numbers": [e["test_number"] for e in log],
            "happy_day_example": output.get("happy_day_example") or {}, "source": source}


def checkpoints_allowed(output: dict) -> int:
    """As many checkpoints as the saved run had, and one more if it stopped before its cap
    (the Skeptic was satisfied, or it broke): a re-judgement that goes on then stops as
    "replay_ended", not as if it had used up its checkpoints."""
    saved = len(output.get("checkpoints") or [])
    return saved if output.get("stopped_reason") == "checkpoints_exhausted" else saved + 1


def replaying_adapter(adapter, output: dict, replay: dict):
    """The adapter as the saved run saw it, handing back the saved result for each test."""
    results = replay["results"]
    return replace(saved_adapter(adapter, output), execute_test=lambda test, n: copy.deepcopy(results[n]))


def row(name: str, output: dict) -> str:
    """One line of the comparison table."""
    cps = output.get("checkpoints") or []
    gaps = [g for cp in cps for g in cp["skeptic_review"].get("gaps") or []]
    obs = output.get("observations") or []
    held = sum(1 for o in obs if o.get("status") == "corroborated")
    kinds: dict[str, int] = {}
    for g in gaps:
        kinds[g.get("kind", "?")] = kinds.get(g.get("kind", "?"), 0) + 1
    retries = sum(1 for u in output.get("usage_log") or [] if u.get("rejected"))
    return (f"| {name} | {output.get('stopped_reason', '?')} | {len(cps)} | {held} of {len(obs)} | "
            f"{sum(1 for cp in cps if summary_verdict_errors(cp['hypothesis']))} | "
            f"{len(gaps)} ({sum(1 for g in gaps if g.get('blocks_verdict'))}) | "
            f"{', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) or '-'} | {retries} | "
            f"${estimated_cost(output.get('usage_summary') or {}):.2f} |")


HEADER = ("| Run | Stopped | Checkpoints | Claims holding up | Summaries judging the product | Objections (blocking) | "
          "Objections by kind | Retries | Cost |\n|---|---|---|---|---|---|---|---|---|")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Re-judge a saved run several times: same tests, only the judging again.")
    ap.add_argument("run_dir", type=Path, help="the saved run's folder (with output.json)")
    ap.add_argument("--adapter", required=True, choices=available_adapters())
    ap.add_argument("--times", type=int, default=3, help="how many repetitions (default 3)")
    ap.add_argument("--out", type=Path, required=True, help="where to write r1, r2, ...")
    ap.add_argument("--model", default=None)
    ap.add_argument("--first-round-budget", type=int, default=None, dest="first_round_test_budget",
                    help="the saved run's first-round budget, for the records that use it (the adapter's default if left out)")
    ap.add_argument("--default-budget", type=int, default=None, dest="default_test_budget")
    ap.add_argument("--with", default="", dest="lean_with", metavar="PARTS",
                    help="For a lean run: parts to switch on as well, from: " + ", ".join(LEAN_PARTS))
    args = ap.parse_args(argv)
    if args.times < 1:
        ap.error("--times must be at least 1")
    output = json.loads((args.run_dir / "output.json").read_text(encoding="utf-8"))
    replay = saved_replay(output, str(args.run_dir))
    lean = "lean" in output
    lean_with = sorted(set((output.get("lean") or {}).get("with") or [])
                       | {p.strip() for p in args.lean_with.split(",") if p.strip()})
    if lean_with and not lean:
        ap.error("--with only means something for a lean run; this one wasn't lean")
    adapter = replaying_adapter(load_adapter(args.adapter), output, replay)
    limits = budget.start_run()      # one limit for every repetition together
    print(f"Spending limit for all {args.times} repetition(s): about ${limits.max_cost_usd:.2f} "
          f"or {limits.max_calls} model calls.")
    rows = [row("saved", output)]
    for n in range(1, args.times + 1):
        print(f"\n=== Re-judging {args.run_dir} ({n} of {args.times}) ===")
        run_config = RunConfig.for_adapter(adapter, model=args.model, max_checkpoints=checkpoints_allowed(output),
                                           first_round_test_budget=args.first_round_test_budget,
                                           default_test_budget=args.default_test_budget,
                                           out_dir=args.out / f"r{n}", lean=lean, lean_with=lean_with)
        result = run(adapter, run_config, replay=copy.deepcopy(replay))
        rows.append(row(f"r{n}", result))
        if result.get("stopped_reason") == "budget_exceeded":
            print("The spending limit was reached; stopping here.")
            break
    print("\n" + HEADER + "\n" + "\n".join(rows))
    print(f"\nFiles: {args.out.resolve()}, one folder per repetition (r1, r2, ...) with output.json and report.html")


if __name__ == "__main__":
    main()
