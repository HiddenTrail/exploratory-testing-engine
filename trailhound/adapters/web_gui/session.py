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
import functools
import json
import os
import re
import shutil
from collections import Counter
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit
from pathlib import Path

# web-recon is the source of truth for perception, identity and the safety gate; reuse it
# rather than reimplement. It lives under .experiments/, so put it on the path here (the one
# place this adapter crosses that line), exactly as web-recon's own scripts do.
_WEB_RECON = Path(__file__).resolve().parents[3] / ".experiments" / "web-recon"
if str(_WEB_RECON) not in sys.path:
    sys.path.insert(0, str(_WEB_RECON))

from identity import appearance, control_keys, impersonal, signature   # noqa: E402
from perceive import _ELEMENTS_JS as ELEMENTS_JS   # noqa: E402
from perceive import Collector, capture, visual_diff  # noqa: E402
from safety import SEARCH_PROBE, TEXT_ROLES        # noqa: E402
from safety import plan as gate_plan                # noqa: E402
from safety import safe_actions                    # noqa: E402

from trailhound.adapters.web_gui import careful as careful_mod  # noqa: E402
from trailhound.adapters.web_gui import reference as ref_mod  # noqa: E402
from trailhound.adapters.web_gui import to_context  # noqa: E402
from trailhound.ontology.oracle_creator import load_context, load_vocabulary  # noqa: E402

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
# A saved Playwright session (context.storage_state(): cookies and storage) every test
# starts from, for example logged in (issue #154). Each test still gets a fresh context,
# just loaded from this file instead of empty, so results stay attributable. The file
# holds live auth cookies: keep it in the gitignored .sessions/, and it never reaches a
# prompt or a report (only its name does).
_SESSION_ENV = "WEB_GUI_SESSION"
# A path on the product that answers below 400 only for a session the server still accepts
# (issue #227), e.g. /profile on Juice Shop. Optional: without it, only expiry dates are checked.
_SESSION_CHECK_ENV = "WEB_GUI_SESSION_CHECK"
# How a test may start (issue #249). "same_tab": the saved session as it was, sessionStorage
# included. "new_tab": what a new tab of that logged-in browser gets, cookies and
# localStorage but empty sessionStorage. A logged-in Juice Shop user's new tab lost the
# basket, and only a person found it, because every test started as the same tab.
START_AS = ("same_tab", "new_tab")
# What one step of a test does on the live page (#310). A test starts from a route on the
# site or a screen the map knows, then runs up to MAX_STEPS of these on whatever is there.
STEP_KINDS = ("click", "fill", "select", "goto", "back")
MAX_STEPS = 6
# How many of the page's controls a result lists, so the Driver can act on what it sees.
_PAGE_CONTROLS_SHOWN = 40


def load_session_file(path) -> str:
    """The path of a valid session file, or SystemExit saying what's wrong with it. A
    missing or malformed file fails the run loudly, as Spoor's --session does, rather than
    quietly starting every test logged out."""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"{_SESSION_ENV} points at {p}, which does not exist. Save a session first (#155).")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"{_SESSION_ENV} file {p} isn't valid JSON: {e}")
    if not (isinstance(data, dict) and isinstance(data.get("cookies"), list) and isinstance(data.get("origins"), list)):
        raise SystemExit(f"{_SESSION_ENV} file {p} isn't a Playwright session (it needs 'cookies' and 'origins' "
                         "lists, as context.storage_state() writes).")
    return str(p)


# Names that look like a login credential, for a cookie or storage entry (issue #227).
_CREDENTIAL_NAME = re.compile(r"token|session|auth|jwt|sid|login|bearer", re.I)
# A session that expires sooner than this from the start of a run probably won't last it.
_SESSION_SOON_S = 30 * 60


def _jwt_exp(value: str) -> float | None:
    """The `exp` claim of a value that is a JWT, or None (not a JWT, or no expiry)."""
    import base64
    parts = value.split(".") if isinstance(value, str) else []
    if len(parts) != 3 or not value.startswith("eyJ"):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return float(payload["exp"]) if isinstance(payload, dict) and "exp" in payload else None
    except (ValueError, TypeError):
        return None


def session_expiry(path, now: float) -> dict:
    """The credentials in a session file that have expired, or will within the run's first
    half hour, by name only (issue #227). A credential is a cookie or storage entry whose
    name looks like one, or whose value is a JWT. Its expiry is the cookie's date or the
    JWT's `exp`. Found in the milestone run: the Juice Shop token cookie had expired
    overnight, the browser dropped it, and the token left in localStorage kept the page
    looking logged in while the server answered 500, which the engine reported as a bug."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    found = []   # (name, expires at)
    for c in data.get("cookies", []):
        exp = _jwt_exp(c.get("value", ""))
        if c.get("expires", -1) > 0 and (_CREDENTIAL_NAME.search(c.get("name", "")) or exp is not None):
            found.append((f"cookie {c['name']}", float(c["expires"])))
        if exp is not None:
            found.append((f"cookie {c['name']} (its JWT)", exp))
    for origin in data.get("origins", []):
        for item in origin.get("localStorage", []) + origin.get("sessionStorage", []):
            exp = _jwt_exp(item.get("value", ""))
            if exp is not None:
                found.append((f"storage {item['name']} (its JWT)", exp))
    return {"expired": sorted(n for n, t in found if t <= now),
            "soon": sorted(n for n, t in found if now < t <= now + _SESSION_SOON_S)}


def session_check_path() -> str:
    """WEB_GUI_SESSION_CHECK, or "" if unset. SystemExit if it isn't a path on the product
    (issue #243): Git Bash turns "/profile" into "C:/Program Files/Git/profile", Juice Shop
    answered 200 for that made-up path, and the check passed without checking anything."""
    value = os.environ.get(_SESSION_CHECK_ENV, "")
    if value and (not value.startswith("/") or value.startswith("//") or ":" in value.split("?")[0]):
        raise SystemExit(
            f"{_SESSION_CHECK_ENV}={value!r} isn't a path on the product, like /profile. In Git Bash, "
            f"MSYS_NO_PATHCONV=1 stops it rewriting the path.")
    return value


def check_session_fresh(path, now: float) -> str | None:
    """SystemExit if a credential in the session has expired, since every test would then
    run as a half-logged-in user and report the server's refusals as bugs. Returns a
    warning if one expires soon, else None."""
    expiry = session_expiry(path, now)
    if expiry["expired"]:
        raise SystemExit(
            f"The saved session {session_name(path)!r} has expired ({', '.join(expiry['expired'])}). The page may "
            "still look logged in, but the server won't accept it, so tests would report its refusals as bugs. "
            "Save a fresh session (python -m trailhound.adapters.web_gui.save_session).")
    if expiry["soon"]:
        return (f"WARNING: the saved session {session_name(path)!r} expires within {_SESSION_SOON_S // 60} minutes "
                f"({', '.join(expiry['soon'])}). Tests after that will run half logged in.")
    return None


def session_storage_script(path) -> str | None:
    """An init script that puts a saved session's sessionStorage back (issue #228), or
    None if it saved none. Playwright's storage_state can't restore sessionStorage, so
    this runs before the app's own scripts on every page. It only fills an empty
    sessionStorage, so a new tab starts where the saved one was, and whatever the app
    writes after that isn't overwritten on the next navigation. Values go in as a JSON
    literal, so none can break out of the script."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    by_origin = {o["origin"]: [[e["name"], e["value"]] for e in o.get("sessionStorage", [])]
                 for o in data.get("origins", []) if o.get("sessionStorage")}
    if not by_origin:
        return None
    return ("(() => { const saved = " + json.dumps(by_origin) + "[location.origin];"
            " if (!saved) return;"
            " try { if (sessionStorage.length) return;"
            " for (const [k, v] of saved) sessionStorage.setItem(k, v); } catch (e) {} })();")


