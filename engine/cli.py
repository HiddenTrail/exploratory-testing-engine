"""CLI entrypoint: python -m engine.cli --adapter <name> [options].

Generic infrastructure only - the Windows console UTF-8 workaround, argument
parsing, and wiring an adapter + RunConfig into engine.runner.run(). No
domain knowledge lives here.
"""

import argparse
import sys
from pathlib import Path

# Model-generated text (reasoning, probes) can contain non-ASCII characters that
# the default Windows console codec can't encode, crashing a plain print().
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine.adapters.registry import available_adapters, load_adapter
from engine.config import RunConfig
from engine.lean import PARTS as LEAN_PARTS
from engine.runner import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Trailhound against a SUT adapter.")
    parser.add_argument("--adapter", required=True, choices=available_adapters(), help="Which SUT adapter to run.")
    parser.add_argument("--model", default=None, help="Override the Anthropic model (default: engine default).")
    parser.add_argument("--max-checkpoints", type=int, default=None, dest="max_checkpoints")
    parser.add_argument("--first-round-budget", type=int, default=None, dest="first_round_test_budget")
    parser.add_argument("--default-budget", type=int, default=None, dest="default_test_budget")
    parser.add_argument("--out-dir", type=Path, default=None, help="Override the results directory (default: runs/<adapter>).")
    parser.add_argument("--lean", action="store_true",
                        help="A lean run for experiments (issue #295): the model writes only what decides a finding, "
                             "and the testing story, the debrief and bug report write-ups are skipped.")
    parser.add_argument("--with", default="", dest="lean_with", metavar="PARTS",
                        help="With --lean: parts to switch back on, comma-separated, from: " + ", ".join(LEAN_PARTS))
    parser.add_argument("--learn", nargs="?", const="", default=None, metavar="PRODUCT",
                        help="After the run, feed its results and discoveries into the context layer, so the next "
                             "run starts from them (issue #159). Give the product (e.g. juice-shop) when it has a wiki.")
    args = parser.parse_args()
    lean_with = [p.strip() for p in args.lean_with.split(",") if p.strip()]
    if lean_with and not args.lean:
        parser.error("--with only works with --lean")
    unknown = sorted(set(lean_with) - set(LEAN_PARTS))
    if unknown:
        parser.error(f"--with: unknown part(s) {', '.join(unknown)}; choose from {', '.join(LEAN_PARTS)}")

    adapter = load_adapter(args.adapter)
    # What the Skeptic objected to in earlier runs on this system (#258), from the same
    # context file --learn writes: the product's, or the adapter's own.
    from engine.ontology.feedback import driver_history
    from engine.ontology.oracle_creator import load_context
    history = driver_history(load_context(args.learn or adapter.name))
    if history:
        print("The Driver is told what the Skeptic objected to most before: "
              + ", ".join(h["kind"] for h in history["most_common"]))
    run_config = RunConfig.for_adapter(
        adapter,
        model=args.model,
        max_checkpoints=args.max_checkpoints,
        first_round_test_budget=args.first_round_test_budget,
        default_test_budget=args.default_test_budget,
        out_dir=args.out_dir,
        skeptic_history=history,
        lean=args.lean,
        lean_with=lean_with,
    )
    output = run(adapter, run_config)
    # A run that broke, or that the spending limit stopped, teaches nothing, and exits
    # non-zero so a script or a CI job sees it.
    stopped_badly = output.get("stopped_reason") in ("error", "budget_exceeded")
    # Never re-ranked mid-run; the next run rebuilds its oracle from what this one learned.
    if args.learn is not None and not stopped_badly:
        from engine.ontology.feedback import learn
        for line in learn(adapter.name, run_config.out_dir / "output.json", args.learn or None):
            print(line)
    if stopped_badly:
        sys.exit(2)


if __name__ == "__main__":
    main()
