"""Score a web_gui run against a target's known problems: found X of Y, by evidence (issue #277).

Ten benchmark runs found the same things, and nothing said what they missed. This
matches a run's final observations against a list of known problems
(test-targets/known-problems/<target>.json). An observation finds a known problem only
when both hold:
- one of the tests it cites recorded that problem's signal: a console error or a failed
  request containing the problem's pattern, started the way the problem needs (a new
  tab, say)
- its claim names the problem: it contains one of the problem's 'named_by' words, in any
  case. Evidence alone overcounted: one observation about a 403 "found" a failing CDN
  too, because its test happened to show both.
Code does the matching, never a model.

It also says which known problems a test saw but no observation reported. "The harness
saw it and the Driver didn't report it" is a different weakness from "nobody saw it".

    python -m engine.adapters.web_gui.score --known test-targets/known-problems/juice-shop.json \\
        --run runs/ci/output.json [--out runs/ci/score.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SIGNAL_LISTS = {"console_error": "console_errors", "failed_request": "failed_requests"}


def _start_as(entry: dict) -> str:
    return (entry.get("request") or {}).get("start_as") or (entry.get("result") or {}).get("started_as") or "same_tab"


def shows(entry: dict, match: dict) -> bool:
    """Whether one test's recorded result shows a known problem's signal."""
    if match.get("start_as") and _start_as(entry) != match["start_as"]:
        return False
    key = _SIGNAL_LISTS.get(match["signal"])
    result = entry.get("result") or {}
    texts = [t for signals in (result.get("signals") or {}, result.get("signals_weak") or {})
             for t in signals.get(key, [])] if key else []
    return any(match["pattern"] in t for t in texts)


def names(observation: dict, problem: dict) -> bool:
    """Whether an observation's claim names the problem: one of its 'named_by' words."""
    claim = (observation.get("claim") or "").lower()
    return any(word.lower() in claim for word in problem.get("named_by", [])) if problem.get("named_by") else True


def score(known: dict, output: dict) -> dict:
    """found: known problems a final observation found, with how it was labelled.
    seen_not_reported: shown by a test that no observation cites. missed: neither."""
    tests = {e.get("test_number"): e for e in output.get("casting_log", [])}
    observations = output.get("observations", [])
    found, seen, missed = [], [], []
    for problem in known["problems"]:
        hits = [o for o in observations if names(o, problem)
                and any(shows(tests[n], problem["match"]) for n in o.get("tests", []) if n in tests)]
        showing = [n for n, e in tests.items() if shows(e, problem["match"])]
        if hits:
            found.append({"id": problem["id"], "title": problem["title"], "quality": problem.get("quality", ""),
                          "by": [{"observation": o["id"], "kind": o["kind"], "status": o.get("status", ""),
                                  "replay": o.get("replay", "")} for o in hits]})
        elif showing:
            seen.append({"id": problem["id"], "title": problem["title"], "tests": showing})
        else:
            missed.append({"id": problem["id"], "title": problem["title"]})
    return {"target": known.get("target", ""), "review": (known.get("review") or {}).get("status", ""),
            "known": len(known["problems"]), "found": found, "seen_not_reported": seen, "missed": missed,
            "out_of_reach": [p["id"] for p in known.get("out_of_reach", [])]}


def summary(result: dict) -> str:
    """The score as Markdown, for the run summary on a CI page."""
    def labels(f):
        return ", ".join(f"{b['observation']} {b['kind']}" + (f" ({b['status']})" if b["status"] else "") for b in f["by"])
    lines = [f"**Known problems found: {len(result['found'])} of {result['known']}** "
             f"({result['target']}, list {result['review'] or 'unreviewed'})."]
    lines += [f"- found {f['id']}: {f['title']}, as {labels(f)}" for f in result["found"]]
    lines += [f"- seen by tests {', '.join(map(str, s['tests']))} but not reported, {s['id']}: {s['title']}"
              for s in result["seen_not_reported"]]
    lines += [f"- missed {m['id']}: {m['title']}" for m in result["missed"]]
    if result["out_of_reach"]:
        lines.append(f"Out of the harness's reach, not counted: {', '.join(result['out_of_reach'])}.")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Score a web_gui run against a target's known problems.")
    ap.add_argument("--known", required=True, help="e.g. test-targets/known-problems/juice-shop.json")
    ap.add_argument("--run", required=True, help="the run's output.json")
    ap.add_argument("--out", default=None, help="also write the score as JSON here")
    args = ap.parse_args()
    known = json.loads(Path(args.known).read_text(encoding="utf-8"))
    result = score(known, json.loads(Path(args.run).read_text(encoding="utf-8")))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(summary(result), end="")


if __name__ == "__main__":
    main()