def session_name(path) -> str:
    """What a session is called in the Driver's evidence, the report and the map: the file
    name without its extension, never its contents."""
    return Path(path).stem if path else ""

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
  // Described so the Driver can tell covers apart (issue #150: on Juice Shop every
  // open menu's transparent backdrop came out as a bare "div"): the role, or the tag
  // with its id and first two classes, plus its accessible name, or for a label,
  // button or link its short text. A bare wrapper is described by the nearest
  // ancestor (up to 3 levels) that has an id, a class or a role.
  const describe = (e) => {
    const tag = e.tagName.toLowerCase(), role = e.getAttribute("role");
    // Classes with digits are skipped: frameworks generate them (Angular's ng-tns-c21-12)
    // and they change from build to build, so they'd make a cover look new each run.
    const classes = [...e.classList].filter((c) => !/\d/.test(c)).slice(0, 2);
    const what = role || tag + (e.id ? "#" + e.id : "") + classes.map((c) => "." + c).join("");
    // aria-labelledby too: dialogs are often named by their title that way (Copilot on #166).
    const labelledBy = (e.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)
      .map((id) => (document.getElementById(id) || {}).textContent || "").join(" ").trim().replace(/\s+/g, " ");
    const named = (e.getAttribute("aria-label") || labelledBy).slice(0, 40)
      || (["label", "button", "a"].includes(tag) ? (e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30) : "");
    return what + (named ? ` '${named}'` : "");
  };
  let box = hit.closest("[role=dialog], [role=alertdialog], [aria-modal=true], [aria-label], [aria-labelledby]");
  if (!box) {
    box = hit;
    for (let i = 0; i < 3 && box.parentElement && !box.id && !box.classList.length && !box.getAttribute("role"); i++)
      box = box.parentElement;
  }
  return {state: "covered", by: describe(box)};
}
"""

# The product whose context file holds earlier runs' discoveries (issue #159): the same
# WEB_GUI_PRODUCT that picks the seeded oracle.
_PRODUCT_ENV = "WEB_GUI_PRODUCT"
# Videos of the tests (#286), on unless WEB_GUI_VIDEO=off. They show whatever the
# logged-in page shows, so they follow the screenshot rules: kept with the run's other
# files, never committed and never sent to a model. Not Playwright traces: those hold
# cookies and tokens.
_VIDEO_ENV = "WEB_GUI_VIDEO"
# Big enough to read the page. A test of about 10 s came to just under 0.5 MB.
_VIDEO_SIZE = {"width": 960, "height": 675}


def video_on() -> bool:
    return os.environ.get(_VIDEO_ENV, "").strip().lower() != "off"
# At most this many earlier discoveries are checked at the start of a run, the most often
# reached first. Each costs one replay, a few seconds, and no model call.
_MAX_EARLIER_DISCOVERIES = 20

# A discovered screen joins the run's map (issue #158) only if it's at most this many
# steps from the start, so a chain of discoveries can't wander off indefinitely.
_MAX_DISCOVERY_STEPS = 6

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
window.__trailhoundMutations = 0;
new MutationObserver((records) => { window.__trailhoundMutations += records.length; })
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


# A state is watched idle once per run, to learn what changes on its own (polling,
# timers, analytics, a carousel): _NOISE_SAMPLES looks, _NOISE_SAMPLE_MS apart. The
# signal audit on #146 found PrestaShop's home page carousel, which turns about every
# 5 s, reported as an action's trusted effect, so the watch covers about 6 s. See
# _signal_diff.
_NOISE_SAMPLES = 3
_NOISE_SAMPLE_MS = 2000


def _request_key(r: dict) -> str:
    """A request without its query or fragment, so a poll with a changing timestamp
    matches itself."""
    return f"{r['method']} {urlsplit(r['url'])._replace(query='', fragment='').geturl()}"


def _console_key(text: str) -> str:
    return re.sub(r"\d+", "#", text or "")[:200]


def _own_request(r: dict, origin: str) -> bool:
    """Whether a request is the product's own business: to its origin, or to a host
    with no dot that isn't localhost. The second is a malformed URL in the product's
    page, not a third party: PrestaShop requests http://modules/... on every load
    (a broken relative URL) and the first version of this rule called that third-party
    (#146 audit)."""
    request, product = urlsplit(r["url"]), urlsplit(origin)
    # An exact origin match: a prefix check let https://example.com.evil/ pass for
    # https://example.com, and :80801 for :8080 (Copilot on #152).
    default_ports = {"http": 80, "https": 443}
    try:
        if ((request.scheme, request.hostname, request.port or default_ports.get(request.scheme))
                == (product.scheme, product.hostname, product.port or default_ports.get(product.scheme))):
            return True
    except ValueError:   # a port urlsplit can't read isn't the product's origin
        return False
    host = request.hostname or ""
    return bool(host) and "." not in host and ":" not in host and host != "localhost"


def _signal_diff(before, after, requests: list[dict], storage_before: dict, storage_after: dict,
                 settled_before: bool, settled_after: bool, noise: dict, origin: str,
                 sent: bool = True) -> tuple[dict, dict]:
    """What an action did beyond the screen it landed on (issue #143), split by how far
    it can be trusted. Returns (signals, weak).

    A signal is only trusted, so usable as a fact, if it passes every check; anything
    else goes to `weak` as a hint. Background traffic, timers and third-party calls make
    a raw before/after diff look like evidence when it isn't:
    - requests count only if they started after the action (`requests` is already
      filtered to those), and are trusted only on the product's own origin
    - console errors, requests and storage keys that also changed while the state sat
      idle (`noise`, see Session._idle_noise) are the page's own background, not the
      action's effect
    - nothing read from a page that hadn't rested is trusted, and nothing at all when
      the action wasn't sent (the path drifted or the click failed): whatever changed
      then isn't the action's effect
    - controls that also came and went while the state sat idle (a carousel) are noise
    Screenshots are never a signal: pixels move with animations, cursors and fonts.
    The settled flags are always in `signals`; everything else only if it changed."""
    signals = {"settled_before": settled_before, "settled_after": settled_after}
    weak: dict = {}

    def put(key, trusted_items, weak_items):
        # The same request or message repeated is one signal (PrestaShop requested
        # the same broken SVG twice on one load).
        trusted_items, weak_items = list(dict.fromkeys(trusted_items)), list(dict.fromkeys(weak_items))
        if trusted_items:
            signals[key] = trusted_items[:_MAX_SIGNAL_ITEMS]
            if len(trusted_items) > _MAX_SIGNAL_ITEMS:
                signals[f"{key}_more"] = len(trusted_items) - _MAX_SIGNAL_ITEMS
        if weak_items:
            weak[key] = weak_items[:_MAX_SIGNAL_ITEMS]
            if len(weak_items) > _MAX_SIGNAL_ITEMS:
                weak[f"{key}_more"] = len(weak_items) - _MAX_SIGNAL_ITEMS

    errors = [c["text"] for c in after.console if c.get("type") in ("error", "pageerror")]
    put("console_errors", [e for e in errors if _console_key(e) not in noise.get("console", ())],
        [e for e in errors if _console_key(e) in noise.get("console", ())])

    failed = [r for r in requests if r.get("status") is not None and (r["status"] == 0 or r["status"] >= 400)]
    def line(r):
        return f"{_request_key(r)} -> {r['status'] or r.get('failure') or 'no response'}"
    own = lambda r: _own_request(r, origin) and _request_key(r) not in noise.get("requests", ())
    put("failed_requests", [line(r) for r in failed if own(r)], [line(r) for r in failed if not own(r)])

    noisy_storage = set(noise.get("storage", ()))
    for key, keys in (("storage_added", sorted(set(storage_after) - set(storage_before))),
                      ("storage_removed", sorted(set(storage_before) - set(storage_after))),
                      ("storage_changed", sorted(k for k in set(storage_before) & set(storage_after)
                                                 if storage_before[k] != storage_after[k]))):
        put(key, [k for k in keys if k not in noisy_storage], [k for k in keys if k in noisy_storage])

    noisy_controls = set(noise.get("controls", ()))
    controls_before, controls_after = set(control_keys(before)), set(control_keys(after))
    for key, keys in (("controls_added", sorted(controls_after - controls_before)),
                      ("controls_removed", sorted(controls_before - controls_after))):
        put(key, [k for k in keys if k not in noisy_controls], [k for k in keys if k in noisy_controls])

    if not (sent and settled_before and settled_after):
        for key in [k for k in signals if not k.startswith("settled_") and not k.endswith("_more")]:
            items = signals.pop(key) + weak.get(key, [])
            cut = signals.pop(f"{key}_more", 0) + weak.pop(f"{key}_more", 0) + max(len(items) - _MAX_SIGNAL_ITEMS, 0)
            weak[key] = items[:_MAX_SIGNAL_ITEMS]
            if cut:
                weak[f"{key}_more"] = cut
    return signals, weak


def discovery_id(sig: str) -> str:
    """A short, stable id for a screen the carried map doesn't have, from its signature."""
    import hashlib
    return "d" + hashlib.blake2s(sig.encode("utf-8"), digest_size=4).hexdigest()


@functools.cache
def _feature_tags() -> frozenset[str]:
    return frozenset(load_vocabulary()["tags"]["feature"])


# Why the browser couldn't do a step (#325), from Playwright's error and its call log,
# most telling first: a Driver told only "failed" took a hidden toolbar search box for a
# basket quantity field and reported the harness as broken.
# Matched against Playwright's own words only: the call log also quotes the element's
# HTML, where a bare "disabled" matched aria-disabled="false" on every Angular dropdown.
_FAILURE_REASONS = (
    ("intercepts pointer events", "covered by another element"),
    ("is not a <select>", "not a dropdown with options (a custom one: click it, then click the option)"),
    ("did not find some options", "no option with that label"),
    ("element is not visible", "hidden: it has no size or isn't shown (it may open from another control)"),
    ("outside of the viewport", "hidden: it has no size or isn't shown (it may open from another control)"),
    ("element is not enabled", "disabled"),
    ("element is not editable", "not editable (read-only)"),
    ("strict mode violation", "more than one control matched"),
    ("element is detached", "it went away while the step ran"),
    ("timeout", "timed out waiting for it"),
)


def failure_reason(error: Exception | str) -> str:
    """Why a step failed, in words, from a Playwright error (#325)."""
    text = str(error)
    low = text.lower()
    for needle, reason in _FAILURE_REASONS:
        if needle in low:
            return reason
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:120] or "the browser couldn't do it"


