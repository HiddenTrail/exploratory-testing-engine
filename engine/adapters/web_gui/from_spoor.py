"""Turn a Spoor exploration map into the ontology.json web_gui reads (issue #113).

web_gui recognises where it is by web-recon's live page signature, and Spoor's saved
map can't produce that signature: it has no URL, no headings and no DOM control list,
and it names controls from the accessibility tree. So this converter is *live*: it
replays Spoor's paths in a fresh browser session, captures each page the way
web-recon does, and writes web-recon's shape from what it saw. No LLM call.

What it keeps (#310): Spoor feeds the context, so the converted map keeps everything
Spoor reached. Testing fully (#299), every Spoor step whose control is found live is
replayed and becomes a path step, Add to Basket and Checkout included, so the screens
behind them reach the map. Two steps are refused: logging out, and on a part of the
target tagged careful, anything web-recon's read-only gate (`safety.plan`) wouldn't
click. Each control keeps the gate's verdict as `committing` (it changes data), and
`spoor_reached: false` when Spoor couldn't reach it (behind a dialog, #121); the sweep
leaves both out, the Driver's guide shows both. A page that doesn't replay to the same
signature twice is dropped.

States Spoor splits but web-recon's signature doesn't are merged, and edges that
become self-loops are dropped. Pages that only appear after a filled-in scaffold
(`spoor apply-scaffold`) aren't followed: web_gui doesn't replay typed values.

    python -m engine.adapters.web_gui.from_spoor \\
        --map .spoor-cache/maps/127.0.0.1_3000.json --url http://127.0.0.1:3000 \\
        --out .experiments/web-recon/out/juice-shop-from-spoor.json
"""

import argparse
import json
import os
import sys
from collections import deque
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from engine.adapters.web_gui import careful
from engine.adapters.web_gui import session as live_session  # puts web-recon on sys.path

import safety  # noqa: E402  (web-recon, on the path via session)
from identity import signature  # noqa: E402
from perceive import capture  # noqa: E402

SCHEMA = "web-recon/1"


def _norm(name: str) -> str:
    return " ".join((name or "").split()).lower()


def _find_element(obs, role: str, name: str) -> dict | None:
    """The live element for a Spoor action; {} when no element in the DOM capture has
    that name (it may still have it in the accessibility tree); None when several do.

    Spoor names controls from the accessibility tree and web-recon from the DOM, so the
    names can differ: Juice Shop's "Help getting started" is "school Help getting
    started" to web-recon, the "school" being an icon's ligature text. Matched on role
    and normalised name first; failing that, on the one element of the same role whose
    name *contains* Spoor's. More than one candidate, or none, means no match."""
    wanted = _norm(name)
    same_role = [e for e in obs.elements if e.get("role") == role]
    matches = [e for e in same_role if _norm(e.get("name", "")) == wanted]
    if not matches and wanted:
        matches = [e for e in same_role if wanted in _norm(e.get("name", ""))]
    if not matches:
        return {}
    return matches[0] if len(matches) == 1 else None


def changes_data(element: dict, origin: str) -> bool:
    """Whether the read-only gate holds this control back because using it would change
    data (a submit, or a name like "Add to Basket"), not for another reason."""
    reason = safety.plan(element, origin).reason
    return "mutating verb" in reason or "commits a form" in reason


def _why_not_follow(element: dict | None, name: str, obs, origin: str, tags: dict) -> str:
    """Why a Spoor step isn't replayed, or "" if it is. A step whose element isn't in the
    DOM capture by that name is followed by its accessible name, Spoor's own (#310): the
    replay finds it with Playwright's role lookup, and a page that doesn't replay twice
    is dropped as unstable anyway."""
    if element is None:
        return "more than one on the live page"
    if careful.logs_out(name):
        return "it logs out"
    parsed = urlparse(obs.url)
    route = (parsed.path or "/") + (f"#{parsed.fragment}" if parsed.fragment else "")
    if careful.applies(tags, route, name):
        if not element:
            return "tagged careful, and not in the page capture for the read-only gate to judge"
        if safety.plan(element, origin).kind != "click":
            return "tagged careful, and the read-only gate wouldn't click it"
    return ""


def _spoor_offers(element: dict, actions: list[tuple[str, str]]) -> bool:
    """Whether Spoor found this live element as an action, matched on role and name the
    same way as the steps (equal after normalising, or Spoor's name contained in it)."""
    name = _norm(element.get("name", ""))
    return any(role == element.get("role") and (spoor == name or (spoor and spoor in name))
               for role, spoor in actions)


