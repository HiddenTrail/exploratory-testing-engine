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
    respond).
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
         A hint for a next test, never evidence for a claim on its own.
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
delete or type into anything but a search box comes back "refused". Two things are refused
everywhere: logging out, which ends the session every test starts from, and leaving the
product's site (blocked_off_site). After any test that reaches a new state the run reboots
to the start."""


def outcome_for(result: dict) -> outcome.Outcome:
    """One `session.act` result as the engine's typed outcome envelope. Pure, so it is
    tested against recorded results with no browser attached.

    `accepted` is None for an action that was sent: web-recon cannot distinguish "the click
    was swallowed" from "the click hit a control that genuinely does nothing" - both leave
    the signature unchanged - so answering False would invent a fact. A control that could
    not be actuated at all (verdict not "sent") is the one honest False: it never reached
    the app."""
    action = result.get("action", "")
    if result.get("started_as") == "new_tab":   # not the same action as from the same tab (#249)
        action += " (as a new tab)"
    before = result.get("screen_before", "")
    after = result.get("screen_after", "")

    if result.get("verdict") != "sent":
        return outcome.Outcome(action_id=action, effect=outcome.UNKNOWN, accepted=False,
                               state_before=before, state_after=before,
                               start_intended=result.get("intended_before", ""))

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
    )


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
    return redacted


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


def describe_test_for_log(test: dict) -> str:
    tab = " (as a new tab)" if test.get("start_as") == "new_tab" else ""
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
    if detail.get("covered_by"):
        line += f", clicked through {detail['covered_by']} on top of it"
    if detail.get("blocked_off_site"):
        line += f", stopped from leaving the site for {detail['blocked_off_site'][0]}"
    signals = detail.get("signals") or {}
    noted = [f"{len(signals['console_errors'])} console error(s)" if signals.get("console_errors") else "",
             f"{len(signals['failed_requests'])} failed request(s)" if signals.get("failed_requests") else "",
             "storage changed" if any(k in signals for k in ("storage_added", "storage_removed", "storage_changed")) else "",
             "UNSETTLED" if signals and not (signals.get("settled_before", True) and signals.get("settled_after", True)) else "",
             f"{sum(len(v) for v in detail['signals_weak'].values() if isinstance(v, list))} weak signal(s)" if detail.get("signals_weak") else ""]
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
                                             "description": "The element's role, for click, fill and select "
                                                            "(the part before the first colon in 'role:name')."},
                                    "name": {"type": "string",
                                             "description": "The element's name, for click, fill and select. "
                                                            "Empty for an element without one (an image, an icon)."},
                                    "nth": {"type": "integer",
                                            "description": "Which one, when several elements on the page have this "
                                                           "role and name (page_controls shows '(x12)'). 1 if left out."},
                                    "value": {"type": "string",
                                              "description": "What to type (fill), the option (select), or the "
                                                             "route (goto). Empty otherwise."},
                                },
                                "required": ["do"],
                            },
                        },
                        "start_as": {"type": "string", "enum": list(live_session.START_AS),
                                     "description": "Optional, 'same_tab' if left out. 'new_tab' starts the test "
                                                    "as a new tab of the logged-in browser (see NEW TAB). Only "
                                                    "with a saved session."},
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
    if kind in ("click", "fill", "select"):
        if not isinstance(step.get("role"), str) or not step["role"].strip():
            errors.append(f"{where} ({kind}) needs a 'role'")
        if not isinstance(step.get("name", ""), str):
            errors.append(f"{where}.name must be text (empty for an element without a name)")
        if "nth" in step and (not isinstance(step["nth"], int) or isinstance(step["nth"], bool) or step["nth"] < 1):
            errors.append(f"{where}.nth must be a whole number from 1")
    if kind in ("fill", "select", "goto") and not isinstance(step.get("value"), str):
        errors.append(f"{where} ({kind}) needs a 'value'")
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
        elif start_as == "new_tab" and live_session._SESSION is not None and not live_session.has_session():
            errors.append(f"candidate_tests[{i}].start_as is 'new_tab', but this run has no saved session, "
                          "so a new tab is the same as any test. Leave start_as out.")
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
    tab = " (as a new tab)" if request.get("start_as") == "new_tab" else ""
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
      {_signals_html(result)}
      {_video_html(entry)}
    </article>
    """


def _steps_html(steps) -> str:
    """Each step and what came of it (#310), when one didn't simply get done."""
    if not steps or all(s.get("status") == "done" for s in steps):
        return ""
    kinds = {"done": "good", "not_found": "warn", "refused": "warn", "failed": "bad"}
    rows = "".join(f"<li>{esc(live_session._step_label(s))} {badge(s.get('status', '?').replace('_', ' '), kinds.get(s.get('status'), 'neutral'))}"
                   f"{(' ' + esc(s['detail'])) if s.get('detail') else ''}</li>" for s in steps)
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
    # Modest budgets: every action is a real browser reach + actuate + reboot taking a
    # second or more, and the action space is only as large as the carried map.
    default_max_checkpoints=3,
    default_first_round_test_budget=6,
    default_test_budget=5,
)
