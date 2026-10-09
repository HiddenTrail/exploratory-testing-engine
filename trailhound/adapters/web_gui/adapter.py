"""SUTAdapter for a web GUI: a browser app as a system under test, driven by the LLM
Driver over web-recon's perception.

The fourth adapter, and the browser transposition of clash_royale. Where that one drives a
live game by named taps and reads screens by pixel comparison, this drives a web app by
named (state, control) actions and reads states by web-recon's *signature* (URL route +
control skeleton + landmark headings). The two share a spine on purpose: an interface
nobody declared is mapped by exploring it, the only claim checkable on a first visit is
whether a control lands somewhere `same` / `known` / `new`, and the carried reference (an
earlier recon pass) is what turns `known_screen` into a claim about the app rather than
about the run's own memory.

What the Driver is testing
--------------------------
Not "does this app work" - the navigation graph the deterministic recon already mapped.
A test is one control on one state plus a structural prediction of where it lands. An
anomaly is a control that does not do what the interface implies: a dead control, a control
you cannot get back from, two controls to one place, a state whose identity is unstable.

Safety
------
The action space is exactly the (state, control) pairs the recon found and its read-only
safety gate cleared as non-committing - carried in the reference, enumerated by
reference.pairs(). There is no free-text selector and no coordinate: the Driver picks a
pair from an enumerated map, and a pair outside it is refused before anything is actuated.
So this run looks and navigates only; nothing it can name mutates the app.
"""

import os
import re
from pathlib import Path

from trailhound import outcome
from trailhound.adapter import SUTAdapter
from trailhound.coverage import value_kinds
from trailhound.tools import CASTING_REASONING_DESCRIPTION, PRIOR_FEEDBACK_GUIDE, casting_envelope_errors
from trailhound.adapters.web_gui import reference as ref_mod
from trailhound.adapters.web_gui import session as live_session
from trailhound.adapters.web_gui.reference import PREDICTIONS
from trailhound.adapters.web_gui.score import score_run
from trailhound.ontology.oracle_creator import build_product_ideas, build_ranked_ideas
from trailhound.report import badge, bool_badge, esc, inline_markdown, render_json_block, render_oracle_ranked


API_SCHEMA_DOC = """A web application, explored through a browser and observed by web-recon's
state signature. There is no API response body to read: a "state" is a view of the app,
identified by its URL route, the set of interactive controls on it, and its landmark
headings - body text and map position are treated as the same state, a variant.

WHAT A TEST IS. A test starts somewhere and then does up to 6 steps on the live page, in
order, the way a person would. `start` is a route on the site, like "/#/basket" or "/", or
the id of a screen from `carried_map` or one discovered this run (like "st05"); a screen
id is reached by replaying how it was found. Each step is one of:
  click   an element, by its role and name ("button", "Add to Basket")
  fill    a field, by role and name, with the value you choose
  select  an option in a list, by the list's role and name and the option as value
  press   a key, as value: Enter, Escape, Tab, Shift+Tab, ArrowUp, ArrowDown, ArrowLeft,
          ArrowRight, Space or Backspace. With a role and name it goes to that element,
          focused first (Enter in a chat box sends the message); without, to whatever has
          focus after the step before (a field you just filled), and the step's result
          says what that was in "focused"
  goto    a route on the site, as value
  back    the browser's back button
Name elements the way `carried_map` and a result's `page_controls` list them, "role:name":
the role is what comes before the first colon. An element can have an empty name ("link:",
an image or an icon); when several share a role and name, page_controls shows "(x12)" and
`nth` picks which, in page order. `carried_map` is a guide to the product's
screens, their routes and what's on them, from an earlier recon; it is not a limit. You can
act on anything that is on the page when the step runs. A step whose element isn't there
comes back "not_found", and the steps after it don't run. Every test starts from a fresh
browser, so a test is a sequence, not a step in a longer one: put what builds on what in
the same test.

SCREENS FROM EARLIER RUNS. carried_map can include screens earlier runs discovered, marked
"found by an earlier run". Each was replayed once at the start of this run and landed where
it did before, so it's as valid a state as any other. earlier_discoveries lists which joined
and which no longer replay.

DISCOVERED SCREENS. When a test reaches a screen the carried map doesn't have, its result
carries `discovered`: the screen's id (e.g. "d85f2417e"). From the next round on, that id
works as a start: the harness reaches it by replaying the start and steps that found it,
from a fresh session.

NEW TAB. With a saved session, a test may set start_as to "new_tab": it then starts the
way a new tab of the same logged-in browser would. Cookies and localStorage are shared with
the saved tab, sessionStorage starts empty. Apps that keep part of a user's state per tab
(a basket, a wizard's step, a selection) can lose it or break here. To use it, run the same
test once as usual and once as a new tab, and compare. The result then carries
started_as: "new_tab".

FRESH START. A test may set start_as to "fresh": it then starts with no saved session at all,
what a first-time visitor gets: no cookies, no storage, not logged in. Use it to see what a new
visitor sees (a cookie notice, a welcome dialog) or to test logging in; a step that needs a login
has to do it. The result then carries started_as: "fresh".

WHAT YOU GET BACK, per test:
  screen_before / screen_after: the state signature before the first step and after the last.
  screen_was: "same_screen" (the signature did not change), "known_screen" (it changed to a
    state already in the carried map or already seen this run), or "new_screen" (somewhere
    neither applies to - a state the recon never mapped).
  same_appearance: true only when screen_was is same_screen AND the body/text did not move
    either - i.e. the control did nothing observable at all (a candidate dead control).
  was_measured_before: true if the state landed on was in the carried map.
  first_sight_this_run: true the first time this run reaches that state.
  reached_target_state: whether the test got to its start before the first step - false means
    the app drifted (or the route didn't open) and the reading is suspect.
  steps: each step and what came of it: "done", "not_found" (nothing on the page had that
    role and name), "refused" (see HOW FAR YOU MAY GO) or "failed" (it was there but didn't
    respond; "detail" says why). A step also says what it set off, so an error is tied to
    the step that caused it. In a test of several steps, its own "signals" and
    "signals_weak" (console errors and failed requests; a step is trusted only if it was
    done and the page had rested before and after it). On a trusted step, "server_said": a
    failed request on the product's own site with the server's own error message, and
    "slow": its requests that took 2 s or more. "requests": what the step sent to the site, as
    "POST /api/Users -> 201", at most 8 (static files that loaded fine aren't listed). Any step can
    also carry "page_says": what
    the page started ("shown") and stopped ("gone") telling the user with that step, read
    after the page rested: "invalid field 'Email': Please provide an email address.",
    "error at 'Password': ...", "error: Invalid email or password." (text the page marks
    as an error or notice), "alert: ...", "status: ..." (toasts, snack bars, live regions),
    and "the browser refused 'Name': ..." (the browser's own check when a form is submitted,
    for the first field it refuses; shown on each step that sets it off, never "gone"). Treat it as a fact. "page_says_weak" is the
    same from a step that isn't trusted, for example one the page hadn't rested after. No
    page_says means nothing changed there, which only counts as "no message" if the
    message would have shown by then.
  page_controls: what's on the page after the last step, as "role:name", so a next test can
    act on it.
  settle: seconds the page took to go quiet after the action (the app's own timing).
  click: seconds the click itself took. A long click means the harness needed a
         fallback to press the control (it was not uniquely found), not that the
         app was slow.
  signals: what the action did beyond the screen it landed on, worked out by the
         harness from before/after captures (only what changed is listed):
         settled_before / settled_after (false: the page was still changing or loading
         when it was read, so the reading is suspect), console_errors, failed_requests
         (status 0 means no response at all), storage_added / storage_removed /
         storage_changed (local:, session: and cookie: keys; values are never shown),
         controls_added / controls_removed. These passed every trust check: the
         request started after the action, on the product's own origin, nothing of it
         happened while the page sat idle, and the page had rested. Treat them as facts.
  signals_weak: the same kinds of signal that failed a trust check (third-party, also
         seen with no action, read from an unsettled page, or the action wasn't sent).
         A hint for a next test, never evidence for a claim on its own. Console warnings are
         only ever here.
  discovered: present when the action reached a screen the carried map doesn't have: its
         id (e.g. "d1a2b3c4") and how many controls on it the safety gate would allow.
         The same id again means the same screen, reached again.
  covered_by: present when something else was on top of the control, for example
         "dialog 'cookieconsent'". The harness sent the click to the control anyway,
         which a real user couldn't do without moving the cover first.
  blocked_off_site: present when the action tried to take the browser to another site,
         directly or through a redirect: where it would have gone. The browser was stopped,
         because tests never leave the product's site. A control that leads off the site,
         especially through the product's own redirect, can be worth reporting.
  verdict: "sent" when at least one step ran, "not_actuated" when none did.
  recovered_to: the signature the run rebooted to after an action that reached a new state,
    so the next test starts clean; recovered_ok says whether that matched the start state.

WHAT COUNTS AS A PROBLEM HERE. Anything the product does that a user, or the oracle's ideas,
wouldn't expect: an error in the console or a failed request on the site while doing
something ordinary, a form that accepts a value it shouldn't or refuses one it should, a
number that doesn't add up, a step that changes nothing (same_screen with same_appearance),
a state that's lost (a basket, a login, a choice) when it shouldn't be, a place you can't
get back from (recovered_ok false). A carried screen you can no longer reach is drift since
the recon: a real finding, but about the map, so label it as such."""


