"""What the runs covered in each area of a product, and how much each area matters next (#328).

The context learned where the Driver got to and which oracle ideas it cited, but not what
it covered. So the next run couldn't tell a screen tested hard from one nobody touched,
and the oracle couldn't point at the gaps. This keeps, per area and across runs: the tests
cast there, the controls they used, the kinds of value each field was sent, the oracle
ideas checked there with their answers, and the errors recorded. Then it scores each area
for the next run, with the reasons in words, so the score can be explained and argued with.

An area is a screen from Spoor's map (by its slug), a screen the Driver reached that the
map lacks (a discovery, by its id), or a route a test started from that no screen has.
The test's own envelope says where it started (outcome.py's `area`). Nothing here reads
an adapter's results: a start is matched to the context's screens by their map states
and routes, and a discovery is named from its url and the step that reached it.

Accepted limitations:
- A test counts for the area it started in. A step after one that moved to another
  screen is on that screen, but the envelope can't say which, so it only counts where
  the start screen has the same control.
- Coverage is kept by screen slug. A new Spoor map can name a screen differently, and
  then its coverage stays under the old slug, listed as an area with no screen.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from trailhound import ledger, outcome

# What raises an area's importance. Weights, not probabilities: the order they give is
# the point. An untouched area with a form must rank above the start page once that has
# been tested, and a place the Driver reached that the map lacks ranks with the gaps.
NEVER_TESTED = 3.0
UNTRIED_CONTROLS = 2.0     # times the share of its controls no test has used
UNCHECKED_IDEAS = 1.5      # times the share of its oracle ideas no test has checked
HAS_FIELDS = 1.0
FIELDS_NEVER_FILLED = 1.0  # times the share of its fields no test has filled
CHANGES_DATA = 1.0
ERRORS = 2.0
IDEAS_BROKE = 1.5
NOT_MAPPED = 2.0
# And what lowers it: tests already spent there. Without it a start page tested 21 times
# in two runs still outranked every screen nobody had touched, on its many gaps alone.
PER_TEST = 0.1
MOST_FOR_TESTS = 3.0
_LISTED = 2                # errors named in a reason
REACHED = "reached by the Driver, not mapped"
NO_SCREEN = "no screen in the context for it"
_MAX_TITLE = 70
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def route_of(url: str) -> str:
    """A url as a route: "http://shop/#/login?x=1" is "/#/login", the way the web adapter
    names a test's start."""
    parts = urlsplit(url or "")
    return (parts.path or "/") + (f"#{parts.fragment.split('?', 1)[0]}" if parts.fragment else "")


def area_key(token: str, screens: list[dict], discoveries: list[dict] = ()) -> str:
    """The context's key for where a test started: the screen whose map states include it,
    else the screen for that route with the shortest path to it (the one a route opens),
    else the place the Driver reached beyond the map at that route (the one reached most
    often), else the token itself. Without the discovery step a test that started at
    "/#/login" was kept apart from the login page the map lacked, which then looked never
    tested and pulled the next run's oracle back to it (#330 benchmark)."""
    for s in screens:
        if token in (s.get("states") or []):
            return s["slug"]
    on_route = [s for s in screens if s.get("route") == token]
    if on_route:
        return min(on_route, key=lambda s: len(s.get("path") or []))["slug"]
    if token.startswith("/"):
        reached = [d for d in discoveries if d.get("url") and route_of(d["url"]) == token]
        if reached:
            return max(reached, key=lambda d: (d.get("times_reached", 0), d["id"]))["id"]
    return token


def extract(output: dict, known_ideas: set[str] | None = None) -> dict[str, dict]:
    """A run's coverage by the area token each test started from. With `known_ideas`, an
    idea id that isn't one of them (the Driver made it up) is left out."""
    answers = ledger.idea_answers(output.get("checkpoints") or [])
    found: dict[str, dict] = {}
    for entry in output.get("casting_log") or []:
        envelope = outcome.read(entry)
        if entry.get("skipped") or not envelope or not envelope.get("area"):
            continue
        a = found.setdefault(envelope["area"], {"tests": 0, "tried": [], "inputs": {}, "ideas": {}, "problems": {}})
        a["tests"] += 1
        for token in envelope.get("tried") or []:
            if token not in a["tried"]:
                a["tried"].append(token)
        for field, kind in envelope.get("inputs") or []:
            kinds = a["inputs"].setdefault(field, [])
            if kind not in kinds:
                kinds.append(kind)
        idea = entry.get("oracle_claim_id")
        if idea and (known_ideas is None or idea in known_ideas):
            a["ideas"][idea] = answers.get(idea, a["ideas"].get(idea, ""))
        for p in envelope.get("problems") or []:
            a["problems"][p] = a["problems"].get(p, 0) + 1
    return found


