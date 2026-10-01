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
# rather than reimplement. It lives under .experiments/, so put it on the path here (the one
# place this adapter crosses that line), exactly as web-recon's own scripts do.
_WEB_RECON = Path(__file__).resolve().parents[3] / ".experiments" / "web-recon"
if str(_WEB_RECON) not in sys.path:
    sys.path.insert(0, str(_WEB_RECON))

from identity import appearance, control_keys, signature   # noqa: E402
from perceive import _ELEMENTS_JS as ELEMENTS_JS   # noqa: E402
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

# What is on top of a control's centre (issue #130). "clear": the control itself.
# "own": a part of the same control, like a styled radio's circle over its hidden
# input, or its label. "covered": something else, like a cookie notice over the
# paginator, described by its role and name. Playwright's click waits for the
# control to be the thing on top, so before this a covered control cost the full
# 4 s + 3 s of timeouts, and then the forced click landed on the cover, not the
# control: on Juice Shop, "Next page" never paged.
_COVER_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return {state: "clear"};
  el.scrollIntoView({block: "center", inline: "center"});
  const r = el.getBoundingClientRect();
  if (!r.width && !r.height) return {state: "clear"};
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  if (!hit || el.contains(hit) || hit.contains(el)) return {state: "clear"};
  if ([...(el.labels || [])].some((label) => label.contains(hit))) return {state: "own"};
  const box = hit.closest("[role=dialog], [role=alertdialog], [aria-modal=true], [aria-label]") || hit;
  const name = (box.getAttribute("aria-label") || "").slice(0, 40);
  return {state: "covered", by: (box.getAttribute("role") || box.tagName.toLowerCase()) + (name ? ` '${name}'` : "")};
}
"""

# A capture that doesn't match the state it should be gets this many more tries,
# this far apart (issue #131). Juice Shop's paginator renders after the product list
# loads, so a capture taken a moment early was missing two controls and read as a
# different state. A state that still differs after the retries is reported as it is.
_RECAPTURE_TRIES = 2
_RECAPTURE_WAIT_MS = 700

# Fraction of a downscaled frame that must move for a same-signature action to count as
# VARIANT rather than a candidate dead control - the same threshold web-recon's crawler
# uses, so a pixel-only map pan/zoom the signature cannot see is not mistaken for "dead".
_VISUAL_CHANGE_THRESHOLD = 0.02


# A rested page (issue #143, after Spoor's settling): no DOM change for _REST_QUIET_MS
# and no request in flight, waited for at most _REST_MAX_MS. A page that doesn't rest in
# time is read anyway and flagged, rather than hanging the run or being trusted. Our
# last three harness bugs (#123, #130, #131) were all reads taken before the page had
# rested. Websockets don't count as requests in flight (Juice Shop keeps one open), and
# unlike Spoor, an urgent live-region toast isn't waited out: identity already leaves
# those controls out (#124), and Juice Shop's stays up for about 5 s on every load.
_REST_QUIET_MS = 400
_REST_MAX_MS = 8000
_REST_POLL_MS = 100

# Counts DOM mutations on every document the page loads, for _rest.
_MUTATION_COUNTER_JS = """
window.__qesMutations = 0;
new MutationObserver((records) => { window.__qesMutations += records.length; })
  .observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