SAFETY_NOTE = """HOW FAR YOU MAY GO. This run tests fully: you may click anything, type any value
into any field, choose options, submit forms, add to the basket and check out, and change
settings, on a copy of the product nobody depends on. 'testing_mode' in your evidence says if
any part of it is tagged careful; there you only look, and a step that would submit, buy,
delete or type into anything but a search box comes back "refused". A key press there is
judged the same way: Escape, Tab and Shift+Tab are fine, Enter and Space only on what you
could click and never in a field, the arrow keys and Backspace only in a search box. Enter
in a form submits it, so it's refused anywhere a click on the form's submit button would be,
and Enter in a field is refused while a control on the page is tagged careful by name. Two things are refused
everywhere: logging out, which ends the session every test starts from, and leaving the
product's site (blocked_off_site). After any test that reaches a new state the run reboots
to the start."""


TEST_CAPABILITIES = """A test here starts at a route on the site or a known screen, logged in with the
saved session (or as a new tab of it), and does up to 6 steps: click, fill, select, press a key (Enter,
Escape, Tab, arrows, Space, Backspace), go to a route, go back. A test can be run again, and the same
steps can be repeated in one test. What a test shows: where it landed (same, known or new screen); each
step's status and why it failed; the requests each step sent to the site (method, path, status); the
console errors and failed requests each step set off, with the request's address and status and the
server's error message; slow requests; storage and cookie keys
that changed (not their values); controls that appeared or went; the page's messages (validation errors,
alerts, toasts); the controls on the page at the end. What a test can't do: read the DOM, CSS, styles or
a screenshot; open a network tab or read response headers or bodies beyond the error message; clear
storage part way through a test; block, delay or mock a request; suppress an error; act as a second
user at the same time. A test can start fresh, with no saved session (a first-time visitor)."""


def outcome_for(result: dict) -> outcome.Outcome:
    """One `session.act` result as the engine's typed outcome envelope. Pure, so it is
    tested against recorded results with no browser attached.

    `accepted` is None for an action that was sent: web-recon cannot distinguish "the click
    was swallowed" from "the click hit a control that genuinely does nothing" - both leave
    the signature unchanged - so answering False would invent a fact. A control that could
    not be actuated at all (verdict not "sent") is the one honest False: it never reached
    the app."""
    action = result.get("action", "")
    # Not the same action as from the same tab (#249, #381).
    action += _START_LABEL.get(result.get("started_as"), "")
    before = result.get("screen_before", "")
    after = result.get("screen_after", "")

    if result.get("verdict") != "sent":
        return outcome.Outcome(action_id=action, effect=outcome.UNKNOWN, accepted=False,
                               state_before=before, state_after=before,
                               start_intended=result.get("intended_before", ""),
                               area=area_of(result), **coverage_of(result))

    screen_was = result.get("screen_was")
    if screen_was == "same_screen":
        effect = outcome.NONE if result.get("same_appearance") else outcome.VARIANT
    elif screen_was in ("known_screen", "new_screen"):
        effect = outcome.TRANSITION
    else:
        effect = outcome.UNKNOWN

    recovered = "recovered_to" in result
    return outcome.Outcome(
        action_id=action,
        effect=effect,
        accepted=None,
        state_before=before,
        state_after=after,
        start_intended=result.get("intended_before", ""),
        reset_attempted=recovered,
        reset_ok=result.get("recovered_ok") if recovered else None,
        latency=result.get("settle"),
        matched_prior=result.get("was_measured_before"),
        problems=problems_of(result),
        area=area_of(result),
        **coverage_of(result),
    )