def _empty() -> dict:
    return {"tests": 0, "runs": [], "tried": [], "inputs": {}, "ideas": {}, "problems": {}}


def _add(c: dict, a: dict, runs: list[str]) -> None:
    """Add coverage `a` (one run's, or another key's) into `c`."""
    c["tests"] += a.get("tests", 0)
    for run in runs:
        if run not in c["runs"]:
            c["runs"].append(run)
    c["tried"] = sorted(set(c["tried"]) | set(a.get("tried", [])))
    for field, kinds in (a.get("inputs") or {}).items():
        c["inputs"][field] = sorted(set(c["inputs"].get(field, [])) | set(kinds))
    for idea, answer in (a.get("ideas") or {}).items():
        if answer or idea not in c["ideas"]:
            c["ideas"][idea] = answer
    for p, n in (a.get("problems") or {}).items():
        c["problems"][p] = c["problems"].get(p, 0) + n


def refold(context: dict) -> None:
    """Move coverage kept under a key that now has a screen (a route tested before the map
    had it) onto that screen's key, so one place isn't split over two."""
    screens = context.get("screens") or []
    coverage = context.get("coverage") or {}
    for key in list(coverage):
        target = area_key(key, screens, context.get("discoveries") or [])
        if target == key:
            continue
        old = coverage.pop(key)
        c = coverage.setdefault(target, _empty())
        _add(c, old, old.get("runs", []))
        if old.get("order", 0) >= c.get("order", 0):
            c["last_run"], c["last_tested"], c["order"] = old.get("last_run"), old.get("last_tested"), old.get("order", 0)


def merge(context: dict, found: dict[str, dict], run: str, day: str | None = None) -> dict[str, bool]:
    """Add a run's coverage to the context's, by area key. Returns each area this run
    tested, and whether it was the first time any run did. An area that already holds
    this run is left as it is, so learning from the same run twice counts it once."""
    day = day or date.today().isoformat()
    screens = context.get("screens") or []
    refold(context)
    coverage = context.setdefault("coverage", {})
    before = {k for k, c in coverage.items() if c.get("tests")}
    learned = {k for k, c in coverage.items() if run in c.get("runs", [])}
    # When each area was last added to, so a later run's answer to an idea wins in rank.
    order = 1 + max((c.get("order", 0) for c in coverage.values()), default=0)
    tested: dict[str, bool] = {}
    for token, a in found.items():
        key = area_key(token, screens, context.get("discoveries") or [])
        tested[key] = key not in before
        if key in learned:
            continue
        c = coverage.setdefault(key, _empty())
        _add(c, a, [run])
        c["last_run"], c["last_tested"], c["order"] = run, day, order
    return tested


