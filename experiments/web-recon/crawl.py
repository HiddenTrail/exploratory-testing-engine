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


# A flaky reach/click gets one retry before the action is abandoned, so a transient
# slow load does not silently drop a branch of the graph - but a persistently failing
# control is given up after this many attempts rather than spun on forever.
MAX_ACTION_ATTEMPTS = 2

# Roles Playwright's get_by_role can target by accessible name. Addressing a control by
# (role, name) survives DOM reshuffles - async content appearing, siblings inserted -
# far better than a positional CSS path, which silently points at the wrong node once
# the tree around it changes. Only the roles a read-only crawl actually clicks are here
# (form roles are always committing and never reach _click); Stage 5 can widen it.
ROLE_LOCATABLE = frozenset({"button", "link", "tab", "menuitem"})


def dedup_findings(findings: list) -> list:
    """Collapse identical findings (same kind, summary, state) to one - a state
    revisited many times re-fires the same console/network error, and one defect should
    be reported once, not per visit."""
    seen, out = set(), []
    for f in findings:
        key = (f.kind, f.summary, f.state_id)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


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


def _settle(page, ms: int = 900) -> None:
    """Wait for the app to go quiet before reading or acting. networkidle matters here:
    apps fetch their data after first paint (EcoEstate renders its mode/search controls
    only once the fetch resolves), so capturing or clicking before idle sees a
    half-rendered page and misses or mis-hits controls."""
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


class Crawler:
    def __init__(self, page, collector: Collector, start_url: str, max_actions: int = 40,
                 out_dir: Path | None = None):
        self.page = page
        self.col = collector
        self.start_url = start_url
        self.base_origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        self.max_actions = max_actions
        # Where per-state screenshots go (relative "images/<id>.png" recorded on each
        # state), so the wiki can show what each state looked like - the browser analog
        # of the game wiki's per-screen picture.
        self.images_dir = (out_dir / "images") if out_dir else None
        self.recs: dict[str, dict] = {}     # state_id -> record
        self.by_sig: dict[str, str] = {}    # signature -> state_id
        self.transitions: list[Transition] = []
        self.findings: list[Evidence] = []
        self.actions_taken = 0

    def _register(self, obs, path: list[dict]) -> str:
        sig = signature(obs)
        if sig in self.by_sig:
            return self.by_sig[sig]
        state_id = f"st{len(self.recs) + 1:02d}"
        safe = safe_actions(obs.elements, self.base_origin)
        # The page currently shows this just-captured state, so a screenshot now is of it.
        image = ""
        if self.images_dir:
            try:
                self.images_dir.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(self.images_dir / f"{state_id}.png"))
                image = f"images/{state_id}.png"
            except Exception:
                image = ""
        self.recs[state_id] = {
            "id": state_id, "signature": sig, "url": obs.url, "title": obs.title,
            "image": image, "headings": obs.headings, "elements": obs.elements,
            "path": list(path), "safe": safe, "tried": set(), "first_seen": self.actions_taken,
        }
        self.by_sig[sig] = state_id
        return state_id

    def _click(self, desc: dict) -> bool:
        """Click a control robustly. Prefer a (role, accessible-name) locator, which is
        stable across DOM changes; fall back to the captured CSS path. Returns whether a
        click actually landed."""
        role, name, css = desc.get("role", ""), (desc.get("name") or ""), desc["locator"]
        # Use the role locator only when it uniquely identifies the control; if the name
        # is shared (two "Back" buttons), fall back to the exact CSS path so we click the
        # node we actually recorded rather than an arbitrary .first.
        if role in ROLE_LOCATABLE and name:
            try:
                loc = self.page.get_by_role(role, name=name, exact=True)
                if loc.count() == 1:
                    loc.click(timeout=4000)
                    return True
            except Exception:
                pass
        try:
            self.page.click(css, timeout=4000)
            return True
        except Exception:
            return False

    def _reach(self, rec: dict):
        """Replay a state's discovery path from the start and return the before-frame
        Observation, or None (recording instability) if a step fails or it lands on a
        different state. The path is element descriptors, so replay uses robust clicks."""
        self.page.goto(self.start_url, wait_until="domcontentloaded")
        _settle(self.page)
        for desc in rec["path"]:
            if not self._click(desc):
                self._instability(rec, f"could not replay click on {desc.get('name') or desc['locator']}")
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
            element = next(e for e in rec["safe"] if e["locator"] == locator)
            attempts = rec.setdefault("attempts", {})
            attempts[locator] = attempts.get(locator, 0) + 1
            give_up = attempts[locator] >= MAX_ACTION_ATTEMPTS

            before = self._reach(rec)
            if before is None:
                if give_up:
                    rec["tried"].add(locator)  # stop retrying a path we cannot replay
                continue

            before_sig = rec["signature"]
            if not self._click(element):
                if give_up:
                    rec["tried"].add(locator)
                    # A control we identified but could not actuate (obscured, or not
                    # interactive as a user click). Recorded as a *blocked edge*, not a
                    # functional finding: it is a fact about the control, not an app error.
                    self.transitions.append(Transition(
                        id=f"tr{len(self.transitions) + 1:03d}", source=state_id,
                        action=Action(kind="click",
                                      element_key=f"{element['role']}:{element['name']}",
                                      target=locator),
                        dest=state_id, effect="blocked", changed=False,
                        first_seen=self.actions_taken))
                continue
            rec["tried"].add(locator)  # a click that landed is done, pass or not
            _settle(self.page)
            after = capture(self.page, self.col)
            self.actions_taken += 1

            after_sig = signature(after)
            dest_id = self._register(after, path=rec["path"] + [element])
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
        states = []
        for r in self.recs.values():
            safe_locators = {e["locator"] for e in r["safe"]}
            states.append(State(
                id=r["id"], url=r["url"], signature=r["signature"], title=r["title"],
                image=r.get("image", ""), first_seen=r["first_seen"],
                elements=[Element(key=f"{e['role']}:{e['name']}", role=e["role"],
                                  name=e["name"], kind=e.get("tag", ""), locator=e["locator"],
                                  committing=(e["locator"] not in safe_locators),
                                  href=e.get("href", ""))
                          for e in r["elements"]]))
        return Ontology(
            target={"url": self.start_url, "origin": self.base_origin},
            session={"actions": self.actions_taken, "states": len(states)},
            states=states, transitions=self.transitions,
            findings=dedup_findings(self.findings),
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
        onto = Crawler(page, col, args.url, max_actions=args.max,
                       out_dir=Path(args.out).parent).crawl()
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