def changes_data(element: dict, origin: str) -> bool:
    """Whether the read-only gate holds this control back because using it would change
    data (a submit, or a name like "Add to Basket"), not for another reason."""
    reason = gate_plan(element, origin).reason
    return "mutating verb" in reason or "commits a form" in reason


def discovery(obs, sig: str, path: list[dict], from_state: str, via: str, origin: str,
              common: set[str] = frozenset()) -> dict:
    """A screen an action reached that the carried map doesn't have (issue #157), in the
    shape of a map state, so it can be added to a map later (#158): its controls are
    already through web-recon's safety gate (committing unless the read-only crawl may act
    on them), and `path` is every step from the start, the carried path plus the action.
    Its controls, its fields and the controls that change data are listed as coverage
    tokens (#328), so the context can weigh it against the mapped screens. Its features
    leave out `common`, the controls on nearly every state of the map (the toolbar), as a
    mapped screen's do (#330)."""
    safe = {e["locator"] for e in safe_actions(obs.elements, origin)}
    return {
        "id": discovery_id(sig), "signature": sig, "url": obs.url, "title": obs.title,
        "from_state": from_state, "via": via, "path": path,
        "elements": [{"key": f"{e['role']}:{e['name']}", "role": e["role"], "name": e["name"],
                      "kind": e.get("tag", ""), "locator": e["locator"],
                      "committing": e["locator"] not in safe, "href": e.get("href", ""),
                      **({"hint": e["hint"]} if e.get("hint") else {})}       # #325
                     for e in obs.elements],
        "controls_offered": len(safe),
        "controls": sorted({ref_mod.control_token(e["role"], e["name"]) for e in obs.elements
                            if e["role"] not in ("", "generic")}),
        "fields": sorted({ref_mod.control_token(e["role"], e["name"]) for e in obs.elements
                          if e["role"] in ref_mod.FIELD_ROLES}),
        "changes_data": sorted({ref_mod.control_token(e["role"], e["name"]) for e in obs.elements
                                if changes_data(e, origin)}),
        # Feature tags from the vocabulary, the way a mapped screen gets them, so the oracle
        # can draw ideas for it when it's among the most important new places (#330).
        "features": to_context.features_of(
            [e for e in obs.elements if e["role"] not in ("", "generic") and to_context.common_key(e) not in common],
            [], _feature_tags()),
    }


def origin_of(url: str) -> str:
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}"


def off_site_target(url: str, status: int, location: str | None, site: str) -> str | None:
    """Where a main-frame navigation would take the browser off the site, or None (#308).
    A link on the site can still leave it through a redirect: Juice Shop's
    ./redirect?to=https://github.com/... passed the safety gate, which only sees the href."""
    if origin_of(url) != site:
        return url
    if 300 <= status < 400 and location and origin_of(urljoin(url, location)) != site:
        return urljoin(url, location)
    return None


