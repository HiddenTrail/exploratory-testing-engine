"""Sweep every reachable action on a web target, to know what could be found at all (issue #276).

A run's findings only mean something against what it could have found. On a web target
that ceiling is set by the map (which actions the Driver may take) and by the harness
(what it can observe). This runs every (state, control) pair in the map once, as the
same tab and as a new tab of the logged-in browser, with no model, and collects every
problem the harness observes, deduplicated:

- a console error, keyed by its first line
- a failed request, keyed by method, path and status (own origin trusted, others weak)
- a new-tab difference: the same action shows a console error or lands elsewhere as a
  new tab than as the same tab (state kept per tab)

With --follow-discoveries, screens discovered on the way join the queue, as they would
for the Driver. It's off by default: on Juice Shop, switching language "discovers" a
translated copy of every screen, and the first sweep stopped at its 400-action cap with
1,220 actions still queued. The output
is a candidate list of known problems for that target and session, for a person to
review before it becomes ground truth (#277). It uses the same session, safety gate,
rested reads and trusted/weak split as a run.

    python -m engine.adapters.web_gui.sweep --ontology .experiments/web-recon/out/juice-shop-logged-in.json \\
        --url http://127.0.0.1:3000 --session .sessions/juice-shop/logged-in.json --out runs/sweep/juice-shop.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0][:160] if (text or "").strip() else ""


def _request_key(line: str) -> str:
    """'GET http://host/path?x=1 -> 500' as 'GET /path -> 500'."""
    try:
        method, rest = line.split(" ", 1)
        url, _, status = rest.partition(" -> ")
        return f"{method} {urlsplit(url).path or '/'} -> {status}"
    except ValueError:
        return line[:160]


def _route(signature: str) -> str:
    return (signature or "").split("|", 1)[0] or "?"


def problems_in(result: dict) -> list[dict]:
    """The problems one action's result shows, before deduplication."""
    found = []
    for tier, signals in (("trusted", result.get("signals") or {}), ("weak", result.get("signals_weak") or {})):
        for text in signals.get("console_errors", []):
            found.append({"type": "console_error", "pattern": _first_line(text), "tier": tier})
        for line in signals.get("failed_requests", []):
            found.append({"type": "failed_request", "pattern": _request_key(line), "tier": tier})
    return found


def aggregate(records: list[dict]) -> list[dict]:
    """Every problem once, with where it showed (routes, actions, how the test started).
    A problem seen as trusted anywhere counts as trusted."""
    by_key: dict = {}
    for rec in records:
        for p in rec["problems"]:
            key = (p["type"], p["pattern"])
            entry = by_key.setdefault(key, {"type": p["type"], "pattern": p["pattern"], "tier": "weak",
                                            "routes": [], "actions": [], "start_as": [], "times": 0})
            entry["times"] += 1
            if p["tier"] == "trusted":
                entry["tier"] = "trusted"
            for field, value in (("routes", rec["route_after"]), ("actions", rec["action"]),
                                 ("start_as", rec["start_as"])):
                if value not in entry[field]:
                    entry[field].append(value)
    # Problems a new tab shows that the same tab didn't, for the same action.
    same = {(r["action"], p["type"], p["pattern"]) for r in records if r["start_as"] == "same_tab" for p in r["problems"]}
    for rec in records:
        if rec["start_as"] != "new_tab":
            continue
        for p in rec["problems"]:
            if (rec["action"], p["type"], p["pattern"]) not in same:
                by_key[(p["type"], p["pattern"])]["new_tab_only"] = True
    problems = sorted(by_key.values(), key=lambda e: (e["tier"] != "trusted", e["type"], e["pattern"]))
    for i, p in enumerate(problems, start=1):
        p["id"] = f"P{i:02d}"
    return problems


def sweep(session, reference, new_tab: bool, max_actions: int, log=print, follow_discoveries: bool = False) -> dict:
    """Run every pair once (and as a new tab), up to max_actions; with follow_discoveries,
    the pairs of screens discovered on the way too."""
    queue = sorted(reference.pairs())
    seen_pairs, records, unreached = set(queue), [], []
    started = time.time()
    while queue and len(records) < max_actions:
        state_id, control = queue.pop(0)
        for start_as in (("same_tab", "new_tab") if new_tab else ("same_tab",)):
            result = session.act(state_id, control, start_as)
            if not result.get("reached_target_state") or result.get("verdict") != "sent":
                unreached.append(f"{state_id} :: {control} ({start_as})")
            records.append({"action": f"{state_id} :: {control}", "start_as": start_as,
                            "route_after": _route(result.get("screen_after", "")), "problems": problems_in(result)})
            log(f"  {len(records):3d} {start_as:8} {state_id} :: {control[:50]} -> {_route(result.get('screen_after', ''))} "
                f"({len(records[-1]['problems'])} problem signal(s))")
        for pair in sorted(reference.pairs()) if follow_discoveries else ():   # screens discovered on the way
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                queue.append(pair)
    return {"actions_run": len(records), "pairs_left": len(queue), "unreached": unreached,
            "seconds": round(time.time() - started), "problems": aggregate(records), "records": records}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Run every reachable action once and list what the harness observes.")
    ap.add_argument("--ontology", required=True, help="the converted map (from_spoor's output)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--session", default=None, help="a saved session file, for a target behind a login")
    ap.add_argument("--out", required=True, help="where to write the sweep, e.g. runs/sweep/juice-shop.json")
    ap.add_argument("--no-new-tab", action="store_true", help="skip running each action again as a new tab")
    ap.add_argument("--max-actions", type=int, default=400, help="stop after this many actions (default 400)")
    ap.add_argument("--follow-discoveries", action="store_true",
                    help="also run the actions on screens discovered on the way (can grow fast, e.g. one per language)")
    args = ap.parse_args()

    os.environ["WEB_GUI_ONTOLOGY"], os.environ["WEB_GUI_URL"] = args.ontology, args.url
    if args.session:
        os.environ["WEB_GUI_SESSION"] = args.session
    os.environ["WEB_GUI_VIDEO"] = "off"   # a sweep has no report to show videos in (#286)
    from engine.adapters.web_gui import adapter as adp
    from engine.adapters.web_gui import session as live_session

    live_session.check_ready(adp.ADAPTER)
    session = live_session.live()
    try:
        result = sweep(session, session.reference, new_tab=bool(args.session) and not args.no_new_tab,
                       max_actions=args.max_actions, follow_discoveries=args.follow_discoveries)
    finally:
        session.close()
    result.update({"target": args.url, "map": args.ontology,
                   "session": live_session.session_name(args.session) if args.session else ""})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{result['actions_run']} actions in {result['seconds']} s, {len(result['unreached'])} didn't reach their "
          f"state; {len(result['problems'])} distinct problem(s) observed:")
    for p in result["problems"]:
        flags = " (new tab only)" if p.get("new_tab_only") else ""
        print(f"  {p['id']} {p['tier']:7} {p['type']:14} {p['pattern'][:90]}{flags}  on {', '.join(p['routes'][:3])}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
