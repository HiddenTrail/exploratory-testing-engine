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

from analyze import analyze
from identity import appearance, signature
from oracles import run_observation_oracles
from perceive import Collector, capture, visual_diff
from safety import action_plans, plan, vetted_actions
from schema import Action, Element, Evidence, Ontology, State, Transition


# A flaky reach/click gets one retry before the action is abandoned, so a transient
# slow load does not silently drop a branch of the graph - but a persistently failing
# control is given up after this many attempts rather than spun on forever.
MAX_ACTION_ATTEMPTS = 2

# When the DOM signature and text say an action changed nothing, a before/after
# screenshot is compared: if this fraction of a downscaled frame moved, the action did
# something visual the DOM could not see (a canvas/map pan or zoom) and is "changed", not
# "dead". Keeps a "dead control" observation honest.
VISUAL_CHANGE_THRESHOLD = 0.02

# Gesture probes tried on every state, at the viewport centre, in addition to the DOM
# controls. They reveal what a click/fill cannot: a map that pans and zooms, a hover
# tooltip/menu. All are non-committing (a wheel "is not destructive on its own", a hover
# commits nothing, a centre drag pans content) - the safe half of the game kit's fuller
# input set. Their effect is judged by the same before/after screenshot diff, since they
# change pixels the DOM cannot see. A drag over content that is really a slider/drag-drop
# could mutate; that residual risk is bounded by the reboot-before-every-action and is
# what the later vetting pass tightens.
_WHEEL_DELTA = 400
_DRAG_OFFSET = (160, 0)
GESTURE_PROBES = (
    ("hover", "hover centre"),
    ("wheel_down", "wheel down"),
    ("wheel_up", "wheel up"),
    ("zoom_in", "ctrl+wheel zoom in"),
    ("zoom_out", "ctrl+wheel zoom out"),
    ("drag", "drag-pan centre"),
)


GESTURE_KINDS = frozenset(kind for kind, _ in GESTURE_PROBES)


def gesture_actions() -> list[dict]:
    """The synthetic gesture-probe actions added to every state. Pure - the viewport
    centre is resolved at actuation time, so this is just the fixed descriptor list."""
    return [{"role": "gesture", "name": label, "tag": "", "type": "",
             "locator": f"__gesture__:{kind}", "href": "",
             "act_kind": kind, "act_value": ""}
            for kind, label in GESTURE_PROBES]