def _step_label(step: dict) -> str:
    """How a step reads in an action's label: "button:Next page", "textbox:Search = 'x'",
    "goto /#/basket", "back"."""
    kind = step.get("do", "click")
    if kind == "back":
        return "back"
    if kind == "goto":
        return f"goto {step.get('value', '')}"
    label = f"{step.get('role', '')}:{step.get('name', '')}" + (f" #{step['nth']}" if int(step.get("nth") or 1) > 1 else "")
    return label + (f" = {step['value']!r}" if kind in ("fill", "select") and step.get("value") else "")


def _replay_step(step: dict, done: dict, session) -> dict:
    """A step that ran, as a replayable path step (what _actuate takes)."""
    if step.get("do") == "goto":
        return {"goto": session.route_url(step.get("value") or "/")}
    if step.get("do") == "back":
        return {"back": True}
    return {k: step[k] for k in ("role", "name", "value", "locator", "nth") if step.get(k)}


class Session:
    def __init__(self, reference: ref_mod.Reference, base_url: str, headed: bool, session_file: str | None = None,
                 record_video: bool = False):
        from playwright.sync_api import sync_playwright
        self.reference = reference
        self.base_url = base_url
        self.session_file = session_file
        self._session_storage_js = session_storage_script(session_file) if session_file else None
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed, slow_mo=300 if headed else 0)
        self._context = None
        # Every browser context records into a scratch folder. Only the recording each
        # test acted in is remembered, and save_videos keeps the ones asked for (#286).
        # Only a run records (check_ready); the sweep and the audits have no report to show it.
        self._video_dir = tempfile.mkdtemp(prefix="trailhound-video-") if record_video else None
        self._videos: dict = {}                    # test number -> its Playwright Video
        self.last_video = None
        # The browser never leaves the site (#308): where it was stopped from going.
        self._site = origin_of(base_url)
        self.blocked_off_site: list[str] = []
        # Careful everywhere until check_ready loads the target's tags (#299): a session
        # nobody set up fails closed.
        self.careful = dict(careful_mod.EVERYTHING)
        self._open_fresh_page()
        self.seen_signatures: set[str] = set()   # signatures first sighted this run
        self.last_covered_by = ""                  # what was on top of the last control clicked
        self.last_failure = ""                     # why the last step failed (#325)
        self._noise: dict = {}                      # state id -> what changes there on its own
        self.entry_signature = ""
        atexit.register(self.close)

    def close(self) -> None:
        for shut in (getattr(self, "_context", None), getattr(self, "_browser", None), getattr(self, "_pw", None)):
            try:
                (shut.close if hasattr(shut, "close") else shut.stop)()
            except Exception:
                pass
        if getattr(self, "_video_dir", None):
            shutil.rmtree(self._video_dir, ignore_errors=True)

    def save_videos(self, test_numbers, dest: Path) -> dict[int, str]:
        """Keep the videos of these tests as dest/test_<n>.webm and drop the rest (#286).
        A video is only complete once its context is closed, so recording stops here: the
        session goes on in a fresh context that doesn't record. Returns test number ->
        file name, for the tests that have a video."""
        scratch = self._video_dir
        if not scratch:
            return {}
        self._video_dir = None
        self._open_fresh_page()
        saved = {}
        for n in sorted(test_numbers):
            video = self._videos.get(n)
            if video is None:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            try:
                video.save_as(dest / f"test_{n}.webm")
                saved[n] = f"test_{n}.webm"
            except Exception as e:   # a lost video is a missing exhibit, not a failed run
                print(f"  couldn't save the video of test #{n}: {e}")
        # The rest were never asked for, and close() no longer knows the folder.
        shutil.rmtree(scratch, ignore_errors=True)
        return saved

    # ---- primitives ------------------------------------------------------------------

    def _open_fresh_page(self) -> None:
        """A new browser context, so no cookies, storage or cache carry over from the
        previous one. Juice Shop, for one, remembers a dismissed welcome banner or cookie
        message in a cookie, and on a reused page every later restart then lands on a
        different start screen (issue #117). The Collector is re-attached, because it
        listens on one page."""
        old = self._context
        options = {"viewport": {"width": 1280, "height": 900}}
        if getattr(self, "_video_dir", None):
            options["record_video_dir"] = self._video_dir
            options["record_video_size"] = _VIDEO_SIZE
        if getattr(self, "session_file", None):
            options["storage_state"] = self.session_file
        self._context = self._browser.new_context(**options)
        # The browser never leaves the site (#308), in this tab or any a click opens.
        self._context.on("page", self._guard_page)
        try:
            self._context.add_init_script(_MUTATION_COUNTER_JS)
        except Exception:
            pass
        if getattr(self, "_session_storage_js", None) and getattr(self, "_start_as", "same_tab") != "new_tab":
            self._context.add_init_script(self._session_storage_js)
        self.page = self._context.new_page()
        self._guard_page(self.page)
        self.col = Collector().attach(self.page)
        self._inflight: set = set()
        # Every request with the time it started, so an action is only blamed for the
        # requests it started (issue #143), not ones already in flight when it ran.
        self._requests: dict = {}
        self.page.on("request", self._on_request)
        self.page.on("response", lambda resp: self._requests.get(id(resp.request), {}).update(status=resp.status))
        self.page.on("requestfinished", lambda r: self._inflight.discard(id(r)))
        self.page.on("requestfailed", self._on_request_failed)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass

    def _guard_page(self, page) -> None:
        """Stops this page's main frame from leaving the site, directly or by a redirect
        (#308). Chrome's own interception (CDP Fetch), limited to page documents: it
        pauses each one before it's sent and again when its response arrives, so a
        redirect's Location is seen before the browser follows it. Not Playwright's
        route(): that sees every request and not the redirect hops, and routing Juice
        Shop's socket.io poll kept it open, so no page ever counted as rested.
        Once per page: the context's "page" event also fires for pages opened here."""
        if getattr(page, "_trailhound_guarded", False):
            return
        page._trailhound_guarded = True
        try:
            cdp = self._context.new_cdp_session(page)
            main_frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
            cdp.on("Fetch.requestPaused", lambda event: self._on_document(cdp, main_frame, event))
            cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document", "requestStage": stage}
                                                   for stage in ("Request", "Response")]})
        except Exception as e:      # never silently unguarded: say so
            print(f"WARNING: couldn't guard the browser against leaving the site ({type(e).__name__}: {e})")

    def _on_document(self, cdp, main_frame: str, event: dict) -> None:
        """One paused page document: stopped if it takes the main frame off the site.
        A frame inside the page (an embed) may load from another site."""
        location = next((h["value"] for h in event.get("responseHeaders") or [] if h["name"].lower() == "location"), None)
        target = None
        if event.get("frameId") == main_frame:
            target = off_site_target(event["request"]["url"], event.get("responseStatusCode") or 0, location, self._site)
        if target is None:
            cdp.send("Fetch.continueRequest", {"requestId": event["requestId"]})
            return
        self.blocked_off_site.append(target[:300])
        cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})

    def _reboot(self, url: str = "") -> None:
        """Back to the start as a first-time visitor: a fresh session, then the base URL,
        or `url` on the site (a test that starts from a route, #310)."""
        self._open_fresh_page()
        self.page.goto(url or self.base_url, wait_until="domcontentloaded")
        self.last_rest = self._rest()

    def route_url(self, route: str) -> str:
        """A route on the site ("/#/basket", "#/basket", "/profile") as a full URL."""
        route = route.strip()
        if route.startswith("#"):
            route = "/" + route
        return self.base_url.rstrip("/") + "/" + route.lstrip("/")

    def _on_request(self, r) -> None:
        self._inflight.add(id(r))
        self._requests[id(r)] = {"t": time.time(), "method": r.method, "url": r.url[:300], "status": None}

    def _on_request_failed(self, r) -> None:
        self._inflight.discard(id(r))
        if "ERR_BLOCKED_BY_CLIENT" in (r.failure or ""):
            # Our own guard stopped it (#308), not the product failing.
            self._requests.pop(id(r), None)
            return
        self._requests.get(id(r), {}).update(status=0, failure=(r.failure or "")[:120])

    def _requests_since(self, t: float) -> list[dict]:
        return [r for r in self._requests.values() if r["t"] >= t]

    def _controls_now(self) -> set:
        try:
            return set(control_keys({"elements": self.page.evaluate(ELEMENTS_JS)}))
        except Exception:
            return set()

    def _idle_noise(self) -> dict:
        """What changes on this page with no action at all, over _NOISE_SAMPLES looks
        _NOISE_SAMPLE_MS apart: the requests started, console errors, storage keys and
        controls that changed. An action's diff leaves those out of its trusted signals
        (see _signal_diff). Reads the element list, not a full capture, so the console
        log is drained only on purpose."""
        self.col.drain()
        storage0, controls0, t = self._storage(), self._controls_now(), time.time()
        storage_changed, controls_changed = set(), set()
        for _ in range(_NOISE_SAMPLES):
            self.page.wait_for_timeout(_NOISE_SAMPLE_MS)
            storage, controls = self._storage(), self._controls_now()
            storage_changed |= {k for k in set(storage0) | set(storage) if storage0.get(k) != storage.get(k)}
            controls_changed |= controls ^ controls0
        console, _ = self.col.drain()
        return {
            "requests": {_request_key(r) for r in self._requests_since(t)},
            "console": {_console_key(c["text"]) for c in console if c.get("type") in ("error", "pageerror")},
            "storage": storage_changed,
            "controls": controls_changed,
        }

    def _rest(self) -> bool:
        """Wait until the page has rested (see _REST_QUIET_MS). True if it did, False if
        _REST_MAX_MS ran out first; the read that follows is then flagged unsettled."""
        start = time.time()
        quiet_since, last = start, None
        while True:
            try:
                mutations = self.page.evaluate("window.__trailhoundMutations ?? -1")
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
            # Only the site's own cookies (#308): another site's are none of its storage.
            keys.update({f"cookie:{c['name']}": hash(c.get("value", ""))
                         for c in self._context.cookies(self.base_url)})
        except Exception:
            pass
        return keys

    def _video_of_page(self):
        try:
            return self.page.video if self._video_dir else None
        except Exception:
            return None

    def _shot(self):
        try:
            return self.page.screenshot()
        except Exception:
            return None

    def _note_failure(self, error: Exception) -> None:
        """Keep the most telling reason a step failed (#325): the ladder tries several
        ways, and a later forced click's error says less than the first one's."""
        reason = failure_reason(error)
        rank = {r: i for i, (_, r) in enumerate(_FAILURE_REASONS)}
        kept = getattr(self, "last_failure", "")
        if not kept or rank.get(reason, len(rank)) < rank.get(kept, len(rank)):
            self.last_failure = reason

    def _actuate(self, step: dict) -> bool:
        """Actuate one control the way the recon's safety gate classified it: a text/search
        box is *filled* with a benign query (only search/filter boxes reach here - the gate
        marks any other text field committing, so it never enters the action space), and
        everything else is *clicked*. Clicking a search box instead of filling it merely
        focuses it and looks like a dead control - the false reading this exists to avoid."""
        if step.get("goto"):                    # a route, in a replayed path (#310)
            try:
                self.page.goto(step["goto"], wait_until="domcontentloaded", timeout=15000)
                return True
            except Exception as exc:
                self._note_failure(exc)
                return False
        if step.get("back"):
            try:
                self.page.go_back(wait_until="domcontentloaded", timeout=8000)
                return True
            except Exception as exc:
                self._note_failure(exc)
                return False
        role, name, css = step.get("role", ""), step.get("name", ""), step.get("locator", "")
        self.last_covered_by = ""
        if role in TEXT_ROLES:
            return self._fill(role, name, css, step.get("value") or SEARCH_PROBE)
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
        except Exception as exc:
            self._note_failure(exc)
        # Click ladder: a unique (role, name) locator first, then the exact selector, then a
        # forced click - the compact form of web-recon's ladder.
        if role in _ROLE_LOCATABLE and name:
            try:
                loc = self.page.get_by_role(role, name=name, exact=True)
                if loc.count() == 1:
                    loc.click(timeout=4000)
                    return True
            except Exception as exc:
                self._note_failure(exc)
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
            except Exception as exc:
                self._note_failure(exc)
        for attempt in (lambda: self.page.click(css, timeout=3000),
                        lambda: self.page.click(css, timeout=2000, force=True)):
            try:
                attempt()
                return True
            except Exception as exc:
                self._note_failure(exc)
                continue
        return False

    def save(self, path) -> dict:
        """Save this session (cookies and storage) to `path`, so later tests and Spoor can
        start from the state a run reached, e.g. after a scripted login on a sandbox target
        (issue #155). Refuses a path git doesn't ignore. Returns what was saved, by name only."""
        from trailhound.adapters.web_gui.save_session import refuse_unless_ignored, save_state

        path = Path(path)
        refuse_unless_ignored(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return save_state(self._context, path)

    def _find_live(self, role: str, name: str, nth: int = 1) -> dict | None:
        """The element on the page now with this role and name: an exact name first, then
        the same name in any case, then one whose name contains it if only one does. An
        empty name is a name too: product images and icon buttons often have none, and
        `nth` picks among several (the first by default, in page order)."""
        try:
            same_role = [e for e in self.page.evaluate(ELEMENTS_JS) if e.get("role") == role]
        except Exception:
            return None
        wanted = (name or "").strip().lower()
        for matches in ([e for e in same_role if (e.get("name") or "") == (name or "")],
                        [e for e in same_role if (e.get("name") or "").strip().lower() == wanted]):
            if matches:
                return matches[nth - 1] if 0 < nth <= len(matches) else None
        contains = [e for e in same_role if wanted and wanted in (e.get("name") or "").lower()]
        if len(contains) == 1 and nth == 1:
            return contains[0]
        # The browser's accessibility tree, where Spoor's names come from: a Juice Shop
        # product card is "button:Apple Juice (1000ml)" there, but an unnamed button in
        # the DOM capture (#310).
        try:
            found = self.page.get_by_role(role, name=name, exact=True).count() if name else 0
        except Exception:
            found = 0
        return {"role": role, "name": name, "locator": "", "a11y_nth": nth} if 0 < nth <= found else None

    def _page_route(self) -> str:
        try:
            url = urlsplit(self.page.url)
        except Exception:
            return ""
        return (url.path or "/") + (f"#{url.fragment}" if url.fragment else "")

    def _do_step(self, step: dict) -> dict:
        """One step of a test on the live page (#310): done, not_found, refused or failed,
        with why. Testing fully by default (#299): any element may be clicked, any field
        typed into, any route opened. On a part of the target tagged careful, the read-only
        safety gate decides instead, judged on the element as it is on the page. Logging
        out is refused everywhere: every test starts from the logged-in session."""
        kind = step.get("do")
        record = {k: step[k] for k in ("do", "role", "name", "value", "nth") if step.get(k) not in (None, "")}
        self.last_failure = ""
        tags = getattr(self, "careful", careful_mod.EVERYTHING)
        gated = lambda why: {**record, "status": "refused",
                             "detail": f"tagged careful, and the read-only safety gate refuses it: {why}"}
        logs_out = {**record, "status": "refused",
                    "detail": "it would log out, which ends the session every test starts from"}
        if kind == "back":
            ok = self._actuate({"back": True})
            return self._outcome(record, ok)
        if kind == "goto":
            route = step.get("value") or "/"
            url = self.route_url(route)
            if careful_mod.logs_out(route):
                return logs_out
            if careful_mod.applies(tags, route):
                gate = gate_plan({"role": "link", "name": route, "href": url, "tag": "a"}, self._site)
                if gate.kind is None:
                    return gated(gate.reason)
            blocked_before = len(self.blocked_off_site)        # an earlier step's block isn't this one's
            ok = self._actuate({"goto": url}) and len(self.blocked_off_site) == blocked_before
            if len(self.blocked_off_site) > blocked_before:
                self.last_failure = "it leads off the site, and the browser was stopped"
            return self._outcome(record, ok)
        element = self._find_live(step.get("role", ""), step.get("name", ""), int(step.get("nth") or 1))
        if element is None and step.get("locator"):     # the map's saved selector (the sweep)
            element = {"role": step.get("role", ""), "name": step.get("name", ""), "locator": step["locator"]}
        if element is None:
            return {**record, "status": "not_found",
                    "detail": "nothing on the page has that role and name (or not that many); page_controls lists what's there"}
        if careful_mod.logs_out(element.get("name", "")):
            return logs_out
        if careful_mod.applies(tags, self._page_route(), element.get("name", "")):
            gate = gate_plan(element, self._site)
            allowed = {"click": ("click",), "fill": ("fill",), "select": ("select",)}.get(kind, ())
            if gate.kind not in allowed:
                return gated(gate.reason if gate.kind is None else f"it can only be {gate.kind}ed")
        target = {"role": element["role"], "name": element["name"], "locator": element.get("locator", ""),
                  **({"value": step["value"]} if step.get("value") else {})}
        if element.get("a11y_nth"):
            # Found only by its accessible name: act on it there.
            try:
                found = self.page.get_by_role(element["role"], name=element["name"], exact=True).nth(element["a11y_nth"] - 1)
                if kind == "fill":
                    found.fill(step.get("value", ""), timeout=4000)
                elif kind == "select":
                    found.select_option(label=step.get("value", ""), timeout=4000)
                else:
                    found.click(timeout=4000)
                ok = True
            except Exception as exc:
                self._note_failure(exc)
                ok = False
            return self._outcome(record, ok)
        if kind == "fill":
            ok = self._fill(element["role"], element["name"], element.get("locator", ""), step.get("value", ""))
            return self._outcome(record, ok)
        if kind == "select":
            try:
                self.page.select_option(target["locator"], label=step.get("value", ""), timeout=4000)
                ok = True
            except Exception as exc:
                self._note_failure(exc)
                ok = False
        else:
            ok = self._actuate(target)
        return self._outcome(record, ok)

    def _outcome(self, record: dict, ok: bool) -> dict:
        """A step's record, done or failed, and when it failed, why (#325)."""
        if ok:
            return {**record, "status": "done"}
        return {**record, "status": "failed", "detail": self.last_failure or "the browser couldn't do it"}

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
            except Exception as exc:
                self._note_failure(exc)
        try:
            self.page.fill(css, value, timeout=4000)
            return True
        except Exception as exc:
            self._note_failure(exc)
            return False

    def _classify(self, before_sig: str, after_sig: str) -> str:
        if after_sig == before_sig:
            return "same_screen"
        if after_sig in self.reference.known_signatures or after_sig in self.seen_signatures:
            return "known_screen"
        return "new_screen"

    def reaches(self, path: list[dict], sig: str) -> bool:
        """Whether replaying `path` from a fresh start lands on the screen `sig`."""
        self._reboot()
        replayed = self._replay(path)
        return replayed and signature(self._capture_expecting(sig)) == sig

    def check_url(self, path: str) -> int | None:
        """The HTTP status of `path` on the product, opened in a fresh context loaded from
        the session (issue #227), or None if it didn't answer."""
        self._open_fresh_page()
        try:
            response = self.page.goto(self.base_url.rstrip("/") + "/" + path.lstrip("/"),
                                      wait_until="domcontentloaded", timeout=15000)
            return response.status if response else None
        except Exception:
            return None

    # ---- the one operation the loop drives -------------------------------------------

    def baseline(self) -> str:
        """Reboot to the start and record the entry signature; the run's ground truth."""
        self._reboot()
        start = self.reference._by_id.get(self.reference.entry(), {}).get("signature", "")
        self.entry_signature = signature(self._capture_expecting(start))
        self.seen_signatures.add(self.entry_signature)
        return self.entry_signature

    def act(self, state_id: str, control_key: str, start_as: str = "same_tab", test_number=None) -> dict:
        """One control on one mapped screen: the one-step test the sweep runs. The map's
        saved selector goes along as a fallback, in case the live lookup misses."""
        target = self.reference.plan_for(state_id, control_key)["target"]
        step = {"do": "fill" if target["role"] in TEXT_ROLES else "click", "role": target["role"],
                "name": target["name"], "locator": target.get("locator", "")}
        return self.act_steps(state_id, [step], start_as, test_number)

    def act_steps(self, start: str, steps: list[dict], start_as: str = "same_tab", test_number=None) -> dict:
        """Reach `start` (a route on the site, or a screen the map knows by id), run `steps`
        on the live page (#310), and report the whole transition classified against the map.
        Recovery (a reboot) is part of the operation when it lands somewhere new, so the next
        test starts clean. `start_as` "new_tab" starts every reboot of this test as a new tab
        (START_AS). With a test_number, the video of the context it ran in is kept under it."""
        self._start_as = start_as
        self.last_video = None
        try:
            result = self._act(start, steps)
        finally:
            self._start_as = "same_tab"
            if test_number is not None and self.last_video is not None:
                self._videos[test_number] = self.last_video
        if start_as != "same_tab":
            result["started_as"] = start_as
        return result

    def is_start(self, start: str) -> bool:
        """Whether a test can start there: a route on the site, or a screen this run knows."""
        return start.startswith(("/", "#")) or start in self.reference._paths

    def _reach(self, start: str):
        """A fresh start, then `start`: (reached, the capture there, its expected signature,
        the replayable path to it). A route is opened directly; a screen is reached by
        replaying how the map or this run got there."""
        if start.startswith(("/", "#")):
            url = self.route_url(start)
            self.blocked_off_site = []
            self._reboot(url)
            return not self.blocked_off_site, self._capture_expecting(""), "", [{"goto": url}]
        path = self.reference._paths[start]
        self._reboot()
        replayed = self._replay(path)
        expected = self.reference._by_id.get(start, {}).get("signature", "")
        before = self._capture_expecting(expected)
        return replayed and expected == signature(before), before, expected, list(path)

    def _act(self, start: str, steps: list[dict]) -> dict:
        # A new tab's page can sit differently while idle (it may fail requests a same-tab
        # page doesn't), so its background is learned on its own.
        noise_key = start if self._start_as == "same_tab" else f"{start}@{self._start_as}"
        reached, before, expected, path = self._reach(start)
        # Learn this state's background once per run, but only once the replay is
        # verified to have reached it: a drifted first replay would otherwise attach
        # another page's noise to this state for the rest of the run. The watch moves
        # the page on, so it rests and is read again afterwards.
        if reached and noise_key not in self._noise:
            self._noise[noise_key] = self._idle_noise()
            # The watch moves the page on: PrestaShop's slider turns about 5 s after each
            # load, so a read after the watch no longer matched the state (#146 audit
            # rerun). Reach the state afresh instead, as every later act does.
            reached, before, expected, path = self._reach(start)
        settled_before = self.last_rest
        storage_before = self._storage()
        before_sig = signature(before)
        before_png = self._shot()

        # The click and the settle are timed separately: the click ladder's fallbacks can
        # take seconds on their own, and counting them as the page's settle time made our
        # retries look like a slow app (issue #122).
        t0 = time.time()
        self.blocked_off_site = []
        done = []                                   # what each step did, in order
        for i, step in enumerate(steps if reached else []):
            done.append(self._do_step(step))
            if done[-1]["status"] != "done":
                break                               # later steps build on this one
            if i < len(steps) - 1:
                self.last_rest = self._rest()
        sent = any(d["status"] == "done" for d in done)
        t1 = time.time()
        settled_after = self._rest()
        click = round(t1 - t0, 2)
        settle = round(time.time() - t1, 2)

        after = capture(self.page, self.col)
        after_sig = signature(after)
        after_png = self._shot()
        # The recording that shows this test: the path to the state, then the action.
        # Taken before the recovery reboot opens a context of its own.
        self.last_video = self._video_of_page()
        screen_was = self._classify(before_sig, after_sig)
        first_sight = after_sig not in self.seen_signatures
        # NONE vs VARIANT: same signature, but did the body text OR the pixels still move?
        # The pixel check catches a canvas pan/zoom the signature and text cannot see, so a
        # live map control is not reported to the Driver as a dead control.
        vd = visual_diff(before_png, after_png)
        moved = (appearance(after) != appearance(before)
                 or (vd is not None and vd > _VISUAL_CHANGE_THRESHOLD))

        result = {
            "action": f"{start} :: " + " > ".join(_step_label(s) for s in steps),
            "reached_target_state": reached,
            "screen_before": before_sig,
            # The stored fingerprint of the state this test was cast against, so the
            # engine can tell "started where it meant to" from "landed elsewhere".
            # Empty for a test that starts from a route: there's no fingerprint to expect.
            "intended_before": expected,
            "screen_after": after_sig,
            "screen_was": screen_was,
            "same_appearance": (screen_was == "same_screen" and not moved),
            "was_measured_before": self.reference.is_known(after_sig),
            "first_sight_this_run": first_sight,
            "settle": settle,
            "click": click,
            "verdict": "sent" if sent else "not_actuated",
            # Each step and what came of it: done, not_found, refused or failed (#310).
            "steps": done,
        }
        if sent:
            # What's on the page now, so the next round can act on it (#310).
            # A control with no name is told apart by its hint and picked by nth (#325),
            # listed after the named ones so the cap cuts hints, not the paging controls.
            nth: Counter = Counter()
            named, hinted, rest = [], [], {}
            for e in after.elements:
                if e.get("role") in ("generic", ""):
                    continue
                if not e.get("name"):
                    nth[e["role"]] += 1            # counted as a step's nth counts: toasts too
                if e.get("transient"):
                    continue
                if not e.get("name") and e.get("hint"):
                    if nth[e["role"]] <= ref_mod.UNNAMED_LISTED:
                        hinted.append(ref_mod.unnamed_key(e, nth[e["role"]]))
                    else:
                        rest.setdefault(e["role"], []).append(nth[e["role"]])
                    continue
                named.append(f"{e['role']}:{e['name']}")
            counted = Counter(named)
            # "link: (x12)": twelve unnamed links, picked with nth.
            keys = [k if n == 1 else f"{k} (x{n})" for k, n in counted.items()] + hinted + [
                ref_mod.unnamed_rest(role, nths[0], nths[-1]) for role, nths in rest.items()]
            result["page_controls"] = keys[:_PAGE_CONTROLS_SHOWN]
            if len(keys) > _PAGE_CONTROLS_SHOWN:
                result["page_controls_more"] = len(keys) - _PAGE_CONTROLS_SHOWN
        if sent and self.last_covered_by:
            result["covered_by"] = self.last_covered_by
        if self.blocked_off_site:
            # The control leads off the site; the browser was stopped (#308).
            result["blocked_off_site"] = list(dict.fromkeys(self.blocked_off_site))
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(self.base_url))
        result["signals"], weak = _signal_diff(before, after, self._requests_since(t0), storage_before, self._storage(),
                                               settled_before, settled_after, self._noise.get(noise_key, {}), origin,
                                               # After a stopped trip off the site (#308) the page is the
                                               # browser's error page, not the product: hints only.
                                               sent=sent and not self.blocked_off_site)
        if weak:
            result["signals_weak"] = weak
        # A screen the carried map doesn't have, however many times this run has seen it,
        # so later runs can count how often it's reached (#157). Recorded before the
        # recovery reboot, from the capture taken on it. It also joins this run's map, so
        # later tests can act on it (#158).
        # Not from a new-tab test: the screen's path only replays from a new tab, and
        # the run's map is replayed from the saved session as it was.
        if (sent and not self.blocked_off_site and after_sig not in self.reference.carried_signatures
                and self._start_as == "same_tab"):
            origin = "{0.scheme}://{0.netloc}".format(urlsplit(self.base_url))
            ran = [_replay_step(s, d, self) for s, d in zip(steps, done) if d["status"] == "done"]
            result["discovered"] = discovery(after, after_sig, path + ran, start,
                                             " > ".join(_step_label(s) for s in steps), origin,
                                             to_context.common_controls(self.reference.states))
            result["discovered"]["in_run_map"] = bool(self.reference.add_discovery(result["discovered"],
                                                                                  _MAX_DISCOVERY_STEPS))
        self.seen_signatures.add(after_sig)
        if screen_was == "new_screen":
            recovered = self.recover()
            result["recovered_to"] = recovered
            result["recovered_ok"] = recovered == self.entry_signature
        return result

    def _replay(self, path: list[dict]) -> bool:
        """Actuate a carried path step by step, resting after each; stops at the first
        step that fails."""
        for step in path:
            ok = self._actuate(step)
            self.last_rest = self._rest()
            if not ok:
                return False
        return True

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