def area_of(result: dict) -> str:
    """Where the test was cast to start (#328): a screen of the map by its id, or a route
    as "/#/basket" (a fragment's query left out). From the front of the result's action,
    so nothing new goes into the history the model reads. A test that never reached its
    start has no area: nothing was tried there, and counting it would make a screen the
    harness can't reach look covered."""
    if result.get("reached_target_state") is False:
        return ""
    start = (result.get("action") or "").split(" :: ", 1)[0].strip()
    if start.startswith("#"):
        start = "/" + start
    return start.split("?", 1)[0]


def coverage_of(result: dict) -> dict:
    """The controls a test used and the kinds of value it typed (#328), from the steps
    that were done. A refused, missing or failed control wasn't tried. Every step counts
    for the area the test started in; one after a step that moved to another screen is on
    that screen, which the context can't tell from here, so it only counts where the start
    screen has the same control. The token is from the name the Driver wrote: a control it
    found by part of its name ("Add to Basket" for "Add to Basket Apple Juice") doesn't
    match the map's token, and stays counted as never tried. Recording the matched name
    would put a new field into the history the model reads."""
    tried, inputs = [], []
    for step in result.get("steps") or []:
        if step.get("status") != "done" or step.get("do") not in ("click", "fill", "select", "press"):
            continue
        if step["do"] == "press" and not step.get("role"):
            continue                            # on whatever had focus: no control named
        token = ref_mod.control_token(step.get("role", ""), step.get("name", ""))
        if token not in tried:
            tried.append(token)
        if step["do"] in ("fill", "select"):
            for kind in value_kinds(step.get("value", "")):
                if [token, kind] not in inputs:
                    inputs.append([token, kind])
    return {"tried": tried, "inputs": inputs}


def _token(text: str) -> str:
    """The same problem as the same token: the first line, without the site's origin, a
    query string or an id in a path ("/api/BasketItems/13" is "/api/BasketItems/#").
    Status codes and the message stay."""
    text = (text or "").splitlines()[0] if text else ""
    text = re.sub(r"https?://[^/\s]+", "", text)
    text = re.sub(r"\?[^\s]*", "", text)
    text = re.sub(r"/\d+(?=[/\s]|$)", "/#", text)
    return " ".join(text.split())[:120]


def problems_of(result: dict) -> list[str]:
    """The test's trusted problems as tokens (#312): each console error and each failed
    request on the product's own site, from `signals` (the trusted tier, never the weak
    one). A test whose action wasn't sent, or that was stopped leaving the site, has none."""
    if result.get("verdict") != "sent" or result.get("blocked_off_site"):
        return []
    signals = result.get("signals") or {}
    found = [f"console: {_token(e)}" for e in signals.get("console_errors") or []]
    found += [f"request: {_token(r)}" for r in signals.get("failed_requests") or []]
    return list(dict.fromkeys(found))


# How many of a discovered screen's controls the Driver is shown by name (issue #158).
_DISCOVERY_CONTROLS_SHOWN = 30


def redact_history_for_model(casting_log: list[dict]) -> list[dict]:
    """The default redaction, plus a discovered screen cut down: the full record (path,
    every element) stays in output.json for feedback (#157), but would bloat every later
    prompt. The first time a screen appears in these entries, the Driver gets the controls
    it may now act on there (#158); after that, just its id."""
    from trailhound.redact import default_redact_history_for_model

    redacted = default_redact_history_for_model(casting_log)
    listed = set()
    for entry in redacted:
        found = (entry.get("result") or {}).get("discovered")
        if not found:
            continue
        short = {"id": found["id"]}
        if found["id"] not in listed and found.get("in_run_map"):
            controls = sorted(e["key"] for e in found["elements"] if not e.get("committing", True) and e.get("name"))
            short["controls"] = controls[:_DISCOVERY_CONTROLS_SHOWN]
            if len(controls) > _DISCOVERY_CONTROLS_SHOWN:
                short["controls_more"] = len(controls) - _DISCOVERY_CONTROLS_SHOWN
            listed.add(found["id"])
        entry["result"]["discovered"] = short
    # The full request log stays in output.json and the report; the Driver gets each step's
    # short form, the server's messages and the slow requests (#326), and each step its requests (#381).
    for entry in redacted:
        result = entry.get("result") or {}
        _requests_by_step(result, result.pop("request_log", None) or {})
    return redacted


# How many of a step's requests the model reads (#381); the rest are counted.
_STEP_REQUESTS = 8


def _requests_by_step(result: dict, log: dict) -> None:
    """Each step's own-site requests, as "POST /api/Users -> 201", on the step in the history
    the model reads (#381). The full request log is too long for every prompt, but without
    any of it the Driver couldn't say how many requests a double click sent. Static files
    that loaded fine aren't in it (#326)."""
    by_step: dict = {}
    for row in log.get("own_site") or []:
        status = row.get("status") if row.get("status") is not None else "no answer yet"
        by_step.setdefault(row.get("step"), []).append(f"{row.get('method')} {row.get('path')} -> {status}")
    for n, step in enumerate(result.get("steps") or [], start=1):
        rows = by_step.get(n)
        if rows:
            step["requests"] = rows[:_STEP_REQUESTS] + (
                [f"and {len(rows) - _STEP_REQUESTS} more"] if len(rows) > _STEP_REQUESTS else [])


def _start_and_steps(test: dict) -> tuple[str, list[dict]]:
    """A test's start and steps. A test cast before #310 named one (state, control) pair."""
    if "start" in test:
        return test["start"], test.get("steps") or []
    role, _, name = test.get("control_key", "").partition(":")
    return test.get("state_id", ""), [{"do": "fill" if role in live_session.TEXT_ROLES else "click",
                                       "role": role, "name": name}]