# Roles Playwright's get_by_role can target by accessible name. Addressing a control by
# (role, name) survives DOM reshuffles - async content appearing, siblings inserted -
# far better than a positional CSS path, which silently points at the wrong node once
# the tree around it changes. Covers the clickable controls plus the selection controls
# the safety gate now allows (a view toggle is not a mutation).
ROLE_LOCATABLE = frozenset({
    "button", "link", "tab", "menuitem", "radio", "checkbox", "switch",
    "menuitemradio", "menuitemcheckbox",
})


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
    # A state whose next untried is a real control is preferred over one whose next is a
    # gesture probe, so genuine controls across the whole graph are exercised before the
    # gestures (which every state carries) can crowd out coverage on a tight budget.
    def rank(s):
        first_is_gesture = s["untried"][0].startswith("__gesture__:")
        return (first_is_gesture, len(s["path"]), s["id"])
    nearest = min(candidates, key=rank)
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
                 out_dir: Path | None = None, proposer=None, mutate: bool = False,
                 resume: Ontology | None = None):
        self.page = page
        self.col = collector
        self.start_url = start_url
        self.base_origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        self.max_actions = max_actions
        # Optional model proposer(obs) -> [candidate]. Off by default (None): the crawl is
        # then wholly deterministic. When set (crawl --llm), each new state's DOM controls
        # are supplemented with model-nominated ones that are resolved, gated and tested
        # like any other - the model proposes, the deterministic gate and the app dispose.
        self.proposer = proposer
        # Stage 5b: when True (crawl --mutate, off by default), committing controls that the
        # deterministic vetting pass admits - only reversible query submits (search/filter/
        # sort) - are also actuated. Everything destructive stays refused even then.
        self.mutate = mutate
        # Stage 6 resume/carry: the map a previous run wrote, keyed by signature. A state
        # whose signature is in here is *known on first sight* this run (carried), and after
        # the crawl a drift report says which carried states went missing and which are new.
        self.carried_sigs = {s.signature: s for s in resume.states} if resume else {}
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
        # Each actuable control paired with how to actuate it (click or fill a search
        # box), plus the gesture probes (hover / wheel / zoom / drag) tried on every state.
        actions = [{**e, "act_kind": p.kind, "act_value": p.value}
                   for e, p in action_plans(obs.elements, self.base_origin)]
        if self.proposer:
            llm_actions = self._llm_candidate_actions(obs, actions)
            actions += llm_actions
            obs.elements += llm_actions
        if self.mutate:
            actions += self._mutation_actions(obs.elements)
        actions += gesture_actions()
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
            "path": list(path), "actions": actions,
            "action_locators": {a["locator"] for a in actions},
            "tried": set(), "first_seen": self.actions_taken,
            "carried": sig in self.carried_sigs,   # known before this run reached it
        }
        self.by_sig[sig] = state_id
        return state_id

    def _actuate(self, desc: dict) -> bool:
        """Perform a control's planned action - click, fill, or a gesture probe - and say
        whether it landed."""
        kind = desc.get("act_kind", "click")
        if kind == "fill":
            return self._fill(desc)
        if kind == "submit_search":
            return self._submit_search(desc)
        if kind in GESTURE_KINDS:
            return self._gesture(kind)
        # "click" and a vetted "submit" button both go through the click ladder.
        return self._click(desc)

    def _llm_candidate_actions(self, obs, existing: list[dict]) -> list[dict]:
        """Model-nominated controls, each resolved on the live page and cleared by the
        deterministic safety gate, ready to be tested like any DOM control. A nomination
        that resolves to no unique element, duplicates one already found, or the gate
        refuses is dropped here - so the model can only *add candidates to test*, never
        widen what may be touched. Returns the extra action descriptors (origin 'llm')."""
        known = {(a.get("role"), (a.get("name") or "").lower()) for a in existing}
        out = []
        for cand in self.proposer(obs):
            key = (cand.get("role"), (cand.get("name") or "").lower())
            if key in known:
                continue
            el = self._resolve_candidate(cand)
            if el is None:                       # matched no unique element -> hallucination
                continue
            p = plan(el, self.base_origin)
            if p.kind is None:                   # the read-only gate refuses it
                continue
            known.add(key)
            out.append({**el, "act_kind": p.kind, "act_value": p.value, "origin": "llm"})
        return out

    def _mutation_actions(self, elements: list[dict]) -> list[dict]:
        """Vetted committing controls (only reversible query submits - search/filter/sort)
        added as extra actions when --mutate is on. Each gets a distinct '__mutate__:'
        identity so it coexists with the read-only fill of the same field, and carries its
        real selector in 'act_target'. Everything destructive the vetting pass refuses."""
        out = []
        for e, v in vetted_actions(elements, self.base_origin, enabled=True):
            css = e["locator"]
            out.append({**e, "act_kind": v.kind, "act_value": v.value, "origin": "mutation",
                        "locator": f"__mutate__:{v.kind}:{css}", "act_target": css})
        return out

    def _resolve_candidate(self, cand: dict) -> dict | None:
        """Turn a model nomination (role + name) into a real element descriptor iff it
        matches exactly one control on the page now. No unique match -> None (dropped)."""
        role = (cand.get("role") or "").strip().lower()
        name = (cand.get("name") or "").strip()
        if role not in ROLE_LOCATABLE or not name or '"' in name:
            return None
        try:
            if loc.count() != 1 or not loc.is_enabled():
                return None
            href = ""
            if role == "link":
                try:
                    href = loc.get_attribute("href", timeout=1000) or ""
                except Exception:
                    href = ""
        except Exception:
            return None
        # A role selector string: get_by_role (the click ladder's first, most robust step)
        # actuates it, and page.click accepts it as a fallback too.
        return {"role": role, "name": name, "tag": "", "type": "", "href": href,
                "locator": f'role={role}[name="{name}"]'}

    def _gesture(self, kind: str) -> bool:
        """A non-committing gesture at the viewport centre: hover, wheel, ctrl+wheel zoom,
        or a drag-pan. Returns whether it ran without error."""
        vp = self.page.viewport_size or {"width": 1280, "height": 800}
        cx, cy = vp["width"] // 2, vp["height"] // 2
        try:
            self.page.mouse.move(cx, cy)
            if kind == "wheel_down":
                self.page.mouse.wheel(0, _WHEEL_DELTA)
            elif kind == "wheel_up":
                self.page.mouse.wheel(0, -_WHEEL_DELTA)
            elif kind in ("zoom_in", "zoom_out"):
                self.page.keyboard.down("Control")
                self.page.mouse.wheel(0, -_WHEEL_DELTA if kind == "zoom_in" else _WHEEL_DELTA)
                self.page.keyboard.up("Control")
            elif kind == "drag":
                dx, dy = _DRAG_OFFSET
                self.page.mouse.down()
                self.page.mouse.move(cx + dx, cy + dy, steps=8)
                self.page.mouse.up()
            # "hover" is just the move above.
            return True
        except Exception:
            try:
                self.page.keyboard.up("Control")  # never leave a modifier stuck
                self.page.mouse.up()
            except Exception:
                pass
            return False

    def _click(self, desc: dict) -> bool:
        """Click a control, trying every reasonable way to reach it before giving up -
        the browser transposition of the game kit's "try all the locators". A control the
        ontology *found* should be actuated if it possibly can, so:

        1. a unique (role, accessible-name) locator - stable across DOM reshuffles;
        2. the exact captured CSS path;
        3. scroll it into view, then the CSS path (it may be off-screen);
        4. dispatch a click event straight at the node (bypasses hit-testing, so an
           overlay that intercepts a real pointer does not block it);
        5. a forced click (bypasses the actionability wait).

        Only reached for controls the safety gate already cleared, so trying harder does
        not widen what may be touched - it only makes reaching it more reliable."""
        role, name = desc.get("role", ""), (desc.get("name") or "")
        css = desc.get("act_target") or desc["locator"]
        if role in ROLE_LOCATABLE and name:
            try:
                loc = self.page.get_by_role(role, name=name, exact=True)
                if loc.count() == 1:
                    loc.click(timeout=4000)
                    return True
            except Exception:
                pass
        for attempt in (
            lambda: self.page.click(css, timeout=3000),
            lambda: (self.page.locator(css).scroll_into_view_if_needed(timeout=2000),
                     self.page.click(css, timeout=2000)),
            lambda: self.page.dispatch_event(css, "click"),
            lambda: self.page.click(css, timeout=2000, force=True),
        ):
            try:
                attempt()
                return True
            except Exception:
                continue
        return False

    def _fill(self, desc: dict) -> bool:
        """Type a benign query into a search/filter box - and deliberately do NOT press
        Enter. Enter can submit an enclosing <form> (a POST the gate never vetted, and a
        server write the reboot cannot undo). Live-filter UIs react to the input itself;
        a submit-only search is missed on purpose, the safe read-only choice."""
        css, value = (desc.get("act_target") or desc["locator"]), desc.get("act_value", "test")
        try:
            self.page.fill(css, value, timeout=4000)
            return True
        except Exception:
            return False

    def _submit_search(self, desc: dict) -> bool:
        """A vetted mutation (--mutate only): fill a search/filter box with a benign query
        and press Enter to submit it. Unlike the read-only _fill, this *does* submit - but
        only for a control the deterministic vetting pass confirmed is a reversible,
        idempotent query (a GET-style search), never a data-writing form."""
        css, value = (desc.get("act_target") or desc["locator"]), desc.get("act_value", "test")
        try:
            self.page.fill(css, value, timeout=4000)
            self.page.press(css, "Enter")
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
            if not self._actuate(desc):
                self._instability(rec, f"could not replay action on {desc.get('name') or desc['locator']}")
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

    def _same_origin(self, url: str) -> bool:
        return urlparse(url).netloc == urlparse(self.start_url).netloc

    def _reboot(self) -> None:
        """Return to a clean starting page - the recovery for anything that landed
        somewhere unexpected. (The per-action _reach already reboots before every action,
        so a stray effect never compounds; this is the explicit off-origin case.)"""
        self.page.goto(self.start_url, wait_until="domcontentloaded")
        _settle(self.page)

    def _screenshot_bytes(self):
        try:
            return self.page.screenshot()
        except Exception:
            return None

    def _save_shot(self, data) -> str:
        """Persist an action screenshot (taken on every touch) and return its wiki path."""
        if not (self.images_dir and data):
            return ""
        try:
            self.images_dir.mkdir(parents=True, exist_ok=True)
            name = f"act{self.actions_taken:03d}.png"
            (self.images_dir / name).write_bytes(data)
            return f"images/{name}"
        except Exception:
            return ""

    def _visual_diff(self, before, after):
        """Fraction of a downscaled grayscale frame that changed between two screenshots.
        Delegates to perceive.visual_diff so the crawler and the engine web-GUI adapter
        judge "did nothing" by the same measure."""
        return visual_diff(before, after)

    def _untried(self, rec: dict) -> list[dict]:
        untried = [a for a in rec["actions"] if a["locator"] not in rec["tried"]]
        # Real controls first, gesture probes last (stable sort: False < True).
        return sorted(untried, key=lambda a: a["act_kind"] in GESTURE_KINDS)

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
            element = next(a for a in rec["actions"] if a["locator"] == locator)
            act_kind = element.get("act_kind", "click")
            is_gesture = act_kind in GESTURE_KINDS
            origin = element.get("origin", "")   # "llm" if the model nominated this control
            element_key = f"{element['role']}:{element['name']}"
            attempts = rec.setdefault("attempts", {})
            attempts[locator] = attempts.get(locator, 0) + 1
            give_up = attempts[locator] >= MAX_ACTION_ATTEMPTS

            before = self._reach(rec)
            if before is None:
                if give_up:
                    rec["tried"].add(locator)  # stop retrying a path we cannot replay
                continue

            before_sig = rec["signature"]
            before_png = self._screenshot_bytes()  # for the dead-vs-visual-change check
            if not self._actuate(element):
                if give_up:
                    rec["tried"].add(locator)
                    # A control we identified but could not actuate even after the whole
                    # ladder (obscured / not interactive). Recorded as a *blocked edge*,
                    # not a functional finding: it is a fact about the control, not an app error.
                    self.transitions.append(Transition(
                        id=f"tr{len(self.transitions) + 1:03d}", source=state_id,
                        action=Action(kind=act_kind, element_key=element_key, target=locator,
                                      origin=origin),
                        dest=state_id, effect="blocked", changed=False,
                        first_seen=self.actions_taken))
                continue
            rec["tried"].add(locator)  # an action that landed is done, pass or not
            _settle(self.page)
            after = capture(self.page, self.col)
            self.actions_taken += 1
            action = Action(kind=act_kind, element_key=element_key, target=locator, origin=origin)
            after_png = self._screenshot_bytes()
            shot = self._save_shot(after_png)  # a screenshot on every touch

            # Recovery: if the action left the app (a JS navigation off-origin the gate
            # could not foresee from the element), do not explore off-site - record it and
            # reboot to the start.
            if not self._same_origin(after.url):
                self.transitions.append(Transition(
                    id=f"tr{len(self.transitions) + 1:03d}", source=state_id, action=action,
                    dest="external", effect="external", changed=True,
                    first_seen=self.actions_taken, after_image=shot))
                self._reboot()
                continue

            after_sig = signature(after)

            if is_gesture:
                # A gesture (hover/wheel/zoom/drag) is not a reliably-replayable
                # navigation, so it never mints a state or a discovery-path step: it is
                # recorded as a self-transition on the state it was tried from, its effect
                # judged by signature/text and then the pixel diff. Oracles still run - a
                # gesture can trigger a network error too.
                self.findings.extend(run_observation_oracles(after, state_id, self.actions_taken))
                vdiff = self._visual_diff(before_png, after_png)
                changed = (after_sig != before_sig or appearance(after) != appearance(before)
                           or (vdiff is not None and vdiff > VISUAL_CHANGE_THRESHOLD))
                self.transitions.append(Transition(
                    id=f"tr{len(self.transitions) + 1:03d}", source=state_id, action=action,
                    dest=state_id, effect=("changed" if changed else "dead"), changed=changed,
                    first_seen=self.actions_taken, after_image=shot))
                continue

            dest_id = self._register(after, path=rec["path"] + [element])
            self.findings.extend(run_observation_oracles(after, dest_id, self.actions_taken))

            if after_sig != before_sig:
                effect = "navigate"                          # went to another state
            elif appearance(after) != appearance(before):
                effect = "changed"                           # same state, text/content moved
            else:
                # DOM/text saw nothing - confirm with pixels before calling it dead, so a
                # canvas/map change (invisible to the signature) is not a false "dead".
                vdiff = self._visual_diff(before_png, after_png)
                effect = "changed" if (vdiff is not None and vdiff > VISUAL_CHANGE_THRESHOLD) else "dead"

            self.transitions.append(Transition(
                id=f"tr{len(self.transitions) + 1:03d}", source=state_id, action=action,
                dest=dest_id, effect=effect, changed=(effect != "dead"),
                first_seen=self.actions_taken, after_image=shot))

        return self._build()

    def _carry_observations(self) -> list[Evidence]:
        """Drift between the carried map and this run: carried states that were not reached
        this time, and states new since the carried map. Structural observations, not
        defects - a carried state going missing may be a removed feature or just a branch
        this budget did not reach; the report says which, it does not judge."""
        seen = set(self.by_sig)
        obs = [
            Evidence(kind="carried_state_absent", state_id=s.id,
                     summary=f"{s.id} ({s.title or s.signature[:40]}) was in the carried map "
                             f"but was not reached this run")
            for sig, s in self.carried_sigs.items() if sig not in seen
        ]
        obs += [
            Evidence(kind="new_state", state_id=r["id"],
                     summary=f"{r['id']} was not in the carried map - new since last run")
            for r in self.recs.values() if not r["carried"]
        ]
        return obs

    def _build(self) -> Ontology:
        states = []
        for r in self.recs.values():
            safe_locators = r["action_locators"]
            states.append(State(
                id=r["id"], url=r["url"], signature=r["signature"], title=r["title"],
                image=r.get("image", ""), first_seen=r["first_seen"], carried=r["carried"],
                elements=[Element(key=f"{e['role']}:{e['name']}", role=e["role"],
                                  name=e["name"], kind=e.get("tag", ""), locator=e["locator"],
                                  committing=(e["locator"] not in safe_locators),
                                  href=e.get("href", ""))
                          for e in r["elements"]]))
        session = {"actions": self.actions_taken, "states": len(states)}
        if self.carried_sigs:
            session["resumed_from_states"] = len(self.carried_sigs)
        onto = Ontology(
            target={"url": self.start_url, "origin": self.base_origin},
            session=session,
            states=states, transitions=self.transitions,
            findings=dedup_findings(self.findings),
        )
        onto.observations = analyze(onto)  # deterministic graph oracles over the finished map
        if self.carried_sigs:
            onto.observations += self._carry_observations()   # + resume/carry drift
        return onto


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default="http://localhost:5173/")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--out", default="out/ontology.json")
    ap.add_argument("--llm", action="store_true",
                    help="also let the model nominate interactable controls the DOM scan "
                         "missed (off by default; each is still resolved, safety-gated and "
                         "tested - the crawl stays deterministic and read-only either way).")
    ap.add_argument("--mutate", action="store_true",
                    help="also actuate committing controls the deterministic vetting pass "
                         "admits - only reversible query submits (search/filter/sort); "
                         "destructive controls stay refused. OFF by default (read-only).")
    ap.add_argument("--resume", default="",
                    help="carry a previous run's ontology.json forward: states it mapped are "
                         "known on first sight, and a drift report flags carried states not "
                         "reached this run and states new since it.")
    args = ap.parse_args()

    resume = None
    if args.resume:
        resume = Ontology.load(args.resume)
        print(f"resuming from {args.resume} ({len(resume.states)} carried states)")

    proposer = None
    if args.llm:
        from propose import make_proposer  # imported only when asked, keeps default path model-free
        proposer = make_proposer()
        print("model proposer: " + ("on" if proposer else "unavailable (no engine auth) - deterministic only"))
    if args.mutate:
        print("mutations: ON - vetted, reversible query submits only (search/filter/sort)")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=400 if args.headed else 0)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        col = Collector().attach(page)
        onto = Crawler(page, col, args.url, max_actions=args.max,
                       out_dir=Path(args.out).parent, proposer=proposer, mutate=args.mutate,
                       resume=resume).crawl()
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