def join_earlier_discoveries(session: "Session", discoveries: list[dict]) -> dict:
    """Check the screens earlier runs discovered (context_<product>.json, issue #159) and
    add the ones that still replay to this run's map, so the Driver can act on them from
    the first round. Each is replayed once from a fresh start: it joins only if it lands
    on the same screen, which also counts as one more reach of it (feedback reads
    "joined"). Returns the ids by outcome."""
    outcome: dict[str, list[str]] = {"joined": [], "not_reached": [], "already_in_map": [], "too_deep": []}
    ranked = sorted(discoveries, key=lambda d: -d.get("times_reached", 0))
    for record in ranked[:_MAX_EARLIER_DISCOVERIES]:
        if record["signature"] in session.reference.carried_signatures:
            outcome["already_in_map"].append(record["id"])
        elif len(record["path"]) > _MAX_DISCOVERY_STEPS:
            outcome["too_deep"].append(record["id"])
        elif session.reaches(record["path"], record["signature"]):
            session.reference.add_discovery(record, _MAX_DISCOVERY_STEPS, earlier_run=True)
            outcome["joined"].append(record["id"])
        else:
            outcome["not_reached"].append(record["id"])
    return {k: v for k, v in outcome.items() if v}


def _route_name(url: str) -> str:
    """'http://h/#/privacy-security/privacy-policy' as 'privacy security / privacy policy'."""
    parts = urlsplit(url or "")
    route = (parts.fragment or parts.path or "/").strip("/")
    return " / ".join(p.replace("-", " ") for p in route.split("/") if p) or "start page"