"""

# Storage keys with a short hash of each value, so a change is visible without any
# value (which may be a token) reaching the Driver.
_STORAGE_JS = r"""
() => {
  const hash = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return h; };
  const read = (store, prefix) => Object.fromEntries(Object.keys(store).map((k) => [prefix + k, hash(store.getItem(k) || "")]));
  try { return {...read(localStorage, "local:"), ...read(sessionStorage, "session:")}; } catch (e) { return {}; }
}
"""
_MAX_SIGNAL_ITEMS = 5


def _signal_diff(before, after, storage_before: dict, storage_after: dict,
                 settled_before: bool, settled_after: bool) -> dict:
    """What an action did, beyond the screen it landed on (issue #143): the console
    errors and failed requests it caused (the Collector is drained by the capture
    before the action, so `after` holds only what came since), storage and cookie keys
    it added, removed or changed, controls that appeared or went, and whether the page
    had rested before and after. Only what changed is included, to keep the prompt
    small; the settled flags are always there."""
    signals = {"settled_before": settled_before, "settled_after": settled_after}
    errors = [c["text"] for c in after.console if c.get("type") in ("error", "pageerror")]
    if errors:
        signals["console_errors"] = errors[:_MAX_SIGNAL_ITEMS]
        signals["console_error_count"] = len(errors)
    failed = [f"{n['method']} {n['url']} -> {n['status'] or n.get('failure', 'failed')}"
              for n in after.network if not n.get("status") or n["status"] >= 400]
    if failed:
        signals["failed_requests"] = failed[:_MAX_SIGNAL_ITEMS]
        signals["failed_request_count"] = len(failed)
    added = sorted(set(storage_after) - set(storage_before))
    removed = sorted(set(storage_before) - set(storage_after))
    changed = sorted(k for k in set(storage_before) & set(storage_after) if storage_before[k] != storage_after[k])
    for key, keys in (("storage_added", added), ("storage_removed", removed), ("storage_changed", changed)):
        if keys:
            signals[key] = keys[:_MAX_SIGNAL_ITEMS]
    controls_before, controls_after = set(control_keys(before)), set(control_keys(after))
    if controls_after - controls_before:
        signals["controls_added"] = sorted(controls_after - controls_before)[:_MAX_SIGNAL_ITEMS]
    if controls_before - controls_after:
        signals["controls_removed"] = sorted(controls_before - controls_after)[:_MAX_SIGNAL_ITEMS]
    return signals


class Session:
    def __init__(self, reference: ref_mod.Reference, base_url: str, headed: bool):
        from playwright.sync_api import sync_playwright
        self.reference = reference
        self.base_url = base_url
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed, slow_mo=300 if headed else 0)
        self._context = None
        self._open_fresh_page()
        self.seen_signatures: set[str] = set()   # signatures first sighted this run
        self.last_covered_by = ""                  # what was on top of the last control clicked
        self.entry_signature = ""
        atexit.register(self.close)

    def close(self) -> None:
        for shut in (getattr(self, "_context", None), getattr(self, "_browser", None), getattr(self, "_pw", None)):
            try:
                (shut.close if hasattr(shut, "close") else shut.stop)()
            except Exception:
                pass

    # ---- primitives ------------------------------------------------------------------

    def _open_fresh_page(self) -> None:
        """A new browser context, so no cookies, storage or cache carry over from the
        previous one. Juice Shop, for one, remembers a dismissed welcome banner or cookie
        message in a cookie, and on a reused page every later restart then lands on a
        different start screen (issue #117). The Collector is re-attached, because it
        listens on one page."""
        old = self._context
        self._context = self._browser.new_context(viewport={"width": 1280, "height": 900})
        try:
            self._context.add_init_script(_MUTATION_COUNTER_JS)
        except Exception:
            pass
        self.page = self._context.new_page()
        self.col = Collector().attach(self.page)
        self._inflight: set = set()
        self.page.on("request", lambda r: self._inflight.add(id(r)))
        self.page.on("requestfinished", lambda r: self._inflight.discard(id(r)))
        self.page.on("requestfailed", lambda r: self._inflight.discard(id(r)))
        if old is not None:
            try:
                old.close()
            except Exception:
                pass

    def _reboot(self) -> None:
        """Back to the start as a first-time visitor: a fresh session, then the base URL."""
        self._open_fresh_page()
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        self.last_rest = self._rest()

    def _rest(self) -> bool:
        """Wait until the page has rested (see _REST_QUIET_MS). True if it did, False if
        _REST_MAX_MS ran out first; the read that follows is then flagged unsettled."""
        start = time.time()
        quiet_since, last = start, None
        while True:
            try:
                mutations = self.page.evaluate("window.__qesMutations ?? -1")
            except Exception:
                mutations = -1
            now = time.time()
            if mutations != last or getattr(self, "_inflight", None):
                quiet_since, last = now, mutations
            elif (now - quiet_since) * 1000 >= _REST_QUIET_MS:
                return True
            if (now - start) * 1000 >= _REST_MAX_MS:
                return False
            self.page.wait_for_timeout(_REST_POLL_MS)

    def _storage(self) -> dict:
        try:
            keys = dict(self.page.evaluate(_STORAGE_JS) or {})
        except Exception:
            keys = {}
        try:
            keys.update({f"cookie:{c['name']}": hash(c.get("value", "")) for c in self._context.cookies()})
        except Exception:
            pass
        return keys

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
        self.last_covered_by = ""
        if role in TEXT_ROLES:
            return self._fill(role, name, css)
        # Something on top of the control. A part of the control itself (a styled
        # radio's circle): a forced click lands on it, which presses the control. Anything
        # else gets up to a second to go away (a dismissed notice fades out); if it's
        # still there, a forced click would land on IT, not the control, so the click
        # event goes to the control directly and the result says what was in the way,
        # since a user would have had to move it first. Either way, no waiting out the
        # ladder's 4 s + 3 s of timeouts. The live selector, not the saved one, which
        # can be stale (#123) and would point this at the wrong element.
        target = self._live_locator(role, name) or css
        cover = self._cover(target)
        for _ in range(5):
            if cover.get("state") != "covered":
                break
            self.page.wait_for_timeout(200)
            cover = self._cover(target)
        try:
            if cover.get("state") == "own":
                self.page.click(target, timeout=2000, force=True)
                return True
            if cover.get("state") == "covered":
                self.page.dispatch_event(target, "click", timeout=2000)
                self.last_covered_by = cover.get("by", "")
                return True
        except Exception:
            pass
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
        # Next the control's selector as it stands now, found by web-recon's own role and
        # name: the saved selector is positional, and on Juice Shop a toast in the same
        # overlay container shifts it (issue #123). Playwright's role lookup above can
        # miss it, because it names by the accessibility tree ("Help getting started",
        # where web-recon's DOM name is "school Help getting started").
        live = self._live_locator(role, name)
        if live and live != css:
            try:
                self.page.click(live, timeout=3000)
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

    def _cover(self, css: str) -> dict:
        if not css:
            return {"state": "clear"}
        try:
            return self.page.evaluate(_COVER_JS, css) or {"state": "clear"}
        except Exception:
            return {"state": "clear"}

    def _live_locator(self, role: str, name: str) -> str:
        """The current selector of the one control on the page with this role and name, as
        web-recon's capture names it; empty if there is none or more than one. Reads the
        element list only, not a full capture, which would drain the console and network
        log the oracle reads."""
        if not name:
            return ""
        try:
            found = [e["locator"] for e in self.page.evaluate(ELEMENTS_JS)
                     if e.get("role") == role and e.get("name") == name]
        except Exception:
            return ""
        return found[0] if len(found) == 1 else ""

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
        start = self.reference._by_id.get(self.reference.entry(), {}).get("signature", "")
        self.entry_signature = signature(self._capture_expecting(start))
        self.seen_signatures.add(self.entry_signature)
        return self.entry_signature

    def act(self, state_id: str, control_key: str) -> dict:
        """Reach `state_id` by replaying its carried path, actuate `control_key`, and report
        the whole transition classified against the carried map. Recovery (a reboot) is part
        of the operation when the action lands somewhere new, so the next test starts clean."""
        plan = self.reference.plan_for(state_id, control_key)
        self._reboot()
        replayed = True
        for step in plan["path"]:
            replayed = self._actuate(step)
            self.last_rest = self._rest()
            if not replayed:
                break
        settled_before = self.last_rest

        before = self._capture_expecting(self.reference._by_id.get(state_id, {}).get("signature", ""))
        storage_before = self._storage()
        before_sig = signature(before)
        before_png = self._shot()
        reached = replayed and self.reference._by_id.get(state_id, {}).get("signature") == before_sig

        # The click and the settle are timed separately: the click ladder's fallbacks can
        # take seconds on their own, and counting them as the page's settle time made our
        # retries look like a slow app (issue #122).
        t0 = time.time()
        sent = reached and self._actuate(plan["target"])
        t1 = time.time()
        settled_after = self._rest()
        click = round(t1 - t0, 2)
        settle = round(time.time() - t1, 2)

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
            # The stored fingerprint of the state this test was cast against, so the
            # engine can tell "started where it meant to" from "landed elsewhere".
            "intended_before": self.reference._by_id.get(state_id, {}).get("signature", ""),
            "screen_after": after_sig,
            "screen_was": screen_was,
            "same_appearance": (screen_was == "same_screen" and not moved),
            "was_measured_before": self.reference.is_known(after_sig),
            "first_sight_this_run": first_sight,
            "settle": settle,
            "click": click,
            "verdict": "sent" if sent else "not_actuated",
        }
        if sent and self.last_covered_by:
            result["covered_by"] = self.last_covered_by
        result["signals"] = _signal_diff(before, after, storage_before, self._storage(), settled_before, settled_after)
        self.seen_signatures.add(after_sig)
        if screen_was == "new_screen":
            recovered = self.recover()
            result["recovered_to"] = recovered
            result["recovered_ok"] = recovered == self.entry_signature
        return result

    def recover(self) -> str:
        self._reboot()
        return signature(self._capture_expecting(self.entry_signature))

    def _capture_expecting(self, expected: str):
        """A capture of the page, taken again (up to _RECAPTURE_TRIES more times) while
        it doesn't match `expected`, because a page still loading reads as another
        state. Returns the last capture either way."""
        obs = capture(self.page, self.col)
        for _ in range(_RECAPTURE_TRIES):
            if not expected or signature(obs) == expected:
                break
            self.page.wait_for_timeout(_RECAPTURE_WAIT_MS)
            obs = capture(self.page, self.col)
        return obs


# ---- module singleton + readiness probe ----------------------------------------------

_SESSION: Session | None = None


def _resolve_ontology_path() -> Path:
    raw = os.environ.get(_ONTOLOGY_ENV, "")
    if not raw:
        raise SystemExit(
            f"The web-GUI adapter needs a carried reference. Set {_ONTOLOGY_ENV} to a "
            f"web-recon ontology.json, produced by the deterministic recon first:\n"
            f"    cd .experiments/web-recon && python crawl.py <url> --out out/ontology.json\n"
            f"    set {_ONTOLOGY_ENV}=...\\.experiments\\web-recon\\out\\ontology.json")
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
            f".experiments/web-recon/crawl.py, whose safety flags this adapter relies on.")
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