def map_errors(exploration) -> list[str]:
    """What's missing from a Spoor `exploration` block, against the fields this
    converter reads. It's the contract with Spoor's saved map format (#144): CI runs
    a real, pinned Spoor and checks its output with this, so a format change in Spoor
    shows up as a clear failure instead of a KeyError on the next real map."""
    if not isinstance(exploration, dict):
        return ["the exploration block isn't an object"]
    errors = []
    lists = {}
    for key in ("states", "transitions", "skipped"):
        value = exploration.get(key)
        if not isinstance(value, list):
            errors.append(f"exploration.{key} is missing or not a list")
        else:
            lists[key] = value
    action = lambda a: isinstance(a, dict) and isinstance(a.get("role"), str) and isinstance(a.get("name"), str)
    for i, s in enumerate(lists.get("states", [])):
        if not isinstance(s, dict) or not isinstance(s.get("id"), str):
            errors.append(f"states[{i}] has no string id")
        elif not isinstance(s.get("actions", []), list) or not all(action(a) for a in s.get("actions", [])):
            errors.append(f"states[{i}].actions aren't all {{role, name}}")
    for i, t in enumerate(lists.get("transitions", [])):
        if not (isinstance(t, dict) and isinstance(t.get("from"), str) and isinstance(t.get("to"), str)
                and action(t.get("action"))):
            errors.append(f"transitions[{i}] isn't {{from, to, action: {{role, name}}}}")
    for i, k in enumerate(lists.get("skipped", [])):
        if not (isinstance(k, dict) and isinstance(k.get("from"), str) and action(k.get("action"))):
            errors.append(f"skipped[{i}] isn't {{from, action: {{role, name}}}}")
    return errors


def convert(exploration: dict, url: str, observe: Callable[[list[dict]], object | None],
            tags: dict | None = None) -> tuple[dict, dict]:
    """exploration: Spoor's saved `exploration` block. observe(path) replays a list of
    click steps from a fresh session and returns the captured Observation, or None if
    the replay failed or didn't reproduce. tags: the target's careful tags (#299),
    none by default. Returns (ontology, report)."""
    tags = tags if tags is not None else careful.NOTHING
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    spoor_states = [s["id"] for s in exploration.get("states", [])]
    if not spoor_states:
        raise SystemExit("the Spoor map has no states")
    # What Spoor found it could act on, per state. The page behind a modal dialog is inert
    # in the accessibility tree, so Spoor leaves it out, while web-recon's DOM capture
    # lists it: offering those controls meant clicks landed on the dialog's backdrop and
    # only closed the dialog (issue #121).
    spoor_actions = {s["id"]: [(a["role"], _norm(a["name"])) for a in s.get("actions", [])]
                     for s in exploration.get("states", [])}
    spoor_skipped = {(k["from"], k["action"]["role"], _norm(k["action"]["name"]))
                     for k in exploration.get("skipped", [])}
    outgoing: dict[str, list[dict]] = {}
    for t in exploration.get("transitions", []):
        if t["to"] != t["from"]:
            outgoing.setdefault(t["from"], []).append(t)

    by_signature: dict[str, dict] = {}   # signature -> web-recon state
    state_of: dict[str, str] = {}        # Spoor id -> web-recon id
    transitions: list[dict] = []
    report = {"spoor_states": len(spoor_states), "dropped_unstable": [], "refused_steps": 0, "refused": []}

    queue = deque([(spoor_states[0], [])])
    visited = set()
    while queue:
        spoor_id, path = queue.popleft()
        if spoor_id in visited:
            continue
        visited.add(spoor_id)
        obs = observe(path)
        if obs is None:
            report["dropped_unstable"].append(spoor_id)
            continue
        sig = signature(obs)
        if sig not in by_signature:
            safe_locators = {e["locator"] for e in safety.safe_actions(obs.elements, origin)}
            by_signature[sig] = {
                "id": f"st{len(by_signature) + 1:02d}", "url": obs.url, "signature": sig,
                "title": obs.title, "first_seen": len(by_signature),
                "elements": [{"key": f"{e['role']}:{e['name']}", "role": e["role"], "name": e["name"],
                              "kind": e.get("tag", ""), "locator": e["locator"],
                              "committing": e["locator"] not in safe_locators, "href": e.get("href", ""),
                              # What the Driver is told (#311): the gate also holds back a
                              # dropdown or a disabled button, which change nothing.
                              "changes_data": changes_data(e, origin)}
                             for e in obs.elements],
                "_spoor_ids": [],
            }
        by_signature[sig]["_spoor_ids"].append(spoor_id)
        state_of[spoor_id] = by_signature[sig]["id"]
        for t in outgoing.get(spoor_id, []):
            element = _find_element(obs, t["action"]["role"], t["action"]["name"])
            why = _why_not_follow(element, t["action"]["name"], obs, origin, tags)
            if why:
                report["refused_steps"] += 1
                report["refused"].append(f"{t['action']['role']}:{t['action']['name']} ({why})")
                continue
            step = {"role": t["action"]["role"], "name": t["action"]["name"], "locator": element.get("locator", "")}
            key = f"{element['role']}:{element['name']}" if element else f"{t['action']['role']}:{t['action']['name']}"
            transitions.append({"spoor_from": spoor_id, "spoor_to": t["to"], "step": step, "element_key": key})
            queue.append((t["to"], path + [step]))

    edges, seen_edges = [], set()
    for t in transitions:
        src, dest = state_of.get(t["spoor_from"]), state_of.get(t["spoor_to"])
        if not src or not dest or src == dest or (src, dest, t["element_key"]) in seen_edges:
            continue
        seen_edges.add((src, dest, t["element_key"]))
        edges.append({"id": f"tr{len(edges) + 1:02d}", "source": src, "dest": dest, "effect": "navigate",
                      "changed": True,
                      "action": {"kind": "click", "element_key": t["element_key"], "target": t["step"]["locator"]}})

    # A control Spoor didn't find on that page (any of the Spoor states merged into it),
    # or skipped there, is marked: it's often behind a dialog, where a click lands on the
    # backdrop (#121). The sweep leaves it out; the Driver's guide says so.
    hidden = 0
    for state in by_signature.values():
        ids = state["_spoor_ids"]
        offered = [a for sid in ids for a in spoor_actions.get(sid, [])
                   if (sid, a[0], a[1]) not in spoor_skipped]
        for element in state["elements"]:
            if not _spoor_offers(element, offered):
                element["spoor_reached"] = False
                hidden += 1
    report["hidden_controls"] = hidden

    states = [{k: v for k, v in s.items() if k != "_spoor_ids"} for s in by_signature.values()]
    report.update(states=len(states), transitions=len(edges))
    ontology = {"schema": SCHEMA, "target": {"url": url, "origin": origin},
                "session": {"source": "spoor", "converted_by": "engine.adapters.web_gui.from_spoor", **report},
                "states": states, "transitions": edges, "findings": [], "observations": []}
    return ontology, report


