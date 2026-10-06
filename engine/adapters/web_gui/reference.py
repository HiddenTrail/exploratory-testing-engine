"""The carried reference for the web-GUI adapter: a web-recon `ontology.json`, read as
the map the Driver is briefed on and the action space it may pick from.

This is the seam between the two halves of Stage 6. The deterministic crawler
(.experiments/web-recon) does the read-only recon and writes the ontology; here that
ontology becomes the *carried reference* - exactly as clash_royale carries an earlier
recon pass's fingerprinted screens. The Driver never invents a control or a
coordinate: it may only name a (state, control) pair the recon already found and cleared
as safe, and this module is what enumerates those pairs and computes how to reach each.

Pure: it reads a JSON dict and does graph arithmetic over it. No browser, no model, no
web-recon import - so it is unit-tested against a fixture ontology with nothing attached.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

# The three structural predictions the Driver may make about where an action lands - the
# same taxonomy web-recon's signature draws and clash_royale predicts against.
PREDICTIONS = ("same_screen", "known_screen", "new_screen")


def _split_key(element_key: str) -> tuple[str, str]:
    role, _, name = (element_key or "").partition(":")
    return role, name


class Reference:
    """A loaded web-recon ontology, indexed for the adapter's needs."""

    def __init__(self, data: dict):
        self.schema = data.get("schema", "")
        self.base_url = (data.get("target") or {}).get("url", "")
        # Which saved session the map was made with ("" for none), so a run can warn when it
        # starts from a different one (issue #154).
        self.session_name = (data.get("session") or {}).get("session_name", "")
        self.states = data.get("states", [])
        self.transitions = data.get("transitions", [])
        self._by_id = {s["id"]: s for s in self.states}
        self.known_signatures = {s["signature"] for s in self.states}
        # The map as carried in, before any screen discovered during the run joins it
        # (issue #158): a discovery is judged against this, so it's still counted when
        # it's reached again after it joined (#157).
        self.carried_signatures = set(self.known_signatures)
        self._entry = self._find_entry()
        self._paths = self._compute_paths()          # state_id -> [step, ...] from the entry
        self._catalogue = self._build_catalogue()    # (state_id, control_key) -> {path, target}

    # ---- construction ----------------------------------------------------------------

    def _find_entry(self) -> str:
        """The state the run starts on. web-recon always registers the start state first,
        with first_seen == 0, so the earliest-seen state is the entry - robust even when a
        back-edge makes the entry a navigation destination too (which would fool a
        no-in-edges heuristic into picking an orphan instead)."""
        if not self.states:
            return ""
        return min(self.states, key=lambda s: (s.get("first_seen", 0), s["id"]))["id"]

    def _step(self, t: dict) -> dict:
        role, name = _split_key(t["action"].get("element_key", ""))
        return {"role": role, "name": name, "locator": t["action"].get("target", "")}

    def _compute_paths(self) -> dict:
        """A shortest navigation path (a list of actuation steps) from the entry state to
        every state reachable by in-app navigations. BFS over 'navigate' edges only -
        'changed'/'dead'/'blocked'/'external' edges do not move to a new mappable state."""
        adj = defaultdict(list)
        for t in self.transitions:
            if (t.get("effect") == "navigate" and t.get("dest") not in (t.get("source"), "external")
                    and t.get("dest") in self._by_id):
                adj[t["source"]].append((t["dest"], self._step(t)))
        paths = {self._entry: []}
        queue = [self._entry]
        while queue:
            cur = queue.pop(0)
            for dest, step in adj[cur]:
                if dest not in paths:
                    paths[dest] = paths[cur] + [step]
                    queue.append(dest)
        return paths

    def _build_catalogue(self) -> dict:
        """Every safe (state, control) the Driver may test: a control the recon found on a
        reachable state and did NOT mark committing (so the read-only safety gate already
        cleared it). Value carries the path to the state and how to actuate the control."""
        cat = {}
        for s in self.states:
            path = self._paths.get(s["id"])
            if path is None:                         # not reachable by navigation from entry
                continue
            for e in s.get("elements", []):
                # Fail CLOSED: an element must be *explicitly* non-committing to enter the
                # action space. A missing/misspelled 'committing' key (a foreign or
                # hand-edited ontology) defaults to committing=True and is excluded, rather
                # than silently offering an unvetted - possibly destructive - control.
                if e.get("committing", True) or not e.get("name"):
                    continue
                cat[(s["id"], e["key"])] = {
                    "path": path,
                    "target": {"role": e["role"], "name": e["name"], "locator": e["locator"]},
                }
        return cat

    def rewrite_signatures(self, fn) -> None:
        """Each carried state's signature rewritten by fn, for a map saved before the
        signature changed (#303: fn takes the logged-in user's email out). Pure: the
        caller passes the function, so this module still needs no web-recon import."""
        for state in self.states:
            state["signature"] = fn(state.get("signature", ""))
        self.known_signatures = {s["signature"] for s in self.states}
        self.carried_signatures = set(self.known_signatures)

    # ---- growing during a run (issue #158) -------------------------------------------

    def add_discovery(self, record: dict, max_steps: int, earlier_run: bool = False) -> str | None:
        """Add a screen a test reached beyond the carried map (session.discovery's record)
        as a state of this run's map, so later tests can act on it: its id becomes a
        state id, its path is how it's reached (replayed from a fresh session, like any
        carried path), and its controls the safety gate cleared become pairs. Returns the
        state id, or None for a screen the carried map already has or one more than
        `max_steps` steps from the start (so discoveries of discoveries can't run away).

        `earlier_run`: a screen an earlier run found, checked at the start of this one
        (issue #159). It joins as if it were carried, so reaching it again isn't a new
        discovery."""
        if record["signature"] in self.carried_signatures or len(record["path"]) > max_steps:
            return None
        sid = record["id"]
        if sid in self._by_id:
            return sid
        state = {"id": sid, "url": record["url"], "signature": record["signature"], "title": record["title"],
                 "first_seen": len(self.states), "elements": record["elements"], "discovered": True,
                 "reached_from": f"{record['from_state']} :: {record['via']}"}
        self.states.append(state)
        self._by_id[sid] = state
        self.known_signatures.add(record["signature"])
        if earlier_run:
            state["from_earlier_run"] = True
            self.carried_signatures.add(record["signature"])
        self._paths[sid] = list(record["path"])
        self.transitions.append({"source": record["from_state"], "dest": sid, "effect": "navigate",
                                 "discovered": True, "action": {"kind": "click", "element_key": record["via"],
                                                                 # A path can end in a route or "back" (#310).
                                                                 "target": (record["path"][-1].get("locator")
                                                                            or record["path"][-1].get("goto", ""))}})
        for e in record["elements"]:
            if e.get("committing", True) or not e.get("name"):   # the same fail-closed rule as the map
                continue
            self._catalogue[(sid, e["key"])] = {
                "path": self._paths[sid],
                "target": {"role": e["role"], "name": e["name"], "locator": e["locator"]},
            }
        return sid

    def controls_on(self, state_id: str) -> list[str]:
        """The control keys the Driver may act on at a state, sorted."""
        return sorted(k for (sid, k) in self._catalogue if sid == state_id)

    # ---- queries ---------------------------------------------------------------------

    def entry(self) -> str:
        return self._entry

    def pairs(self) -> set:
        return set(self._catalogue)

    def plan_for(self, state_id: str, control_key: str) -> dict | None:
        return self._catalogue.get((state_id, control_key))

    def state_label(self, state_id: str) -> str:
        s = self._by_id.get(state_id)
        if not s:
            return state_id
        title = s.get("title") or ""
        parts = (s.get("signature") or "").split("|")
        hint = title or (parts[2] if len(parts) > 2 and parts[2] else (parts[0] or "/"))
        if s.get("from_earlier_run"):
            # A single-page app gives every screen one title, so the route says more.
            url = urlsplit(s.get("url") or "")
            route = url.path + (f"#{url.fragment}" if url.fragment else "")
            hint = f"{route or hint[:40]}, found by an earlier run"
        return f"{state_id} ({hint[:80]})" if hint else state_id

    def is_known(self, sig: str) -> bool:
        return sig in self.known_signatures

    def driver_briefing(self) -> str:
        """The map, as text the Driver is onboarded with: each screen a test can start from,
        its route, and what the recon found on it. A guide, not a limit (#310): a test can
        start from any route and act on anything on the live page."""
        lines = []
        for s in self.states:
            if s["id"] not in self._paths:
                continue
            controls = sorted(k for (sid, k) in self._catalogue if sid == s["id"])
            depth = len(self._paths[s["id"]])
            reach = "the start screen" if depth == 0 else f"{depth} navigation(s) from the start"
            url = urlsplit(s.get("url") or "")
            route = (url.path or "/") + (f"#{url.fragment}" if url.fragment else "")
            lines.append(f"  {self.state_label(s['id'])} - route {route} - {reach}")
            lines.extend(f"      {c}" for c in controls)
        return "\n".join(lines) or "  (the map has no screens; start from a route)"


def load(path: str | Path) -> Reference:
    return Reference(json.loads(Path(path).read_text(encoding="utf-8")))
