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

from engine import outcome
from engine.adapter import SUTAdapter
from engine.tools import CASTING_REASONING_DESCRIPTION, PRIOR_FEEDBACK_GUIDE, casting_envelope_errors
from engine.adapters.web_gui import reference as ref_mod
from engine.adapters.web_gui import session as live_session
from engine.adapters.web_gui.reference import PREDICTIONS
from engine.ontology.oracle_creator import build_ranked_ideas
from engine.report import badge, bool_badge, esc, inline_markdown, render_json_block, render_oracle_ranked


API_SCHEMA_DOC = """A web application, explored through a browser and observed by web-recon's
state signature. There is no API response body to read: a "state" is a view of the app,
identified by its URL route, the set of interactive controls on it, and its landmark
headings - body text and map position are treated as the same state, a variant.

THE ACTION SPACE. You may ask for exactly one named action per test: a (state, control)
pair drawn from the carried map, which is given to you as `carried_map` in the onboarding
evidence. Each line there reads `<state_id> :: <role>:<name>` - that pair, verbatim, is a
valid action. You cannot supply a CSS selector, a coordinate, or a control not on that map:
the map is the whole action space, and it holds only controls an earlier read-only recon
pass found and cleared as non-committing (nothing that deletes, buys, submits or sends).
An action first navigates to its state by replaying the recon's path, then actuates the
control.

WHAT YOU GET BACK, per test:
  screen_before / screen_after: the state signature before and after the control was actuated.
  screen_was: "same_screen" (the signature did not change), "known_screen" (it changed to a
    state already in the carried map or already seen this run), or "new_screen" (somewhere
    neither applies to - a state the recon never mapped).
  same_appearance: true only when screen_was is same_screen AND the body/text did not move
    either - i.e. the control did nothing observable at all (a candidate dead control).
  was_measured_before: true if the state landed on was in the carried map.
  first_sight_this_run: true the first time this run reaches that state.
  reached_target_state: whether replaying the path actually arrived at the state you named
    before the control was actuated - false means the app drifted and the reading is suspect.
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
  covered_by: present when something else was on top of the control, for example
         "dialog 'cookieconsent'". The harness sent the click to the control anyway,
         which a real user couldn't do without moving the cover first.
  verdict: "sent" normally, or "not_actuated" if the control could not be actuated at all.
  recovered_to: the signature the run rebooted to after an action that reached a new state,
    so the next test starts clean; recovered_ok says whether that matched the start state.

WHAT COUNTS AS AN ANOMALY HERE. Claims the exploration can actually check: a control that
changes nothing (same_screen with same_appearance), a control that reaches a new state the
way back does not restore (recovered_ok false), two controls that land on the same state, a
state whose identity is unstable across visits, or a control the recon mapped that no longer
actuates. A control landing on new_screen reached somewhere the recon did not map, which is
worth saying; a carried state you can no longer reach is drift in the app since it was
mapped - a real finding, but about the map, so label it as such."""


SAFETY_NOTE = """This run is read-only. The action space is the set of (state, control) pairs
an earlier recon pass cleared as non-committing; the Driver can only pick from that map, so
there is no way to name a control that submits a form, deletes, buys or sends. After any
action that reaches a new state the run reboots to the start, so a stray navigation never
compounds. If a control unexpectedly leaves the app or opens something committing, the
correct reading is to report it, not to explore it."""


def outcome_for(result: dict) -> outcome.Outcome:
    """One `session.act` result as the engine's typed outcome envelope. Pure, so it is
    tested against recorded results with no browser attached.

    `accepted` is None for an action that was sent: web-recon cannot distinguish "the click
    was swallowed" from "the click hit a control that genuinely does nothing" - both leave
    the signature unchanged - so answering False would invent a fact. A control that could
    not be actuated at all (verdict not "sent") is the one honest False: it never reached
    the app."""
    action = result.get("action", "")
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
    )


def execute_test(test: dict, test_number: int) -> dict:
    """Actuate one (state, control) at the live app and report the whole transition."""
    state_id = test["state_id"]
    control_key = test["control_key"]
    predicted = test["predicted_screen"]
    session = live_session.live()

    if (state_id, control_key) not in session.reference.pairs():
        # Unreachable through validation, and kept anyway: a pair not in the carried map has
        # no vetted path or control behind it, so a refused test the Driver can read beats a
        # KeyError mid-run.
        return outcome.attach({
            "test_number": test_number,
            "request": {"state": state_id, "control": control_key},
            "predicted_outcome": test["predicted_outcome"],
            "predicted_screen": predicted,
            "skipped": True,
            "skip_reason": f"{state_id} :: {control_key} is not a pair in the carried map.",
            "prediction_matched": False,
        }, outcome.Outcome(action_id=f"{state_id} :: {control_key}",
                           effect=outcome.UNKNOWN, accepted=False))

    result = session.act(state_id, control_key)
    return outcome.attach({
        "test_number": test_number,
        "request": {"state": state_id, "control": control_key},
        "predicted_outcome": test["predicted_outcome"],
        "predicted_screen": predicted,
        "result": result,
        "actual_screen": result["screen_was"],
        "prediction_matched": result["screen_was"] == predicted,
    }, outcome_for(result))