def execute_test(test: dict, test_number: int) -> dict:
    """Run one test on the live app, its start then its steps (#310), and report the
    whole transition."""
    start, steps = _start_and_steps(test)
    predicted = test["predicted_screen"]
    session = live_session.live()

    if not session.is_start(start):
        # A start that's neither a route nor a screen this run knows: a result the Driver
        # can read, not a retry.
        return outcome.attach({
            "test_number": test_number,
            "request": {"start": start, "steps": steps},
            "predicted_outcome": test["predicted_outcome"],
            "predicted_screen": predicted,
            "skipped": True,
            "skip_reason": (f"'{start}' is neither a route on the site (starting with '/' or '#') nor a screen "
                            "this run knows. Start from a route, or a screen id from carried_map."),
            "prediction_matched": False,
        }, outcome.Outcome(action_id=_test_label(test), effect=outcome.UNKNOWN, accepted=False))

    start_as = test.get("start_as") or "same_tab"
    result = session.act_steps(start, steps, start_as, test_number=test_number)
    request = {"start": start, "steps": steps}
    if start_as != "same_tab":
        request["start_as"] = start_as
    return outcome.attach({
        "test_number": test_number,
        "request": request,
        "predicted_outcome": test["predicted_outcome"],
        "predicted_screen": predicted,
        "result": result,
        "actual_screen": result["screen_was"],
        "prediction_matched": result["screen_was"] == predicted,
    }, outcome_for(result))


def save_test_media(test_numbers, out_dir: Path) -> dict[int, str]:
    """The videos of these tests, kept in out_dir/videos (#286). Empty with no live
    session or with WEB_GUI_VIDEO=off."""
    session = live_session._SESSION
    if session is None:
        return {}
    return {n: f"videos/{name}" for n, name in session.save_videos(test_numbers, out_dir / "videos").items()}


def _timing_html(result) -> str:
    """Where the test's time went (#391), and where its steps begin in the video."""
    t = result.get("timing")
    if not t or t.get("total") is None:
        return ""
    parts = [f"{t['reach']}s to reach the start"]
    if t.get("idle_watch"):
        parts.append(f"{t['idle_watch']}s watching the state idle")
    parts.append(f"{t['steps']}s on the steps, {t['settle']}s settling")
    video = (f" The steps begin {t['video_start']}s into the {t['video_length']}s video." if t.get("video_start") is not None
             else "")
    return (f'<div class="test-outcome prose-muted">took <span class="num">{esc(t["total"])}s</span> in all: '
            f'{esc(", ".join(parts))}.{video}</div>')


def _video_html(entry) -> str:
    """The test's video, when it was kept (#286). preload="none", so a report with many
    videos still opens quickly."""
    if not entry.get("video"):
        return ""
    return (f'<details class="fold"><summary>Video of this test</summary>'
            f'<video controls preload="none" width="640" src="{esc(entry["video"])}"></video></details>')


def _screen_differences(first: str, second: str) -> list[str]:
    """How the screen a replay landed on differs from the original's, from the two
    signatures (route|controls|landmarks): the route, or else what came and went."""
    if first == second:
        return []
    (route1, *rest1), (route2, *rest2) = first.split("|"), second.split("|")
    if route1 != route2:
        return [f"it landed on {route2 or '?'}, not {route1 or '?'} as before"]
    found = []
    for part, a, b in zip(("controls", "landmarks"), rest1 + ["", ""], rest2 + ["", ""]):
        gone, new = sorted(set(filter(None, a.split(";"))) - set(b.split(";"))), sorted(
            set(filter(None, b.split(";"))) - set(a.split(";")))
        if gone:
            found.append(f"{route2} no longer shows the {part} {', '.join(gone[:3])}" + (" and more" if len(gone) > 3 else ""))
        if new:
            found.append(f"{route2} now shows the {part} {', '.join(new[:3])}" + (" and more" if len(new) > 3 else ""))
    return found or [f"{route2} looked different"]


def compare_replay(original: dict, replayed: dict) -> dict:
    """Whether a test run again before its bug is reported came out the same (issue #177):
    it reached the same screen, and its trusted signals are the same. Weak signals are
    hints and are left out, as they are everywhere else. A replay that didn't reach its
    starting state, didn't send the action, or read a page that never rested can't say
    either way, so it answers None and the bug isn't reported as reproduced."""
    before, after = original.get("result") or {}, replayed.get("result") or {}
    if replayed.get("skipped") or not after:
        return {"same": None, "detail": replayed.get("skip_reason") or "the replay didn't run"}
    for name, r in (("the original", before), ("the replay", after)):
        # An original that never acted, or read an unrested page, has nothing to reproduce.
        ran = {"original_ran": False} if name == "the original" else {}
        if not r.get("reached_target_state") or r.get("verdict") != "sent":
            return {"same": None, "detail": f"{name} didn't reach its state and send the action", **ran}
        signals = r.get("signals") or {}
        if not (signals.get("settled_before") and signals.get("settled_after")):
            return {"same": None, "detail": f"{name} read a page that hadn't rested", **ran}
    differences = _screen_differences(before.get("screen_after") or "", after.get("screen_after") or "")
    keys = lambda s: {k for k in s if not k.startswith("settled_") and not k.endswith("_more")}
    first, second = before.get("signals") or {}, after.get("signals") or {}
    for key in sorted(keys(first) | keys(second)):
        gone, new = set(first.get(key, [])) - set(second.get(key, [])), set(second.get(key, [])) - set(first.get(key, []))
        if gone:
            differences.append(f"{key} no longer has {', '.join(sorted(gone))}")
        if new:
            differences.append(f"{key} now also has {', '.join(sorted(new))}")
    if differences:
        return {"same": False, "detail": "; ".join(differences)}
    return {"same": True, "detail": "same screen and trusted signals"}


