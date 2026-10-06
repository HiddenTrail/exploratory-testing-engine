"""A run's outcome as a short Markdown summary, for a CI job's summary page (issue #255).

    python -m engine.run_summary runs/ci/output.json [--log runs/ci/run.log] >> "$GITHUB_STEP_SUMMARY"

Reads only the engine's own fields in output.json: the observations and their status,
the bug replays (#177), the stop reason and the token usage. The retries are counted
from the run's log, where call_tool_with_retry prints each one. No model call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine import budget, interplay


_KIND_ORDER = {"bug": 0, "anomaly": 1, "finding": 2}


def estimated_cost(usage_summary: dict) -> float:
    """An estimate only, at engine/budget.py's list prices. The real bill is in the
    provider's console; this is here so a run that suddenly costs three times as much
    stands out."""
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return budget.estimated_cost({k: sum(call.get(k, 0) for call in usage_summary.values()) for k in keys})


def count_retries(log_text: str) -> int:
    return log_text.count("produced malformed output") + log_text.count("produced no tool call")


def count_dropped_tests(output: dict) -> int:
    return sum(len(c.get("dropped_tests") or []) for c in output.get("checkpoints", []))


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def summarize(output: dict, log_text: str | None = None, bugs: list | None = None) -> str:
    observations = sorted(output.get("observations", []), key=lambda o: _KIND_ORDER.get(o.get("kind"), 9))
    counts = {k: sum(1 for o in observations if o.get("kind") == k) for k in ("bug", "anomaly", "finding")}
    lines = ["## Exploratory run", ""]
    if "lean" in output:
        kept = output["lean"].get("with") or []
        lines += ["**Lean run, for experiments** (#295): compare it only with lean runs"
                  + (f" with the same parts on ({', '.join(kept)})" if kept else "") + ".", ""]
    if output.get("stopped_reason") == "budget_exceeded":
        lines += [f"**The spending limit stopped the run:** {_cell(output.get('error', ''))}", ""]
    elif output.get("error"):
        lines += [f"**The run stopped with an error:** {_cell(output['error'])}", ""]
    lines.append(f"{counts['bug']} bug(s), {counts['anomaly']} anomaly(ies), {counts['finding']} finding(s) from "
                 f"{len(output.get('casting_log', []))} tests and {len(output.get('checkpoints', []))} checkpoint(s). "
                 f"Stopped: `{output.get('stopped_reason', '?')}`.")
    if bugs:
        lines.append(f"{len(bugs)} bug report(s) written to bugs.json.")
    lines.append("")
    areas = ((output.get("checkpoints") or [{}])[-1].get("hypothesis") or {}).get("areas") or []
    if areas:
        lines += ["**Where it stands** (the Driver's last testing story):", "",
                  "| Area | Coverage | Seen so far | Confidence | Not tested |", "|---|---|---|---|---|"]
        lines += [f"| {_cell(a['area'])} | {_cell((a.get('coverage') or a.get('tested', '')).replace('_', ' '))}"
                  f"{' of ' + _cell(a['coverage_of']) if a.get('coverage_of') else ''} | "
                  f"{a['quality'].replace('_', ' ')} | {a['confidence']} | {_cell(a.get('not_tested', ''))} |"
                  for a in areas]
        obstacles = (output["checkpoints"][-1].get("hypothesis") or {}).get("obstacles") or []
        if obstacles:
            lines += ["", "What got in the way: " + "; ".join(_cell(o["obstacle"]) for o in obstacles)]
        lines.append("")
    if observations:
        lines += ["| Id | Kind | Status | Severity | Replay | Claim |", "|---|---|---|---|---|---|"]
        for o in observations:
            kind = o.get("kind", "")
            if o.get("driver_kind") and o["driver_kind"] != kind:
                kind += f" (Driver said {o['driver_kind']})"
            lines.append(f"| {o.get('id', '')} | {kind} | {o.get('status', '')} | {o.get('severity', '')} | "
                         f"{o.get('replay', '')} | {_cell(o.get('claim', ''))} |")
        lines.append("")
    if output.get("score"):
        s = output["score"]
        lines += [f"**Known problems found: {len(s['found'])} of {s['known']}** ({s.get('target', '')}, list "
                  f"{s.get('review') or 'unreviewed'}): found {', '.join(f['id'] for f in s['found']) or 'none'}; "
                  f"seen by a test but not reported {', '.join(x['id'] for x in s['seen_not_reported']) or 'none'}; "
                  f"missed {', '.join(m['id'] for m in s['missed']) or 'none'}.", ""]
    measured = interplay.measure(output.get("checkpoints") or [])
    if measured:
        lines += ["**The Driver and the Skeptic:** " + " ".join(interplay.summary_lines(measured)), ""]
    usage = output.get("usage_summary") or {}
    if usage:
        calls = sum(c.get("calls", 0) for c in usage.values())
        retries = f", {count_retries(log_text)} retried" if log_text is not None else ""
        dropped = count_dropped_tests(output)
        retries += f", {dropped} cast test(s) dropped as unusable" if dropped else ""
        lines.append(f"{calls} model call(s){retries}. Estimated cost about ${estimated_cost(usage):.2f} "
                     f"(list prices for a Sonnet-class model; the provider's console has the real bill).")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Summarize a run's output.json as Markdown.")
    ap.add_argument("output", type=Path, help="the run's output.json")
    ap.add_argument("--log", type=Path, default=None, help="the run's console log, to count retries")
    args = ap.parse_args()
    output = json.loads(args.output.read_text(encoding="utf-8"))
    bugs_path = args.output.with_name("bugs.json")
    bugs = json.loads(bugs_path.read_text(encoding="utf-8")) if bugs_path.exists() else None
    log_text = args.log.read_text(encoding="utf-8", errors="replace") if args.log and args.log.exists() else None
    print(summarize(output, log_text, bugs), end="")


if __name__ == "__main__":
    main()
