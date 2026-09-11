"""The live browser session for the web-GUI adapter - the only browser-touching module,
and the analog of clash_royale/session.py.

It reuses web-recon's *perception* (a live page -> one normalised Observation) and its
*identity* (a state is its URL route + control skeleton + landmark headings; body text /
map position is a variant), so the adapter sees the app exactly as the deterministic
crawler did. It adds only what a driven, one-action-at-a-time run needs: reach a state by
replaying the carried path, actuate one control, classify where it landed against the
carried map, and reboot to recover.

A single browser is launched lazily and kept for the whole run (the checkpoint loop has no
teardown hook; the process closing ends it, and atexit closes it cleanly). Nothing here is
committing: the reference only ever offers controls the recon's safety gate cleared, so the
Driver cannot name anything that mutates.
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path

# web-recon is the source of truth for perception, identity and the safety gate; reuse it
# rather than reimplement. It lives under experiments/, so put it on the path here (the one
# place this adapter crosses that line), exactly as web-recon's own scripts do.
_WEB_RECON = Path(__file__).resolve().parents[3] / "experiments" / "web-recon"
if str(_WEB_RECON) not in sys.path:
    sys.path.insert(0, str(_WEB_RECON))

from identity import appearance, signature       # noqa: E402
from perceive import Collector, capture, visual_diff  # noqa: E402
from safety import SEARCH_PROBE, TEXT_ROLES        # noqa: E402

from engine.adapters.web_gui import reference as ref_mod  # noqa: E402

# Roles Playwright can target by (role, accessible name) - the robust first step of the
# actuation ladder, same set web-recon's crawler uses.
_ROLE_LOCATABLE = frozenset({
    "button", "link", "tab", "menuitem", "radio", "checkbox", "switch",
    "menuitemradio", "menuitemcheckbox",
})

# Where the carried reference (a web-recon ontology.json) lives, and where the SUT is.
_ONTOLOGY_ENV = "WEB_GUI_ONTOLOGY"
_URL_ENV = "WEB_GUI_URL"
_HEADED_ENV = "WEB_GUI_HEADED"

# Fraction of a downscaled frame that must move for a same-signature action to count as
# VARIANT rather than a candidate dead control - the same threshold web-recon's crawler
# uses, so a pixel-only map pan/zoom the signature cannot see is not mistaken for "dead".
_VISUAL_CHANGE_THRESHOLD = 0.02


def _settle(page, quiet_ms: int = 2000, floor_ms: int = 350) -> None:
    """Wait for the page to go quiet, then a short floor. networkidle is capped low
    (quiet_ms): a driven run does many settles (reboot, each path step, after the action),
    and on a live-traffic app - streaming map tiles, polling - the page never truly idles,
    so a long cap just burns wall-clock every time (~6s each was the measured cost). A
    client-side effect (zoom/pan/filter) renders within the floor; the cap only bites when
    real traffic is in flight, and then briefly."""
    try:
        page.wait_for_load_state("networkidle", timeout=quiet_ms)
    except Exception:
        pass
    page.wait_for_timeout(floor_ms)


class Session:
    def __init__(self, reference: ref_mod.Reference, base_url: str, headed: bool):
        from playwright.sync_api import sync_playwright
        self.reference = reference
        self.base_url = base_url
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed, slow_mo=300 if headed else 0)
        self.page = self._browser.new_page(viewport={"width": 1280, "height": 900})
        self.col = Collector().attach(self.page)
        self.seen_signatures: set[str] = set()   # signatures first sighted this run
        self.entry_signature = ""
        atexit.register(self.close)

    def close(self) -> None:
        for shut in (getattr(self, "_browser", None), getattr(self, "_pw", None)):
            try:
                (shut.close if hasattr(shut, "close") else shut.stop)()
            except Exception:
                pass

    # ---- primitives ------------------------------------------------------------------

    def _reboot(self) -> None:
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        _settle(self.page)

    def _shot(self):
        try:
            return self.page.screenshot()
        except Exception:
            return None

    def _actuate(self, step: dict) -> bool:
        """Actuate one control the way the recon's safety gate classified it: a text/search
        box is *filled* with a benign query (only search/filter boxes reach here - the gate
        marks any other text field committing, so it never enters the action space), and
        everything else is *clicked*. Clicking a search box instead of filling it merely
        focuses it and looks like a dead control - the false reading this exists to avoid."""
        role, name, css = step.get("role", ""), step.get("name", ""), step.get("locator", "")
        if role in TEXT_ROLES:
            return self._fill(role, name, css)
        # Click ladder: a unique (role, name) locator first, then the exact selector, then a
        # forced click - the compact form of web-recon's ladder.
        if role in _ROLE_LOCATABLE and name:
            try:
                loc = self.page.get_by_role(role, name=name, exact=True)
                if loc.count() == 1:
                    loc.click(timeout=4000)
                    return True
            except Exception:
                pass
        for attempt in (lambda: self.page.click(css, timeout=3000),
                        lambda: self.page.click(css, timeout=2000, force=True)):
            try:
                attempt()
                return True
            except Exception:
                continue
        return False

    def _fill(self, role: str, name: str, css: str, value: str = SEARCH_PROBE) -> bool:
        """Type a benign query into a search/filter box - and deliberately NOT press Enter,
        matching the read-only recon: a live-filter reacts to the input itself, a submit-only
        search is missed on purpose rather than risk submitting a form the gate never vetted."""
        if name:
            try:
                loc = self.page.get_by_role(role, name=name, exact=True)
                if loc.count() == 1:
                    loc.fill(value, timeout=4000)
                    return True
            except Exception:
                pass
        try:
            self.page.fill(css, value, timeout=4000)
            return True
        except Exception:
            return False

    def _classify(self, before_sig: str, after_sig: str) -> str:
        if after_sig == before_sig:
            return "same_screen"
        if after_sig in self.reference.known_signatures or after_sig in self.seen_signatures:
            return "known_screen"
        return "new_screen"

    # ---- the one operation the loop drives -------------------------------------------

    def baseline(self) -> str:
        """Reboot to the start and record the entry signature; the run's ground truth."""
        self._reboot()
        self.entry_signature = signature(capture(self.page, self.col))
        self.seen_signatures.add(self.entry_signature)
        return self.entry_signature

    def act(self, state_id: str, control_key: str) -> dict:
        """Reach `state_id` by replaying its carried path, actuate `control_key`, and report
        the whole transition classified against the carried map. Recovery (a reboot) is part
        of the operation when the action lands somewhere new, so the next test starts clean."""
        plan = self.reference.plan_for(state_id, control_key)
        self._reboot()
        replayed = all(self._actuate(step) and (_settle(self.page) or True) for step in plan["path"])

        before = capture(self.page, self.col)
        before_sig = signature(before)
        before_png = self._shot()
        reached = replayed and self.reference._by_id.get(state_id, {}).get("signature") == before_sig

        t0 = time.time()
        sent = reached and self._actuate(plan["target"])
        _settle(self.page)
        settle = round(time.time() - t0, 2)

        after = capture(self.page, self.col)
        after_sig = signature(after)
        after_png = self._shot()
        screen_was = self._classify(before_sig, after_sig)
        first_sight = after_sig not in self.seen_signatures
        # NONE vs VARIANT: same signature, but did the body text OR the pixels still move?
        # The pixel check catches a canvas pan/zoom the signature and text cannot see, so a
        # live map control is not reported to the Driver as a dead control.
        vd = visual_diff(before_png, after_png)
        moved = (appearance(after) != appearance(before)
                 or (vd is not None and vd > _VISUAL_CHANGE_THRESHOLD))

        result = {
            "action": f"{state_id} :: {control_key}",
            "reached_target_state": reached,
            "screen_before": before_sig,
            "screen_after": after_sig,
            "screen_was": screen_was,
            "same_appearance": (screen_was == "same_screen" and not moved),
            "was_measured_before": self.reference.is_known(after_sig),
            "first_sight_this_run": first_sight,
            "settle": settle,
            "verdict": "sent" if sent else "not_actuated",
        }
        self.seen_signatures.add(after_sig)
        if screen_was == "new_screen":
            recovered = self.recover()
            result["recovered_to"] = recovered
            result["recovered_ok"] = recovered == self.entry_signature
        return result

    def recover(self) -> str:
        self._reboot()
        return signature(capture(self.page, self.col))