def fetch_happy_day_example(adapter: SUTAdapter) -> dict:
    """One real action at the live app, so onboarding starts from a fact: the first control
    on the entry state, actuated and classified. Proves the machinery (reach, actuate,
    observe, recover) works before a single API call is spent proposing tests."""
    # Empty since #285: for a web run, one click on the start page told the Driver nothing
    # and cost a test and evidence tokens on every call. check_ready already proves the
    # machinery (the server check and the start page) before anything is spent.
    return {"request": {}, "response": {}}


def _test_label(test: dict) -> str:
    """'st05 :: button:Checkout > textbox:Coupon = '-1'': where a test starts and its steps."""
    start, steps = _start_and_steps(test)
    return f"{start} :: " + " > ".join(live_session._step_label(s) for s in steps)


# How a test that didn't start as the saved tab reads in a label.
_START_LABEL = {"new_tab": " (as a new tab)", "fresh": " (fresh, no saved session)"}


def describe_test_for_log(test: dict) -> str:
    tab = _START_LABEL.get(test.get("start_as"), "")
    return f"{_test_label(test)}{tab} -> predicting {test['predicted_screen']}"


def describe_result_for_log(result: dict) -> str:
    if result.get("skipped"):
        return f"SKIPPED - {result['skip_reason']}"
    detail = result["result"]
    if detail.get("verdict") != "sent":
        steps = detail.get("steps") or []
        why = "; ".join(f"{live_session._step_label(s)}: {s['status'].replace('_', ' ')}" for s in steps
                        if s.get("status") != "done")
        return f"NOT RUN - {why or 'the test never reached its start'}"
    line = f"{detail['screen_was']} (click {detail.get('click', '?')}s, settled {detail['settle']}s)"
    if (detail.get("timing") or {}).get("total") is not None:
        line += f", {detail['timing']['total']}s in all"
    if detail.get("covered_by"):
        line += f", clicked through {detail['covered_by']} on top of it"
    if detail.get("blocked_off_site"):
        line += f", stopped from leaving the site for {detail['blocked_off_site'][0]}"
    signals = detail.get("signals") or {}
    noted = [f"{len(signals['console_errors'])} console error(s)" if signals.get("console_errors") else "",
             f"{len(signals['failed_requests'])} failed request(s)" if signals.get("failed_requests") else "",
             "storage changed" if any(k in signals for k in ("storage_added", "storage_removed", "storage_changed")) else "",
             "UNSETTLED" if signals and not (signals.get("settled_before", True) and signals.get("settled_after", True)) else "",
             f"{sum(len(v) for v in detail['signals_weak'].values() if isinstance(v, list))} weak signal(s)" if detail.get("signals_weak") else "",
             f"page messages on {sum(1 for s in detail.get('steps') or [] if (s.get('page_says') or {}).get('shown'))} step(s)"
             if any((s.get("page_says") or {}).get("shown") for s in detail.get("steps") or []) else ""]
    if any(noted):
        line += ", " + ", ".join(n for n in noted if n)
    if not detail.get("reached_target_state"):
        line = "[path drifted before the control] " + line
    if "recovered_to" in detail:
        line += f", recovered {'ok' if detail.get('recovered_ok') else 'ELSEWHERE'}"
    return line


# The oracle. With WEB_GUI_PRODUCT naming a product in the wiki (e.g. "juice-shop"),
# it's that product's seeded oracle (issue #138): the heuristic library and the
# product's facts run through the FEW HICCUPPS seeds, top ORACLE_TOP_N taking turns
# across seeds; WEB_GUI_FEATURES (comma-separated library tags, e.g. "security") is
# then the run's focus, which gets up to a third of the slots (#278). Without a
# product, it's library heuristics only (issue #128): those that fit a GUI, with the
# ones matching WEB_GUI_FEATURES (e.g. "login,search") ranked first. #111 showed a ranked oracle makes the Driver
# find what it lists sooner. WEB_GUI_ORACLE=off leaves it out, for comparing runs.
ORACLE_TOP_N = 15
ORACLE_PRODUCT = os.environ.get("WEB_GUI_PRODUCT", "").strip()
ORACLE_FEATURES = tuple(f.strip() for f in os.environ.get("WEB_GUI_FEATURES", "").split(",") if f.strip())
ORACLE_RANKED = (build_product_ideas(ORACLE_PRODUCT, limit=ORACLE_TOP_N, focus=ORACLE_FEATURES)
                 if ORACLE_PRODUCT else build_ranked_ideas(
    "web_gui", surfaces=("gui",), features=ORACLE_FEATURES, heuristic_limit=ORACLE_TOP_N,
))["ranked_ideas"]
ORACLE_ENABLED = os.environ.get("WEB_GUI_ORACLE", "").strip().lower() != "off"


CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": "Propose a batch of tests against the live web app: each a start and a few steps.",
    "input_schema": {
        "type": "object",
        "properties": {
            "give_up": {"type": "boolean",
                        "description": "Set true only if you have no more good ideas worth proposing this round."},
            "reasoning": {"type": "string", "description": CASTING_REASONING_DESCRIPTION},
            "candidate_tests": {
                "type": "array",
                "description": "Each test is EITHER tied to a hypothesis (linked_hypothesis = the "
                               "theory in full) OR a pure probe (linked_hypothesis = empty string).",
                "items": {
                    "type": "object",
                    "properties": {
                        "linked_hypothesis": {"type": "string"},
                        "oracle_claim_id": {
                            "type": "string",
                            "description": (
                                "If this test targets one of the ideas in 'oracle_ranked' in your evidence, "
                                "copy its id exactly as shown there (e.g. 'heuristic:boundary_edges'). "
                                "Otherwise an empty string. Never put a gap or observation id here."
                            ),
                        },
                        "start": {"type": "string",
                                  "description": "Where the test starts: a route on the site (e.g. '/#/basket', "
                                                 "'/'), or a screen id from carried_map or discovered this run "
                                                 "(e.g. 'st05')."},
                        "steps": {
                            "type": "array",
                            "description": f"What to do there, in order, 1 to {live_session.MAX_STEPS} steps.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "do": {"type": "string", "enum": list(live_session.STEP_KINDS)},
                                    "role": {"type": "string",
                                             "description": "The element's role, for click, fill and select, and "
                                                            "for press when the key goes to a named element "
                                                            "(the part before the first colon in 'role:name')."},
                                    "name": {"type": "string",
                                             "description": "The element's name, for click, fill and select, and "
                                                            "press with a role. Empty for an element without one "
                                                            "(an image, an icon)."},
                                    "nth": {"type": "integer",
                                            "description": "Which one, when several elements on the page have this "
                                                           "role and name (page_controls shows '(x12)'). 1 if left out."},
                                    "value": {"type": "string",
                                              "description": "What to type (fill), the option (select), the key "
                                                             f"(press: {', '.join(live_session.PRESS_KEYS)}), or "
                                                             "the route (goto). Empty otherwise."},
                                },
                                "required": ["do"],
                            },
                        },
                        "start_as": {"type": "string", "enum": list(live_session.START_AS),
                                     "description": "Optional, 'same_tab' if left out. 'new_tab' starts the test "
                                                    "as a new tab of the logged-in browser (see NEW TAB); 'fresh' "
                                                    "with no saved session, as a first-time visitor (see FRESH "
                                                    "START). Both only with a saved session."},
                        "predicted_screen": {"type": "string", "enum": list(PREDICTIONS),
                                             "description": "Where the last step leaves you: 'same_screen' - the "
                                                            "screen you started on; 'known_screen' - a state "
                                                            "already in the map or seen this run; 'new_screen' - "
                                                            "somewhere not mapped yet."},
                        "predicted_outcome": {"type": "string",
                                              "description": "What you predict happens and why, in words."},
                    },
                    "required": ["linked_hypothesis", "oracle_claim_id", "start", "steps",
                                 "predicted_screen", "predicted_outcome"],
                },
            },
        },
        "required": ["give_up", "reasoning", "candidate_tests"],
    },
}