def fetch_happy_day_example(adapter: SUTAdapter) -> dict:
    """One real action at the live app, so onboarding starts from a fact: the first control
    on the entry state, actuated and classified. Proves the machinery (reach, actuate,
    observe, recover) works before a single API call is spent proposing tests."""
    session = live_session.live()
    ref = session.reference
    entry = ref.entry()
    ordered = sorted(ref.pairs())
    pair = next((p for p in ordered if p[0] == entry), ordered[0])
    return {"request": {"state": pair[0], "control": pair[1]}, "response": session.act(*pair)}


def describe_test_for_log(test: dict) -> str:
    return f"{test['state_id']} :: {test['control_key']} -> predicting {test['predicted_screen']}"


def describe_result_for_log(result: dict) -> str:
    if result.get("skipped"):
        return f"SKIPPED - {result['skip_reason']}"
    detail = result["result"]
    if detail.get("verdict") != "sent":
        return f"NOT ACTUATED - the control could not be clicked"
    line = f"{detail['screen_was']} (click {detail.get('click', '?')}s, settled {detail['settle']}s)"
    if detail.get("covered_by"):
        line += f", clicked through {detail['covered_by']} on top of it"
    signals = detail.get("signals") or {}
    noted = [f"{len(signals['console_errors'])} console error(s)" if signals.get("console_errors") else "",
             f"{len(signals['failed_requests'])} failed request(s)" if signals.get("failed_requests") else "",
             "storage changed" if any(k in signals for k in ("storage_added", "storage_removed", "storage_changed")) else "",
             "UNSETTLED" if signals and not (signals.get("settled_before", True) and signals.get("settled_after", True)) else "",
             f"{sum(len(v) for v in detail['signals_weak'].values())} weak signal(s)" if detail.get("signals_weak") else ""]
    if any(noted):
        line += ", " + ", ".join(n for n in noted if n)
    if not detail.get("reached_target_state"):
        line = "[path drifted before the control] " + line
    if "recovered_to" in detail:
        line += f", recovered {'ok' if detail.get('recovered_ok') else 'ELSEWHERE'}"
    return line


# The oracle (issue #114). web_gui has no product-specific claims yet, so
# build_ranked_ideas gives heuristics from the library (engine/ontology/heuristics/,
# issue #128): the ones that fit a GUI, with the ones matching WEB_GUI_FEATURES
# (comma-separated library tags, e.g. "login,search,list-paging") ranked first,
# capped so the prompt stays small. #111 showed a ranked oracle makes the Driver
# find what it lists sooner. WEB_GUI_ORACLE=off leaves it out, for comparing runs.
ORACLE_HEURISTICS_TOP_N = 15
ORACLE_FEATURES = tuple(f.strip() for f in os.environ.get("WEB_GUI_FEATURES", "").split(",") if f.strip())
ORACLE_RANKED = build_ranked_ideas(
    "web_gui", surfaces=("gui",), features=ORACLE_FEATURES, heuristic_limit=ORACLE_HEURISTICS_TOP_N,
)["ranked_ideas"]
ORACLE_ENABLED = os.environ.get("WEB_GUI_ORACLE", "").strip().lower() != "off"


CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": "Propose a batch of (state, control) actions against the live web app.",
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
                        "state_id": {"type": "string",
                                     "description": "The state to act on - a state id from carried_map (e.g. 'st01')."},
                        "control_key": {"type": "string",
                                        "description": "The control to actuate on that state - a 'role:name' key "
                                                       "listed under that state in carried_map."},
                        "predicted_screen": {"type": "string", "enum": list(PREDICTIONS),
                                             "description": "'same_screen' - nothing changes; 'known_screen' - it "
                                                            "goes to a state already in the map or seen this run; "
                                                            "'new_screen' - somewhere not mapped yet."},
                        "predicted_outcome": {"type": "string",
                                              "description": "What you predict happens and why, in words, including "
                                                             "whether you expect to get back."},
                    },
                    "required": ["linked_hypothesis", "oracle_claim_id", "state_id", "control_key",
                                 "predicted_screen", "predicted_outcome"],
                },
            },
        },
        "required": ["give_up", "reasoning", "candidate_tests"],
    },
}


