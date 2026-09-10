"""Read-only frontier crawl of a web app -> an ontology of its states and transitions.

The browser transposition of the game recon's exploration: enumerate the safe actions on
each state (from the DOM, filtered by `safety`), go to the nearest state that still has an
untried one, act, and record where it led plus any evidence the oracles found. No model,
nothing committing - it looks and navigates only.

A state is reached by replaying its discovery path from the start URL (deterministic, and
it works for SPAs whose "navigation" is a click, not a URL change). Reaching a state and
finding a different signature than last time is itself recorded, as state instability.

The frontier choice is a pure function (`choose_frontier`) so it is unit-tested on a
synthetic graph with no browser; the rest drives Playwright.

    python crawl.py <url> [--max N] [--headed] [--out PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from identity import appearance, signature
from oracles import run_observation_oracles
from perceive import Collector, capture
from safety import safe_actions
from schema import Action, Element, Evidence, Ontology, State, Transition


def choose_frontier(open_states: list[dict]) -> tuple[str, str] | None:
    """Pick the next (state_id, locator) to try: the state with an untried safe action
    that is *nearest* the start (shortest discovery path) - breadth-first coverage. Pure.

    `open_states` items: {"id", "path": [locator, ...], "untried": [locator, ...]}.
    Returns None when nothing is left to try.
    """
    candidates = [s for s in open_states if s["untried"]]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda s: (len(s["path"]), s["id"]))
    return nearest["id"], nearest["untried"][0]


def _settle(page, ms: int = 800) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


class Crawler:
    def __init__(self, page, collector: Collector, start_url: str, max_actions: int = 40):
        self.page = page
        self.col = collector
        self.start_url = start_url
        self.base_origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        self.max_actions = max_actions
        self.recs: dict[str, dict] = {}     # state_id -> record
        self.by_sig: dict[str, str] = {}    # signature -> state_id
        self.transitions: list[Transition] = []
        self.findings: list[Evidence] = []
        self.actions_taken = 0

    def _register(self, obs, path: list[str]) -> str:
        sig = signature(obs)
        if sig in self.by_sig:
            return self.by_sig[sig]
        state_id = f"st{len(self.recs) + 1:02d}"
        safe = safe_actions(obs.elements, self.base_origin)
        self.recs[state_id] = {
            "id": state_id, "signature": sig, "url": obs.url, "title": obs.title,
            "headings": obs.headings, "elements": obs.elements, "path": list(path),
            "safe": safe, "tried": set(), "first_seen": self.actions_taken,
        }
        self.by_sig[sig] = state_id
        return state_id

    def _reach(self, rec: dict):
        """Replay a state's discovery path from the start and return the before-frame
        Observation, or None (recording instability) if it lands on a different state."""
        self.page.goto(self.start_url, wait_until="domcontentloaded")
        _settle(self.page)
        for locator in rec["path"]:
            try:
                self.page.click(locator, timeout=3000)
            except Exception:
                self._instability(rec, f"could not replay click {locator}")
                return None
            _settle(self.page)
        here = capture(self.page, self.col)  # also drains the replay's own evidence
        if signature(here) != rec["signature"]:
            self._instability(rec, "replaying the path reached a different state")
            return None
        return here

    def _instability(self, rec: dict, why: str) -> None:
        self.findings.append(Evidence(kind="state_unstable", summary=f"{rec['id']}: {why}",
                                      state_id=rec["id"], seq=self.actions_taken))

    def _untried(self, rec: dict) -> list[dict]:
        return [e for e in rec["safe"] if e["locator"] not in rec["tried"]]

    def crawl(self) -> Ontology:
        self.page.goto(self.start_url, wait_until="domcontentloaded")
        _settle(self.page)
        start_obs = capture(self.page, self.col)
        start_id = self._register(start_obs, path=[])
        self.findings.extend(run_observation_oracles(start_obs, start_id, 0))

        while self.actions_taken < self.max_actions:
            open_states = [{"id": r["id"], "path": r["path"],
                            "untried": [e["locator"] for e in self._untried(r)]}
                           for r in self.recs.values()]
            choice = choose_frontier(open_states)
            if choice is None:
                break
            state_id, locator = choice
            rec = self.recs[state_id]
            rec["tried"].add(locator)
            element = next(e for e in rec["safe"] if e["locator"] == locator)

            before = self._reach(rec)
            if before is None:
                continue

            before_sig = rec["signature"]
            try:
                self.page.click(locator, timeout=3000)
            except Exception:
                self._instability(rec, f"click failed on {locator}")
                continue
            _settle(self.page)
            after = capture(self.page, self.col)
            self.actions_taken += 1

            after_sig = signature(after)
            dest_id = self._register(after, path=rec["path"] + [locator])
            self.findings.extend(run_observation_oracles(after, dest_id, self.actions_taken))

            if after_sig != before_sig:
                effect = "navigate"                          # went to another state
            elif appearance(after) != appearance(before):
                effect = "changed"                           # same state, content moved
            else:
                effect = "dead"                              # nothing changed at all

            action = Action(kind="click", element_key=f"{element['role']}:{element['name']}",
                            target=locator)
            self.transitions.append(Transition(
                id=f"tr{len(self.transitions) + 1:03d}", source=state_id, action=action,
                dest=dest_id, effect=effect, changed=(effect != "dead"),
                first_seen=self.actions_taken))

        return self._build()

    def _build(self) -> Ontology:
        states = [
            State(id=r["id"], url=r["url"], signature=r["signature"], title=r["title"],
                  first_seen=r["first_seen"],
                  elements=[Element(key=f"{e['role']}:{e['name']}", role=e["role"],
                                    name=e["name"], kind=e.get("tag", ""), locator=e["locator"],
                                    committing=(e not in r["safe"]), href=e.get("href", ""))
                            for e in r["elements"]])
            for r in self.recs.values()
        ]
        return Ontology(
            target={"url": self.start_url, "origin": self.base_origin},
            session={"actions": self.actions_taken, "states": len(states)},
            states=states, transitions=self.transitions, findings=self.findings,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default="http://localhost:5173/")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--out", default="out/ontology.json")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=400 if args.headed else 0)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        col = Collector().attach(page)
        onto = Crawler(page, col, args.url, max_actions=args.max).crawl()
        browser.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    onto.save(out)
    print(f"\ncrawled {args.url}")
    print(f"  states: {len(onto.states)}  transitions: {len(onto.transitions)}  "
          f"findings: {len(onto.findings)}  actions: {onto.session['actions']}")
    for s in onto.states:
        print(f"    [{s.id}] {s.signature}")
    for t in onto.transitions:
        print(f"    {t.source} --{t.action.element_key} ({t.effect})--> {t.dest}")
    for f in onto.findings:
        print(f"    FINDING [{f.kind}] {f.summary[:100]}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