def casting_system_prompt(test_budget: int, is_first_round: bool) -> str:
    if is_first_round:
        context = """You have not acted on this app yet. You have a guide to its screens, their
routes and what's on them (carried_map), from an earlier recon, and the oracle's ideas of what
should hold (oracle_ranked). Before proposing anything, think about what a product of this kind
normally does and what goes wrong in it: wrong numbers, inputs it shouldn't accept, state that
gets lost, errors behind an ordinary action, a place you can't get back from. Use the oracle's
ideas and the guide to decide what is worth checking first. State this reasoning explicitly."""
    else:
        context = f"""You now have real transitions. {PRIOR_FEEDBACK_GUIDE}
Remember that repeating an action is a real experiment: the same control landing somewhere different on a second visit, or a state
registered as new twice, are both findings. Briefly state what this app has shown you so far."""

    return f"""You are testing a live web application the way a tester does: use it, push on it,
and notice anything that doesn't behave the way it should. Each test starts from a route or a
screen and does a few steps on the live page (see WHAT A TEST IS).

{context}

In one round, propose a BATCH of tests - up to {test_budget} total:
1. Candidate hypotheses: specific, falsifiable theories about what the product does or fails to
   do. For each, propose 1-2 tests that would check it, with a predicted_screen and a
   predicted_outcome. Set linked_hypothesis to the full theory text.
2. Pure probes: tests not tied to any theory. Predict what you honestly think happens and set
   linked_hypothesis to an empty string.

Every test runs before you see any result, each from a fresh browser, so a test is a sequence of
its own: what builds on what goes in one test. Propose fewer, sharper tests rather than filling
the budget, and set give_up to true if you have no good ideas left.

{SAFETY_NOTE}

Call submit_casting_round with your answer."""


def _step_errors(where: str, step) -> list[str]:
    if not isinstance(step, dict):
        return [f"{where} must be an object"]
    kind = step.get("do")
    if kind not in live_session.STEP_KINDS:
        return [f"{where}.do must be one of: {', '.join(live_session.STEP_KINDS)}"]
    errors = []
    if kind in ("click", "fill", "select") or (kind == "press" and (step.get("role") or step.get("name"))):
        if not isinstance(step.get("role"), str) or not step["role"].strip():
            errors.append(f"{where} ({kind}) needs a 'role'" + (" when it names an element" if kind == "press" else ""))
        if not isinstance(step.get("name", ""), str):
            errors.append(f"{where}.name must be text (empty for an element without a name)")
        if "nth" in step and (not isinstance(step["nth"], int) or isinstance(step["nth"], bool) or step["nth"] < 1):
            errors.append(f"{where}.nth must be a whole number from 1")
    if kind in ("fill", "select", "goto") and not isinstance(step.get("value"), str):
        errors.append(f"{where} ({kind}) needs a 'value'")
    if kind == "press" and "nth" in step and not (step.get("role") or step.get("name")):
        errors.append(f"{where} (press) has 'nth' but no element: give it a 'role' and 'name'")
    if kind == "press" and step.get("value") not in live_session.PRESS_KEYS:
        errors.append(f"{where} (press) needs a key as its value, one of: {', '.join(live_session.PRESS_KEYS)}")
    if kind == "goto" and not str(step.get("value", "")).startswith(("/", "#")):
        errors.append(f"{where} (goto) needs a route on the site as its value, starting with '/' or '#'")
    return errors


def validate_casting_response(data) -> list[str]:
    """The shape only (#310). Where a test starts and what it touches aren't checked
    against the map: the map is a guide, and a step on something that isn't on the page
    comes back as a result, not a retry."""
    errors, tests = casting_envelope_errors(data)
    if not isinstance(tests, list) or not tests:
        return errors
    for i, test in enumerate(tests):
        if not isinstance(test, dict):
            errors.append(f"candidate_tests[{i}] must be an object")
            continue
        for key in ("linked_hypothesis", "oracle_claim_id", "start", "predicted_screen", "predicted_outcome"):
            if key not in test:
                errors.append(f"candidate_tests[{i}] missing '{key}'")
            elif not isinstance(test[key], str):
                errors.append(f"candidate_tests[{i}].{key} must be a string")
        if isinstance(test.get("start"), str) and not test["start"].strip():
            errors.append(f"candidate_tests[{i}].start must name a route or a screen")
        steps = test.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= live_session.MAX_STEPS:
            errors.append(f"candidate_tests[{i}].steps must be a list of 1 to {live_session.MAX_STEPS} steps")
        else:
            for j, step in enumerate(steps):
                errors.extend(_step_errors(f"candidate_tests[{i}].steps[{j}]", step))
        if test.get("predicted_screen") not in PREDICTIONS:
            errors.append(f"candidate_tests[{i}].predicted_screen must be one of: {', '.join(PREDICTIONS)}")
        start_as = test.get("start_as", "same_tab")
        if start_as not in live_session.START_AS:
            errors.append(f"candidate_tests[{i}].start_as must be one of: {', '.join(live_session.START_AS)}")
        elif start_as in ("new_tab", "fresh") and live_session._SESSION is not None and not live_session.has_session():
            errors.append(f"candidate_tests[{i}].start_as is '{start_as}', but this run has no saved session, "
                          "so it starts the same as any test. Leave start_as out.")
    return errors