def live_observer(url: str, headed: bool = False, session_file: str | None = None):
    """observe(path) backed by a real browser: each call starts a fresh session (see
    Session._reboot), from session_file if given, replays the path twice, and returns the
    capture only if both replays reach the same signature."""
    sess = live_session.Session(None, url, headed, session_file)

    def replay(path):
        sess._reboot()
        for step in path:
            if not sess._actuate(step):
                return None
            sess._rest()
        return capture(sess.page, sess.col)

    def observe(path):
        first = replay(path)
        second = replay(path) if first is not None else None
        if first is None or second is None or signature(first) != signature(second):
            return None
        return second

    return observe, sess


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn a Spoor map into web_gui's ontology.json (live replay).")
    ap.add_argument("--map", required=True, help="Spoor's saved map, e.g. .spoor-cache/maps/127.0.0.1_3000.json")
    ap.add_argument("--url", required=True, help="the explored URL, as Spoor keyed it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--session", default=None,
                    help="a saved session file to replay with (#154); use the one Spoor mapped with (--session)")
    ap.add_argument("--product", default=None,
                    help="the product whose careful tags apply (default: WEB_GUI_PRODUCT)")
    args = ap.parse_args()

    saved = json.loads(Path(args.map).read_text(encoding="utf-8"))
    entry = saved.get(args.url) or saved.get(args.url.rstrip("/")) or saved.get(args.url.rstrip("/") + "/")
    if not entry or not entry.get("exploration"):
        raise SystemExit(f"no exploration for {args.url} in {args.map} (keys: {', '.join(saved)})")
    problems = map_errors(entry["exploration"])
    if problems:
        raise SystemExit("this Spoor map isn't in the format the converter reads (#144):\n  " + "\n  ".join(problems))
    session_file = live_session.load_session_file(args.session) if args.session else None
    observe, sess = live_observer(args.url, args.headed, session_file)
    try:
        tags = careful.load(args.product if args.product is not None else os.environ.get("WEB_GUI_PRODUCT", ""))
        ontology, report = convert(entry["exploration"], args.url, observe, tags)
    finally:
        sess.close()
    # Recorded so a run started from a different session warns (Session check_ready).
    ontology["session"]["session_name"] = live_session.session_name(session_file)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(ontology, indent=2), encoding="utf-8")
    print_summary(report, args.out)


def print_summary(report: dict, out: str, stream=None) -> None:
    """The one-line summary, plus the refused steps. Characters the console can't
    encode are replaced: on Windows (cp1252) a control named with an icon font's
    private-use character, like PrestaShop's "All products ", crashed the
    print after the map was already written (issue #150)."""
    stream = stream or sys.stdout
    try:
        stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print(f"converted {report['spoor_states']} Spoor states into {report['states']} states and "
          f"{report['transitions']} transitions; {len(report['dropped_unstable'])} dropped as unstable, "
          f"{report['refused_steps']} steps not followed, {report['hidden_controls']} controls "
          f"Spoor couldn't reach (kept, marked) -> {out}", file=stream)
    if report["refused"]:
        print("  refused:", ", ".join(report["refused"]), file=stream)


if __name__ == "__main__":
    main()