def product_areas(reference, product: str = "") -> list[str]:
    """The names the Driver's testing story uses for areas (#285): each screen of the map
    by route, and the product's screens from the wiki when there is one."""
    names = []
    if product:
        try:
            from trailhound.ontology.product import context_screens, load_product
            names += [e["title"] for e in (load_product(product) or {}).get("entities", [])]
            names += [s["title"] for s in context_screens(product)]          # from Spoor's map (#311)
        except Exception:      # a product without a readable wiki still gets the map's names
            pass
    names += [_route_name(s.get("url", "")) for s in reference.states]
    return list(dict.fromkeys(names))


def has_session() -> bool:
    """Whether this run starts from a saved session, so a new tab differs from the same tab."""
    return bool(_SESSION is not None and _SESSION.session_file)


def _described(name: str) -> str:
    return f"from the saved session '{name}'" if name else "without a saved session"


def replay_blocker() -> str | None:
    """Why a bug's tests can't be trusted to replay right now, or None (issue #177). A
    replay from a session the server no longer accepts reproduces the server's refusal
    every time, which is how the #160 milestone run corroborated a false positive. So the
    same checks as check_ready run again, at the end of the run."""
    session = live()
    if not session.session_file:
        return None
    try:
        check_session_fresh(session.session_file, time.time())
    except SystemExit as e:
        return str(e)
    check_path = session_check_path()
    if check_path:
        status = session.check_url(check_path)
        if status is None or status >= 400:
            return (f"the saved session {session_name(session.session_file)!r} failed its server check: "
                    f"{check_path} answered {status or 'nothing'}")
    return None