def _screen_badge(screen_was) -> str:
    if screen_was == "new_screen":
        return badge("new state", "warn")
    if screen_was == "known_screen":
        return badge("known state", "good")
    return badge("no change", "neutral")


def _signals_html(result) -> str:
    """Both tiers of the signal diff (issue #143): the trusted ones as facts, the weak
    ones marked as hints, so a reader of the report sees the same distinction the
    Driver is told about."""
    signals = result.get("signals") or {}
    if not signals:
        return ""
    def rows(tier):
        # A list cut at _MAX_SIGNAL_ITEMS carries a <key>_more count; show it, or the
        # report looks complete when it isn't (Copilot on #152).
        return "".join(
            f"<li><code>{esc(key)}</code>: {esc(', '.join(map(str, value)))}"
            + (f" <span class=\"prose-muted\">and {esc(tier[key + '_more'])} more</span>" if tier.get(key + "_more") else "")
            + "</li>"
            for key, value in tier.items() if isinstance(value, list))
    settled = signals.get("settled_before", True) and signals.get("settled_after", True)
    flag = "" if settled else f" {badge('read from an unsettled page', 'warn')}"
    trusted, weak = rows(signals), rows(result.get("signals_weak") or {})
    if not (trusted or weak or flag):
        return ""
    trusted_html = f"<p><strong>Signals (trusted)</strong>{flag}</p><ul>{trusted}</ul>" if (trusted or flag) else ""
    weak_html = (f'<p><strong>Weak signals</strong> <span class="prose-muted">hints only, not evidence</span></p>'
                 f"<ul>{weak}</ul>") if weak else ""
    return f'<details class="fold"><summary>Signals</summary>{trusted_html}{weak_html}</details>'


def render_test_entry(entry) -> str:
    if not entry:
        return ""
    request = entry.get("request", {})
    linked = entry.get("linked_hypothesis")
    linked_html = f"<strong>Hypothesis:</strong> {esc(linked)}" if linked else (
        '<span class="probe-label">Probe</span> (no linked hypothesis)')
    number_html = (f'<span class="test-number">Test #{esc(entry.get("test_number"))}</span>'
                   if entry.get("test_number") is not None else "")
    tab = _START_LABEL.get(request.get("start_as"), "")
    label = (_test_label(request) if "start" in request
             else f"{request.get('state')} :: {request.get('control')}")   # a run from before #310
    action_html = f'<span class="test-number">{esc(label)}{tab}</span>'

    if entry.get("skipped"):
        return f"""
        <article class="test test-skipped">
          <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
          <div class="test-outcome">{badge('skipped', 'warn')} {inline_markdown(entry.get('skip_reason'))}</div>
        </article>
        """

    result = entry.get("result", {})
    matched = entry.get("prediction_matched")
    if result.get("verdict") != "sent":
        return f"""
        <article class="test">
          <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
          <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
            {_screen_badge(entry.get('predicted_screen'))}</div>
          <div class="test-outcome">{badge('control could not be actuated', 'bad')}</div>
          {_signals_html(result)}
          {_request_log_html(result)}
          {_video_html(entry)}
        </article>
        """

    recovered = result.get("recovered_to")
    recovered_html = (f'<span class="sep">&middot;</span> recovered '
                      f'{bool_badge(result.get("recovered_ok"), "to start", "elsewhere")}') if recovered else ""
    drift_html = ("" if result.get("reached_target_state")
                  else f' {badge("path drifted", "warn")}')
    return f"""
    <article class="test">
      <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
      {_steps_html(result.get("steps"))}
      <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
        {_screen_badge(entry.get('predicted_screen'))}</div>
      <div class="test-outcome">
        reached {_screen_badge(entry.get('actual_screen'))}{drift_html}
        <span class="sep">&middot;</span> prediction {bool_badge(matched, 'matched', 'missed')}
        {recovered_html}
      </div>
      <div class="test-outcome prose-muted">click took <span class="num">{esc(result.get('click', '?'))}s</span>, settled in <span class="num">{esc(result.get('settle'))}s</span>{f", clicked through {esc(result['covered_by'])} on top of it" if result.get('covered_by') else ""}</div>
      {f'<div class="test-outcome">{badge("stopped from leaving the site", "warn")} {esc(", ".join(result["blocked_off_site"]))}</div>' if result.get("blocked_off_site") else ""}
      {_timing_html(result)}
      {_signals_html(result)}
      {_request_log_html(result)}
      {_video_html(entry)}
    </article>
    """


def _step_signals_html(step) -> str:
    """What one step set off (#326): its trusted errors, the server's messages, slow requests,
    and what the page started and stopped telling the user (#351), a weak one marked as a hint."""
    parts = [f"{key.replace('_', ' ')}: {', '.join(map(str, value))}"
             for key, value in (step.get("signals") or {}).items() if isinstance(value, list)]
    parts += [f"the server said {m}" for m in step.get("server_said") or []]
    parts += [f"slow: {s}" for s in step.get("slow") or []]
    for key, hint in (("page_says", ""), ("page_says_weak", " (a hint)")):
        says = step.get(key) or {}
        parts += [f"the page showed {m}{hint}" for m in says.get("shown") or []]
        parts += [f"the page stopped showing {m}{hint}" for m in says.get("gone") or []]
    return f'<div class="prose-muted">{esc("; ".join(parts))}</div>' if parts else ""