# ---- module singleton + readiness probe ----------------------------------------------

_SESSION: Session | None = None


def _resolve_ontology_path() -> Path:
    raw = os.environ.get(_ONTOLOGY_ENV, "")
    if not raw:
        raise SystemExit(
            f"The web-GUI adapter needs a carried reference. Set {_ONTOLOGY_ENV} to a "
            f"web-recon ontology.json, produced by the deterministic recon first:\n"
            f"    cd experiments/web-recon && python crawl.py <url> --out out/ontology.json\n"
            f"    set {_ONTOLOGY_ENV}=...\\experiments\\web-recon\\out\\ontology.json")
    path = Path(raw)
    if not path.is_file():
        raise SystemExit(f"{_ONTOLOGY_ENV} points at {path}, which does not exist.")
    return path


def live() -> Session:
    if _SESSION is None:
        raise SystemExit("The web-GUI session is not ready - check_ready must run first.")
    return _SESSION


def valid_pairs() -> set:
    """The (state, control) pairs the Driver may name, from the live reference - empty
    before the session is ready, so validation degrades to shape-only rather than raising."""
    return _SESSION.reference.pairs() if _SESSION is not None else set()


def check_ready(adapter) -> None:
    """Load the carried reference, launch the browser, and confirm the SUT is up and on the
    mapped entry state before anything is spent. Raises SystemExit with an actionable
    message rather than returning a flag - a run against a SUT that isn't there costs API
    calls to discover otherwise."""
    global _SESSION
    reference = ref_mod.load(_resolve_ontology_path())
    # Fail closed on a file that is not a web-recon ontology: its elements would lack the
    # 'committing' safety flag, and while the catalogue now defaults such elements to
    # committing (excluded), rejecting a foreign file up front is clearer than a run that
    # silently finds no controls. A canonical recon writes schema "web-recon/<n>".
    if not reference.schema.startswith("web-recon"):
        raise SystemExit(
            f"{_ONTOLOGY_ENV} does not look like a web-recon ontology (schema="
            f"{reference.schema or 'absent'!r}). Point it at one produced by "
            f"experiments/web-recon/crawl.py, whose safety flags this adapter relies on.")
    base_url = os.environ.get(_URL_ENV) or reference.base_url
    if not base_url:
        raise SystemExit(f"No base URL: the carried ontology has no target.url and {_URL_ENV} is unset.")
    if not reference.pairs():
        raise SystemExit("The carried reference has no safe (state, control) pairs to test. "
                         "Run the recon against a richer app, or check the ontology.")

    headed = os.environ.get(_HEADED_ENV, "") not in ("", "0", "false", "False")
    session = Session(reference, base_url, headed)
    try:
        entry_sig = session.baseline()
    except Exception as e:
        session.close()
        raise SystemExit(f"Could not reach the SUT at {base_url}: {e!r}. Is it running?")

    expected = reference._by_id.get(reference.entry(), {}).get("signature", "")
    baseline_note = f"Start state {reference.entry()} confirmed ({entry_sig[:50]}...)."
    if expected and entry_sig != expected:
        # Not fatal: the app may have drifted since the recon. Say so loudly - every
        # known/new_screen reading below is relative to a map that no longer starts here.
        baseline_note = (
            f"WARNING: the SUT's entry state does not match the carried map. Expected "
            f"{expected[:60]}..., got {entry_sig[:60]}.... The app may have changed since "
            f"the recon; known/new_screen readings are relative to the carried map.")
        print(baseline_note)

    # onboarding_extra is merged into the Driver's evidence (engine/loop._base_evidence) and
    # rendered in the report, so the carried map - the action space - is filled in here, the
    # one moment the reference is loaded. The dict is mutated, not reassigned (the adapter is
    # frozen); same pattern as clash_royale's preflight/baseline.
    adapter.onboarding_extra["carried_map"] = reference.driver_briefing()
    adapter.onboarding_extra["baseline"] = baseline_note
    _SESSION = session
