"""A run's outcome as a short Markdown summary, for a CI job's summary page (issue #255).

    python -m trailhound.run_summary runs/ci/output.json [--log runs/ci/run.log] >> "$GITHUB_STEP_SUMMARY"

Reads only the engine's own fields in output.json: the observations and their status,
the bug replays (#177), the stop reason and the token usage. The retries are counted
from the run's log, where call_tool_with_retry prints each one. No model call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trailhound import budget, ledger, interplay
from trailhound.tools import claim_results


_KIND_ORDER = {"bug": 0, "anomaly": 1, "finding": 2}


def estimated_cost(usage_summary: dict) -> float:
    """An estimate only, at trailhound/budget.py's list prices. The real bill is in the
    provider's console; this is here so a run that suddenly costs three times as much
    stands out."""
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return budget.estimated_cost({k: sum(call.get(k, 0) for call in usage_summary.values()) for k in keys})


def count_retries(log_text: str) -> int:
    return log_text.count("produced malformed output") + log_text.count("produced no tool call")


def _oracle_and_errors(output: dict) -> list[str]:
    """How the run used the oracle, and whether every recorded error got an answer (#312)."""
    ranked = (output.get("onboarding_extra") or {}).get("oracle_ranked") or []
    checkpoints = output.get("checkpoints") or []
    lines = []
    if ranked:
        answers = ledger.idea_answers(checkpoints)
        counts = {v: list(answers.values()).count(v) for v in ("held", "broke", "cannot_tell")}
        lines.append(f"**The oracle:** {len(answers)} of {len(ranked)} ideas checked: {counts['held']} held, "
                     f"{counts['broke']} broke, {counts['cannot_tell']} couldn't tell.")
    test_problems = ledger.problems_by_test(output.get("casting_log") or [])
    if test_problems:
        recorded = {p for ps in test_problems.values() for p in ps}
        unanswered = ledger.open_errors(test_problems, ledger.accounted(checkpoints, test_problems))
        dismissed = sum(len((cp.get("hypothesis") or {}).get("dismissed_errors") or []) for cp in checkpoints)
        lines.append(f"**Errors the tests recorded:** {len(recorded)}, "
                     + ("every one answered" if not unanswered else f"{len(unanswered)} without an answer")
                     + f" ({dismissed} dismissed with a reason).")
    return lines + ([""] if lines else [])


# A claim parked by #305, kept in the conclusion but given no more tests.
# A claim parked by #305 in an earlier checkpoint, kept in the conclusion with no more tests.
_PARKED = "parked: objected to in checkpoints in a row, so it got no more tests"
_QUESTION_CHARS = 60


def _results(cp: dict) -> list[dict] | None:
    """A checkpoint's claims by claim_results, or None when it has no hypothesis or review.
    Read with defaults: a summary must not crash on an odd saved run."""
    hypothesis, review = cp.get("hypothesis"), cp.get("skeptic_review")
    if not hypothesis or not review:
        return None
    return claim_results({"observations": hypothesis.get("observations") or []},
                         {"observation_checks": review.get("observation_checks") or [],
                          "gaps": [g for g in review.get("gaps") or [] if isinstance(g.get("about"), list)]})


def _held_back(output: dict) -> dict[str, list[str]]:
    """What keeps each of the last checkpoint's claims inconclusive (#342), a blocking
    question with its text, since the summary doesn't list the gaps."""
    last = (output.get("checkpoints") or [{}])[-1]
    results = _results(last)
    if results is None:
        return {}
    text = {g.get("id"): " ".join((g.get("gap") or "").split()) for g in last["skeptic_review"].get("gaps") or []}

    def said(reason: str) -> str:
        gid = reason.rsplit(" ", 1)[-1]
        if not reason.startswith("open blocking question") or not text.get(gid):
            return reason
        question = text[gid] if len(text[gid]) <= _QUESTION_CHARS else text[gid][:_QUESTION_CHARS - 3] + "..."
        return f"{reason} ({question})"
    return {r["id"]: [said(reason) for reason in r["held_back"]] for r in results}


def _held_back_cell(o: dict, held_back: dict[str, list[str]]) -> str:
    if o.get("status") == "corroborated":
        return ""
    if o.get("id") in held_back:
        return "; ".join(held_back[o["id"]])
    return _PARKED if o.get("parked") else ""


def _claims(output: dict, observations: list[dict]) -> list[str]:
    """How the claims came out (#342), before the table: the checkpoint verdict is all or
    nothing, one blocking question on any claim makes it weak, so on its own it says little."""
    checkpoints = output.get("checkpoints") or []
    if not observations and not checkpoints:
        return []
    per, verdicts, last_ids = [], [], set()
    for n, cp in enumerate(checkpoints, start=1):
        results = _results(cp)
        if results is None:
            continue
        per.append(f"C{n} {sum(1 for r in results if r['status'] == 'corroborated')} of {len(results)}")
        verdicts.append((cp["skeptic_review"].get("verdict") or "?").replace("_", " "))
        last_ids = {r["id"] for r in results}
    if "observations" not in output:
        line = "**Claims:** the run stopped before its conclusion"
    else:
        held = sum(1 for o in observations if o.get("status") == "corroborated")
        carried = sum(1 for o in observations if o.get("id") not in last_ids)
        line = (f"**Claims:** {held} of {len(observations)} claim(s) hold up at the end of the run"
                + (f" (the last checkpoint's {len(observations) - carried}, plus {carried} parked earlier)"
                   if carried and last_ids else ""))
    if per:
        line += f"; by checkpoint {', '.join(per)}. The Skeptic's verdicts: {', '.join(verdicts)}"
    return [line + ".", ""]


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
    lines += _claims(output, observations)
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
        held_back = _held_back(output)
        lines += ["| Id | Kind | Status | Held back by | Severity | Replay | Claim |", "|---|---|---|---|---|---|---|"]
        for o in observations:
            kind = o.get("kind", "")
            if o.get("driver_kind") and o["driver_kind"] != kind:
                kind += f" (Driver said {o['driver_kind']})"
            lines.append(f"| {o.get('id', '')} | {kind} | {o.get('status', '')} | "
                         f"{_cell(_held_back_cell(o, held_back))} | "
                         f"{o.get('severity', '')} | "
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
    lines += _oracle_and_errors(output)
    parked = [p for c in output.get("checkpoints") or [] for p in c.get("parked") or []]
    if parked:
        lines += ["**Parked** (the tests couldn't settle them, so they got no more, #305): " + ", ".join(
            f"{p['claim']} ({p['checkpoints_in_a_row']} checkpoints in a row)" for p in parked), ""]
    if output.get("learned"):                    # written by --learn after the run (#328)
        lines += ["**Learned for the next run:**", *(f"- {_cell(line)}" for line in output["learned"]), ""]
    lines += _cache_line(output)
    usage = output.get("usage_summary") or {}
    if usage:
        calls = sum(c.get("calls", 0) for c in usage.values())
        retries = f", {count_retries(log_text)} retried" if log_text is not None else ""
        dropped = count_dropped_tests(output)
        retries += f", {dropped} cast test(s) dropped without running" if dropped else ""
        lines.append(f"{calls} model call(s){retries}. Estimated cost about ${estimated_cost(usage):.2f} "
                     f"(list prices for a Sonnet-class model; the provider's console has the real bill).")
    return "\n".join(lines) + "\n"


def _cache_line(output: dict) -> list[str]:
    """How the prompt cache did (#393), from the saved usage log: the tokens written and read,
    and the calls that came more than 5 minutes after the previous call of the same kind, which
    is how long a cached prompt lives, and so wrote the prompt again. Empty without a usage log."""
    from datetime import datetime

    log = [u for u in output.get("usage_log") or [] if u.get("at")]
    if not log:
        return []
    written = sum(u.get("cache_creation_input_tokens", 0) for u in log)
    read = sum(u.get("cache_read_input_tokens", 0) for u in log)
    last_by_kind, expired = {}, 0
    for u in log:
        at = datetime.fromisoformat(u["at"])
        before = last_by_kind.get(u["call"])
        if before is not None and (at - before).total_seconds() > 300 and not u.get("cache_read_input_tokens"):
            expired += 1
        last_by_kind[u["call"]] = at
    line = f"Prompt cache: {written:,} tokens written, {read:,} read."
    if expired:
        line += (f" {expired} call(s) came more than 5 minutes after the previous one of their kind and wrote their prompt "
                 "again. On a slow target TRAILHOUND_CACHE_TTL=1h keeps it alive, at twice the write price.")
    return [line, ""]


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