def _area(key: str, title: str, route: str, unmapped: str, controls, fields, changes, cov: dict | None,
          ideas_here: list[str], answers: dict[str, str]) -> dict:
    """One area's score and its reasons. `unmapped` is "" for a screen of the map, else
    why it has none: a place the Driver reached ranks with the gaps, a leftover key doesn't."""
    importance, why, found = 0.0, [], 0.0
    tested = bool(cov and cov.get("tests"))
    if not tested:
        importance += NEVER_TESTED
        why.append("never tested")
    else:
        untried = [c for c in controls if c not in cov.get("tried", [])]
        if untried:
            importance += UNTRIED_CONTROLS * len(untried) / len(controls)
            why.append(f"{len(untried)} of {len(controls)} controls never tried")
    if ideas_here:
        unchecked = [i for i in ideas_here if i not in answers]
        if unchecked:
            importance += UNCHECKED_IDEAS * len(unchecked) / len(ideas_here)
            why.append(f"{len(unchecked)} of {len(ideas_here)} oracle ideas not checked")
    if fields:
        importance += HAS_FIELDS
        why.append(f"{len(fields)} field(s)")
        if tested:
            never = [f for f in fields if f not in cov.get("inputs", {})]
            if never:
                importance += FIELDS_NEVER_FILLED * len(never) / len(fields)
                why.append(f"{len(never)} of {len(fields)} fields never filled")
    if changes:
        importance += CHANGES_DATA
        why.append(f"{len(changes)} control(s) change data")
    problems = sorted((cov or {}).get("problems", {}).items(), key=lambda kv: -kv[1])
    if problems:
        importance += ERRORS
        found += ERRORS
        why.append("errors recorded: " + "; ".join(p for p, _ in problems[:_LISTED])
                   + (f" and {len(problems) - _LISTED} more" if len(problems) > _LISTED else ""))
    broke = [i for i in ideas_here if answers.get(i) == "broke"]
    if broke:
        importance += IDEAS_BROKE
        found += IDEAS_BROKE
        why.append(f"{len(broke)} oracle idea(s) broke here")
    if unmapped:
        importance += NOT_MAPPED if unmapped == REACHED else 0.0
        why.append(unmapped)
    if tested:
        importance -= min(MOST_FOR_TESTS, PER_TEST * cov["tests"])
        why.append(f"tested {cov['tests']} time(s) already")
    # A well-tested area bottoms out at 0 rather than going negative.
    # `untested` is the same score without what was found there: how much of the area is
    # still untested. The oracle steers by it (#330), so a known error doesn't keep pulling
    # tests back; re-checking known findings will be #319's job.
    return {"key": key, "title": title, "route": route, "mapped": not unmapped,
            "tests": (cov or {}).get("tests", 0), "importance": round(max(0.0, importance), 1),
            "untested": round(max(0.0, importance - found), 1), "why": why}


def rank(context: dict, ideas: list[dict] | None = None) -> list[dict]:
    """Every area the context knows, most important first: the map's screens, the
    screens the Driver reached beyond the map, and routes tests started from that no
    screen has. `ideas` is the product's oracle. An idea belongs to the screen it's about,
    and counts as checked there whichever area the test that checked it started from."""
    refold(context)
    coverage = context.get("coverage") or {}
    # Every idea any test checked, with its latest answer: areas in the order they were
    # last added to, so a later run's answer wins.
    answers: dict[str, str] = {}
    for cov in sorted(coverage.values(), key=lambda c: c.get("order", 0)):
        for idea, answer in (cov.get("ideas") or {}).items():
            if answer or idea not in answers:
                answers[idea] = answer
    per_entity: dict[str, list[str]] = {}
    for idea in ideas or []:
        if idea.get("entity"):
            per_entity.setdefault(idea["entity"], []).append(idea["id"])
    areas, seen = [], set()
    for s in context.get("screens") or []:
        areas.append(_area(s["slug"], s.get("title", s["slug"]), s.get("route", ""), "", s.get("controls") or [],
                           s.get("fields") or [], s.get("changes_data") or [], coverage.get(s["slug"]),
                           per_entity.get(s["slug"], []), answers))
        seen.add(s["slug"])
    for d in context.get("discoveries") or []:
        if d["id"] in seen:
            continue
        route = route_of(d.get("url", ""))
        # A single-page app has one page title everywhere, so it's named by how it was reached.
        # Without emails: the account menu's name holds whoever is logged in.
        via = " ".join(_EMAIL.sub("", d.get("via") or "a test").split())
        title = f"{route}, reached by {via}"
        title = title if len(title) <= _MAX_TITLE else title[:_MAX_TITLE - 3] + "..."
        areas.append(_area(d["id"], title, route, REACHED, d.get("controls") or [], d.get("fields") or [],
                           d.get("changes_data") or [], coverage.get(d["id"]), per_entity.get(d["id"], []), answers))
        seen.add(d["id"])
    for key, cov in coverage.items():
        if key not in seen:
            # A route a test started from is a place the map lacks. Anything else (a map
            # state id with no product screens, a slug a new map renamed) just has no screen.
            route = key if key.startswith("/") else ""
            areas.append(_area(key, key, route, REACHED if route else NO_SCREEN, [], [], [], cov, [], answers))
    return sorted(areas, key=lambda a: (-a["importance"], a["key"]))