def _request_log_html(result) -> str:
    """The test's requests to the product's own site, step by step (#326), folded."""
    log = result.get("request_log") or {}
    rows = "".join(
        f"<tr><td>{esc(r.get('step'))}</td><td>{esc(r.get('method'))}</td><td><code>{esc(r.get('path'))}</code></td>"
        f"<td>{esc(r.get('status'))}</td><td>{esc(r.get('ms', ''))}</td><td>{esc(r.get('message', ''))}</td></tr>"
        for r in log.get("own_site") or [])
    if not rows and not (log.get("third_party") or log.get("static_files")):
        return ""
    counted = [f"{log['own_site_more']} more on the site" if log.get("own_site_more") else "",
               f"{log['static_files']} static file(s) that loaded fine" if log.get("static_files") else "",
               f"{log['third_party']} request(s) to other sites" if log.get("third_party") else ""]
    counted = [c for c in counted if c]
    others = (f'<p class="prose-muted">And {esc(", ".join(counted))}, counted only.</p>' if counted else "")
    table = (f"<table><thead><tr><th>Step</th><th>Method</th><th>Path</th><th>Status</th><th>ms</th>"
             f"<th>What the server said</th></tr></thead><tbody>{rows}</tbody></table>" if rows else "")
    return f'<details class="fold"><summary>Requests</summary>{table}{others}</details>'


def _steps_html(steps) -> str:
    """Each step and what came of it (#310), when one didn't simply get done or set
    something off (#326)."""
    if not steps or all(s.get("status") == "done" and not _step_signals_html(s) for s in steps):
        return ""
    kinds = {"done": "good", "not_found": "warn", "refused": "warn", "failed": "bad"}
    rows = "".join(f"<li>{esc(live_session._step_label(s))} {badge(s.get('status', '?').replace('_', ' '), kinds.get(s.get('status'), 'neutral'))}"
                   f"{(' ' + esc(s['detail'])) if s.get('detail') else ''}{_step_signals_html(s)}</li>" for s in steps)
    return f'<ul class="line-list">{rows}</ul>'


def render_onboarding_section(api_schema, onboarding_extra, happy_day_example) -> str:
    extra = onboarding_extra or {}
    happy_request = (happy_day_example or {}).get("request", {})
    happy_response = (happy_day_example or {}).get("response", {})
    # Runs before #285 had one; a web run has none now.
    happy_html = "" if not (happy_request or happy_response) else f"""
    <div class="exhibit">
      <h3>Happy-day example</h3>
      <p class="eyebrow">Request</p>
      {render_json_block(happy_request)}
      <p class="eyebrow">Response</p>
      {render_json_block(happy_response)}
    </div>
    """
    map_html = ""
    if extra.get("carried_map"):
        map_html = f"""
    <details class="fold exhibit">
      <summary>Carried map (a guide to the screens)</summary>
      <pre class="schema-doc">{esc(extra['carried_map'])}</pre>
    </details>
    """
    earlier_html = ""
    if extra.get("earlier_discoveries"):
        routes = extra.get("earlier_discovery_routes") or {}
        named = lambda sid: f"{routes[sid]} ({sid})" if sid in routes else sid
        rows = "".join(f"<li><strong>{esc(k.replace('_', ' '))}:</strong> {esc(', '.join(named(s) for s in v))}</li>"
                       for k, v in extra["earlier_discoveries"].items())
        earlier_html = f"""
    <div class="exhibit">
      <h3>Screens from earlier runs</h3>
      <p class="prose-muted">Screens earlier runs discovered, each replayed once at the start of this run.
        The ones that landed where they did before joined the map (#159).</p>
      <ul>{rows}</ul>
    </div>
    """
    baseline_html = ""
    if extra.get("baseline"):
        warned = str(extra["baseline"]).startswith("WARNING")
        baseline_html = f"""
    <div class="exhibit">
      <h3>Where the run started {badge('the start page differs from the map', 'warn') if warned
                                    else badge('the start page matches the map', 'good')}</h3>
      <pre class="schema-doc">{esc(extra['baseline'])}</pre>
    </div>
    """
    if extra.get("testing_mode"):
        # How far the run was allowed to go (#299), first, so nobody misses it.
        baseline_html = (f'<p class="prose"><strong>{esc(extra["testing_mode"])}</strong></p>'
                         + baseline_html)
    # The schema doc and the map are folded, like the oracle list: background the Driver
    # was given, each hundreds of lines, which pushed the checkpoints far down (#251).
    return f"""
    <details class="fold exhibit">
      <summary>What the Driver was told</summary>
      <pre class="schema-doc">{esc(api_schema)}</pre>
    </details>
    {map_html}
    {baseline_html}
    {earlier_html}
    {render_oracle_ranked(extra.get('oracle_ranked'))}
    {happy_html}
    """


ADAPTER = SUTAdapter(
    name="web_gui",
    display_name="Web GUI (live browser)",
    api_schema_doc=API_SCHEMA_DOC,
    # Mutable on purpose and filled by check_ready: the carried map and where the run
    # actually started are statements about the reference as loaded and the SUT as found,
    # not constants to write down here.
    onboarding_extra={"safety_note": SAFETY_NOTE, **({"oracle_ranked": ORACLE_RANKED} if ORACLE_ENABLED else {})},
    casting_tool_schema=CASTING_TOOL,
    casting_system_prompt=casting_system_prompt,
    validate_casting_response=validate_casting_response,
    casting_max_tokens=lambda budget: 3072 if budget <= 6 else 4096,
    execute_test=execute_test,
    check_sut_ready=live_session.check_ready,
    fetch_happy_day_example=fetch_happy_day_example,
    describe_test_for_log=describe_test_for_log,
    describe_result_for_log=describe_result_for_log,
    redact_history_for_model=redact_history_for_model,
    compare_replay=compare_replay,
    score_run=score_run,
    save_test_media=save_test_media,
    before_replay=live_session.replay_blocker,
    render_test_entry=render_test_entry,
    render_onboarding_section=render_onboarding_section,
    report_title="Web GUI - live browser exploration",
    test_capabilities=TEST_CAPABILITIES,
    # Modest budgets: every action is a real browser reach + actuate + reboot taking a
    # second or more, and the action space is only as large as the carried map.
    default_max_checkpoints=3,
    default_first_round_test_budget=6,
    default_test_budget=5,
)
