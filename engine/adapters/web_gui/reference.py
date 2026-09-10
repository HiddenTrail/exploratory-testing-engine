"""The carried reference for the web-GUI adapter: a web-recon `ontology.json`, read as
the map the Driver is briefed on and the action space it may pick from.

This is the seam between the two halves of Stage 6. The deterministic crawler
(experiments/web-recon) does the read-only recon and writes the ontology; here that
ontology becomes the *carried reference* - exactly as clash_royale carries an earlier
recon pass's eleven fingerprinted screens. The Driver never invents a control or a
coordinate: it may only name a (state, control) pair the recon already found and cleared
as safe, and this module is what enumerates those pairs and computes how to reach each.

Pure: it reads a JSON dict and does graph arithmetic over it. No browser, no model, no
web-recon import - so it is unit-tested against a fixture ontology with nothing attached.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

# The three structural predictions the Driver may make about where an action lands - the
# same taxonomy web-recon's signature draws and clash_royale predicts against.
PREDICTIONS = ("same_screen", "known_screen", "new_screen")


def _split_key(element_key: str) -> tuple[str, str]:
    role, _, name = (element_key or "").partition(":")
    return role, name


class Reference:
    """A loaded web-recon ontology, indexed for the adapter's needs."""

    def __init__(self, data: dict):
        self.base_url = (data.get("target") or {}).get("url", "")
        self.states = data.get("states", [])
        self.transitions = data.get("transitions", [])
        self._by_id = {s["id"]: s for s in self.states}
        self.known_signatures = {s["signature"] for s in self.states}
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
                if e.get("committing") or not e.get("name"):
                    continue
                cat[(s["id"], e["key"])] = {
                    "path": path,
                    "target": {"role": e["role"], "name": e["name"], "locator": e["locator"]},
                }
        return cat

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
        return f"{state_id} ({hint[:40]})" if hint else state_id

    def is_known(self, sig: str) -> bool:
        return sig in self.known_signatures

    def driver_briefing(self) -> str:
        """The map, as text the Driver is onboarded with: each reachable state and the
        controls it may test there. This is the action space - there is no other."""
        lines = []
        for s in self.states:
            if s["id"] not in self._paths:
                continue
            controls = sorted(k for (sid, k) in self._catalogue if sid == s["id"])
            depth = len(self._paths[s["id"]])
            reach = "the start screen" if depth == 0 else f"{depth} navigation(s) from the start"
            lines.append(f"  {self.state_label(s['id'])} - {reach}")
            for c in controls:
                lines.append(f"      {s['id']} :: {c}")
            if not controls:
                lines.append("      (no safe controls found here)")
        return "\n".join(lines) or "  (the carried map has no reachable controls)"


def load(path: str | Path) -> Reference:
    return Reference(json.loads(Path(path).read_text(encoding="utf-8")))