def check_ready(adapter) -> None:
    """Load the carried reference, launch the browser, and confirm the SUT is up and on the
    mapped entry state before anything is spent. Raises SystemExit with an actionable
    message rather than returning a flag - a run against a SUT that isn't there costs API
    calls to discover otherwise."""
    global _SESSION
    reference = ref_mod.load(_resolve_ontology_path())
    # A map saved before #303 still has the user's email in some signatures.
    reference.rewrite_signatures(impersonal)
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
    session_file = load_session_file(os.environ[_SESSION_ENV]) if os.environ.get(_SESSION_ENV) else None
    if session_file:
        warning = check_session_fresh(session_file, time.time())
        if warning:
            print(warning)
    # A map made logged out doesn't match a logged-in start page (Juice Shop shows a basket
    # button, for one), so every test would read as not reaching its state. Say so up front.
    if session_name(session_file) != reference.session_name:
        print(f"WARNING: the carried map was made {_described(reference.session_name)}, but this run starts "
              f"{_described(session_name(session_file))}. Expect tests not to reach their states; make the map "
              f"with the same session (from_spoor --session).")
    check_path = session_check_path()   # before the browser starts, so a bad value costs nothing
    session = Session(reference, base_url, headed, session_file, record_video=video_on())
    if session_file and check_path:
        status = session.check_url(check_path)
        if status is None or status >= 400:
            session.close()
            raise SystemExit(
                f"The saved session {session_name(session_file)!r} failed its server check: {check_path} answered "
                f"{status or 'nothing'}. The server no longer accepts it, so tests would report its refusals as "
                "bugs. Save a fresh session, or fix " + _SESSION_CHECK_ENV + ".")
        print(f"Session {session_name(session_file)!r} accepted by the server ({check_path} answered {status}).")
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

    # Screens earlier runs discovered join the map before the Driver is briefed (#159).
    product = os.environ.get(_PRODUCT_ENV, "").strip()
    earlier = load_context(product).get("discoveries", []) if product else []
    # Saved before #303, a discovery's signature can still hold the user's email.
    earlier = [{**d, "signature": impersonal(d.get("signature", ""))} for d in earlier]
    if earlier:
        joined = join_earlier_discoveries(session, earlier)
        adapter.onboarding_extra["earlier_discoveries"] = joined
        # Their routes, so a reader (and the Driver) can tell the ids apart (#285).
        adapter.onboarding_extra["earlier_discovery_routes"] = {
            d["id"]: urlsplit(d.get("url", "")).fragment or urlsplit(d.get("url", "")).path for d in earlier}
        print("Screens from earlier runs: " + ", ".join(f"{len(v)} {k.replace('_', ' ')}" for k, v in joined.items()))
    else:
        adapter.onboarding_extra.pop("earlier_discoveries", None)

    # The parts of the product the testing story names its areas after (#285): every
    # screen in the map by route, plus the wiki's screens when there's a product.
    adapter.onboarding_extra["product_areas"] = product_areas(reference, product)

    # onboarding_extra is merged into the Driver's evidence (trailhound/loop._base_evidence) and
    # rendered in the report, so the carried map - the action space - is filled in here, the
    # one moment the reference is loaded. The dict is mutated, not reassigned (the adapter is
    # frozen); same pattern as clash_royale's preflight/baseline.
    adapter.onboarding_extra["carried_map"] = reference.driver_briefing()
    adapter.onboarding_extra["baseline"] = baseline_note
    # Testing fully unless tagged careful (#299). Said plainly, because it's what catches a
    # run pointed at the wrong system.
    session.careful = careful_mod.load(product)
    adapter.onboarding_extra["testing_mode"] = careful_mod.describe(session.careful)
    print(adapter.onboarding_extra["testing_mode"])
    if session_file:
        adapter.onboarding_extra["session"] = (
            f"Every test starts from the saved session '{session_name(session_file)}' (for example logged in), "
            "in a fresh browser context each time.")
    else:
        adapter.onboarding_extra.pop("session", None)
    _SESSION = session