def casting_system_prompt(test_budget: int, is_first_round: bool) -> str:
    if is_first_round:
        context = """You have not acted on this app yet. You have been given a carried map of its
states and the controls on each (carried_map), from an earlier read-only recon pass, plus one
real action already executed. Before proposing anything, think about what a web app of this shape
normally does and what goes wrong in that category (a control that silently does nothing, a view
you cannot get back from, two controls to one place, a tab whose content depends on state you have
not set). Use the map to decide what is worth checking first. State this reasoning explicitly."""
    else:
        context = f"""You now have real transitions. {PRIOR_FEEDBACK_GUIDE}
Remember that repeating an action is a real experiment: the same control landing somewhere different on a second visit, or a state
registered as new twice, are both findings. Briefly state what this app has shown you so far."""

    return f"""You are exploring a live web application to build a falsifiable model of its
navigation and to notice anything that does not behave the way its interface implies. You have
been shown what can be observed, the carried map of states and the controls you may act on, and
one real action already executed against the live app.

{context}

In one round, propose a BATCH of actions - up to {test_budget} total:
1. Candidate hypotheses: specific, falsifiable theories about what a control does or fails to do.
   For each, propose 1-2 actions that would check it, with a predicted_screen and a
   predicted_outcome. Set linked_hypothesis to the full theory text.
2. Pure probes: actions not tied to any theory. Predict what you honestly think happens and set
   linked_hypothesis to an empty string.

Every action is executed before you see any result, and after any action that reaches a new state
the run reboots to the start - so make each an independent check, not a step in a sequence. To
reach somewhere two navigations deep, that is the recon's job, not yours: you may only name a
(state, control) pair from the carried map. Propose fewer, sharper actions rather than filling the
budget, and set give_up to true if you have no good ideas left.

{SAFETY_NOTE}

Call submit_casting_round with your answer."""


def validate_casting_response(data) -> list[str]:
    errors, tests = casting_envelope_errors(data)
    if not isinstance(tests, list) or not tests:
        return errors
    else:
        pairs = live_session.valid_pairs()   # empty before the session is ready -> shape-only
        for i, test in enumerate(tests or []):
            if not isinstance(test, dict):
                errors.append(f"candidate_tests[{i}] must be an object")
                continue
            for key in ("linked_hypothesis", "oracle_claim_id", "state_id", "control_key",
                        "predicted_screen", "predicted_outcome"):
                if key not in test:
                    errors.append(f"candidate_tests[{i}] missing '{key}'")
                elif not isinstance(test[key], str):
                    errors.append(f"candidate_tests[{i}].{key} must be a string")
            if test.get("predicted_screen") not in PREDICTIONS:
                errors.append(f"candidate_tests[{i}].predicted_screen must be one of: {', '.join(PREDICTIONS)}")
            # The safety enforcement: a pair outside the carried map has no vetted path or
            # control, so it is rejected and resubmitted rather than actuated.
            if pairs and "state_id" in test and "control_key" in test:
                if (test["state_id"], test["control_key"]) not in pairs:
                    errors.append(
                        f"candidate_tests[{i}] names {test['state_id']} :: {test['control_key']}, "
                        f"which is not a (state, control) pair in the carried map. Pick one listed "
                        f"under a state in carried_map.")
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
        return "".join(f"<li><code>{esc(key)}</code>: {esc(', '.join(map(str, value)))}</li>"
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
    action_html = f'<span class="test-number">{esc(request.get("state"))} :: {esc(request.get("control"))}</span>'

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
      {render_json_block({"state": request.get("state"), "control": request.get("control")})}
      <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
        {_screen_badge(entry.get('predicted_screen'))}</div>
      <div class="test-outcome">
        reached {_screen_badge(entry.get('actual_screen'))}{drift_html}
        <span class="sep">&middot;</span> prediction {bool_badge(matched, 'matched', 'missed')}
        {recovered_html}
      </div>
      <div class="test-outcome prose-muted">click took <span class="num">{esc(result.get('click', '?'))}s</span>, settled in <span class="num">{esc(result.get('settle'))}s</span>{f", clicked through {esc(result['covered_by'])} on top of it" if result.get('covered_by') else ""}</div>
      {_signals_html(result)}
    </article>
    """


def render_onboarding_section(api_schema, onboarding_extra, happy_day_example) -> str:
    extra = onboarding_extra or {}
    happy_request = (happy_day_example or {}).get("request", {})
    happy_response = (happy_day_example or {}).get("response", {})
    map_html = ""
    if extra.get("carried_map"):
        map_html = f"""
    <div class="exhibit">
      <h3>Carried map (the action space)</h3>
      <pre class="schema-doc">{esc(extra['carried_map'])}</pre>
    </div>
    """
    baseline_html = ""
    if extra.get("baseline"):
        warned = str(extra["baseline"]).startswith("WARNING")
        baseline_html = f"""
    <div class="exhibit">
      <h3>Where the run started {badge('drifted', 'warn') if warned else badge('confirmed', 'good')}</h3>
      <pre class="schema-doc">{esc(extra['baseline'])}</pre>
    </div>
    """
    return f"""
    <div class="exhibit">
      <h3>What the Driver was told</h3>
      <pre class="schema-doc">{esc(api_schema)}</pre>
    </div>
    {map_html}
    {baseline_html}
    {render_oracle_ranked(extra.get('oracle_ranked'))}
    <div class="exhibit">
      <h3>Happy-day example</h3>
      <p class="eyebrow">Request</p>
      {render_json_block(happy_request)}
      <p class="eyebrow">Response</p>
      {render_json_block(happy_response)}
    </div>
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
    render_test_entry=render_test_entry,
    render_onboarding_section=render_onboarding_section,
    report_title="Web GUI - live browser exploration",
    # Modest budgets: every action is a real browser reach + actuate + reboot taking a
    # second or more, and the action space is only as large as the carried map.
    default_max_checkpoints=3,
    default_first_round_test_budget=6,
    default_test_budget=5,
)
