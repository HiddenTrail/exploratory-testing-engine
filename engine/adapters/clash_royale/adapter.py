"""SUTAdapter for Clash Royale: a live mobile game as a system under test.

The third adapter, and the first whose SUT is not a web service. token_purchase
and complex_sut both speak HTTP to a mock running on localhost; this one speaks
taps to a real client, signed into a real account, on the machine the run is
happening on. That difference is the point - the engine has been *described* as
SUT-agnostic since the interface was extracted, and until something without a URL
existed, that was a claim rather than a result.

What the Driver is actually testing
-----------------------------------
Not "does this game work". The falsifiable thing about an interface nobody has
mapped is its *navigation graph*: which controls lead where, which lead nowhere,
which lead somewhere you cannot get back from. So a test is one named tap plus a
prediction about where it lands, expressed structurally - see PREDICTIONS - and an
anomaly is a control that does not do what a person reading the interface would
expect it to do.

That is a narrower question than the other two adapters ask, and the narrowing is
imposed by the SUT rather than chosen: without an oracle, a response body or a
schema, the only claims available are about state changes that a frame comparison
can confirm or refute.

Why the prediction is structural and not a screen name
------------------------------------------------------
Screens are identified by comparison, not declared (see session.py). The Driver is
never shown which fingerprint is about to match, so on the tap that first opens the
card collection it has no name to predict; requiring one would make every first
visit an automatic miss and every prediction after it a memory test.
`same_screen` / `known_screen` / `new_screen` is the strongest claim that is
actually checkable on the first visit, and it is a real claim: predicting that a
navigation tab opens something new, and finding the screen unchanged, is exactly
the anomaly this is looking for.

Note what the carried reference does to `known_screen`. Eleven screens of this
client were measured by an earlier recon pass, so a screen can be *known* on its
first sighting this run - which makes `known_screen` a claim about the game's
navigation rather than a claim about the run's own memory, and makes `new_screen`
the much stronger statement that a tap reached somewhere nobody has mapped.

Safety
------
Everything structural is in actions.py and session.py, and the short version is:
the Driver picks a name from an enum, there is no numeric field anywhere in this
schema, the coordinate guard is proven awake before the first tap, a board on
screen aborts the run outright, and a guard refusal comes back as a result the
Driver reads rather than an exception that kills the run.
"""

from engine import outcome
from engine.adapter import SUTAdapter
from engine.adapters.clash_royale import reference
from engine.adapters.clash_royale import session as live_session
from engine.adapters.clash_royale.actions import (
    BY_NAME,
    CASTING_ACTIONS,
    CATALOGUE,
    RECOVERY,
)
from engine.report import badge, bool_badge, esc, inline_markdown, render_json_block

# The three things the Driver may predict about where a tap lands. Kept here
# rather than in actions.py because this is a fact about the casting contract,
# not about the client - session.py produces the same three strings as `screen_was`
# and this is the enum that constrains what may be predicted against them.
PREDICTIONS = ("same_screen", "known_screen", "new_screen")

# The action used for the live happy-day example. `return_to_main` on purpose: it
# is the recovery action, so if it does something surprising the run should find
# that out in onboarding rather than later, when it is being relied on to get out
# of somewhere - and on the main screen its correct behaviour is to change nothing,
# which makes it the cheapest honest live call available.
HAPPY_DAY_ACTION = RECOVERY


def _catalogue_doc() -> str:
    lines = []
    for action in CATALOGUE:
        lines.append(f"  {action.name}\n    {action.what}\n    reversible: {action.reversible}")
    return "\n".join(lines)


API_SCHEMA_DOC = f"""Clash Royale, a live mobile game client, driven by taps and observed
by comparing frames. There is no API, no response body and no log: everything below is
what a screenshot can be made to say.

THE ACTION SPACE. You may ask for exactly one of these named taps per test. You cannot
supply a coordinate - the coordinates are fixed, measured by hand, and reviewed by the
operator before any run. There is no way to express a tap at a place not on this list,
and that is deliberate: this is a real account, and an unvetted coordinate on a game
interface can reach a purchase or an irreversible action.

{_catalogue_doc()}

WHAT YOU GET BACK, per test:
  screen_before: which screen was up before the tap.
  screen_after: which screen was up afterwards.
  screen_was: one of "same_screen" (nothing changed), "known_screen" (a screen already
    recognised - either visited earlier this run, or one of the previously measured
    screens listed further down), or "new_screen" (somewhere neither applies to).
  screen_after_label: the same screen with whatever an earlier pass called it, where
    it recognised one. Read this, not screen_after, when you want to know what a place
    IS; screen_after is the bare token predictions are checked against.
  was_measured_before: true if this screen came from the earlier pass's map rather than
    from this run's own discoveries.
  first_sight_this_run: true the first time this run reaches that screen.
  agreement: 0..1, how much of the screen's stable area matched the fingerprint it was
    identified as. At or above {live_session.SAME_SCREEN} it is that screen; below, it is treated as a
    different one. A match that only just clears the cut is worth noticing.
  settle: seconds the window took to stop changing after the tap. Roughly 0.25s means
    nothing visibly happened; longer means a transition or an animation ran.
  verdict: "sent" normally, or "refused" if the coordinate guard blocked the tap.
  recovered_to: where the run ended up after returning to the main screen, when a test
    landed somewhere new. If it says NOT the main screen, the way back failed - which is
    a finding in its own right and means the next test did not start where it thought.

HOW SCREENS ARE NAMED. A screen is identified by comparing a downscaled frame against
stored fingerprints, never by reading what is on it. Some of those fingerprints were
measured against this same client by an earlier exploratory pass and carry that pass's
names - "sc01", "sc07" and so on, listed below. Anything matching none of them becomes
"unknown-1", "unknown-2" in the order found, and that name means only what it says: not
one of the previously measured screens. You are not told in advance which fingerprint a
tap is about to match, which is why your prediction is structural rather than a name.

{reference.driver_briefing()}

WHAT IS OFF LIMITS, and why some taps come back refused. A coordinate denylist is
enforced below this interface, covering the shop, the clan tab, the battle button, the
gem and gold counters, and the promotional banner. None of the actions above is inside
it, so a refusal means a control has moved to where something forbidden now sits - which
is itself worth reporting as an anomaly. This run touches the meta-game only, and it
stops itself outright on two things: a battle board being on screen, and any of the
screens marked ABORTS above. Either means a tap reached somewhere five vetted taps
should not be able to reach, so no further input is sent and the run ends there.

WHAT COUNTS AS AN ANOMALY HERE. Not "the game has a bug in it" - you cannot see enough to
claim that. Claim things about the navigation this can actually check: a control that does
nothing, a control that leads somewhere the way back does not work from, two controls that
land on the same screen, a screen whose identity is unstable across visits (the same place
being registered as new twice), or a settle time that contradicts what visibly changed.

The previously measured screens give you one more kind of checkable claim, and it cuts both
ways. A tap that lands on "unknown-N" reached somewhere that pass never did, which is worth
saying. A screen that matches at barely above the cut, or a screen the earlier pass reached
that this run cannot reach at all, is evidence that the client has changed since it was
measured - a real finding, but one about the map rather than about the game, and worth
labelling as such so it is not mistaken for a navigation defect."""


SAFETY_NOTE = """This SUT is a live client signed into a real account, on the operator's own
machine, watched by the operator while it runs. There is no reset and no rollback: an
action that spends a resource has spent it. So the scope is navigation of the meta-game -
looking at screens and coming back - and nothing in the action space acquires, spends,
sends or agrees to anything. If a screen appears that asks you to accept or confirm
something, the correct action is to leave it, and this interface's way of leaving is
`dismiss` or `return_to_main`. Never treat an unexpected dialog as a thing to explore."""


# The agreement at or above which a frame is byte-identical to a stored appearance
# of the same screen, which is this SUT's only evidence that an input changed
# NOTHING rather than something small.
#
# It is 0.999 for an arithmetic reason, not a chosen tolerance. `agreement` is a
# fraction over compared cells and there are at most 576 of them, so a single
# differing cell scores 575/576 = 0.998 - and fewer compared cells only push it
# lower. Nothing between 0.999 and 1.000 is reachable, so this is exactly "zero
# cells differ" with a guard against float rounding, and it cannot be loosened by
# accident into a real tolerance.
#
# What it is measured against matters, and is weaker than it looks for one case.
# `session.observe` scores the frame against the stored fingerprint of the screen
# it matched, not against this test's own before-frame. For a screen this run
# registered itself the two are the same frame, so 1.000 means pixel-identical to
# when it was first seen. For a screen carried from an earlier session it is a
# fingerprint from a different day, which will essentially never score 1.000 - so
# those come back VARIANT ("still here, something moved") rather than NONE. That
# asymmetry errs the safe way: it can miss a dead control, never invent one.
IDENTICAL_AGREEMENT = 0.999


def outcome_for(result: dict) -> outcome.Outcome:
    """One `session.act` result as the engine's typed outcome envelope.

    Pure, so the mapping can be tested against recorded results with no client
    attached - which is the point of it being here rather than inline in
    `execute_test`.

    Three decisions worth arguing with:

    `accepted` is None for every tap that was actually sent. This client offers no
    way to distinguish "the tap was swallowed by a modal" from "the tap hit a dead
    area of a live screen" - both produce an unchanged frame - and answering False
    would hand `engine/diagnostics.py` a fact nobody measured. A guard refusal is
    the one honest False: the input demonstrably never reached the SUT.

    A refusal's effect is UNKNOWN, not NONE, even though the click provably did
    nothing. NONE means "the SUT was given this input and nothing happened", and
    the refused click never became an input. Marking it NONE would let a batch of
    denylisted taps read as a collapsed action space - a fabricated finding about
    the game, sourced entirely from this project's own safety layer.

    `matched_prior` is `was_measured_before`: whether the screen the tap landed on
    was one of the eleven an earlier recon pass fingerprinted. A run where that is
    never true has a carried reference contributing nothing, including the four
    abort screens the shop tripwire depends on recognising - which is worth a line
    in the report rather than silence.
    """
    verdict = result.get("verdict")
    screen_before = result.get("screen_before") or ""

    if verdict == "refused":
        return outcome.Outcome(
            action_id=result.get("action", ""),
            effect=outcome.UNKNOWN,
            accepted=False,
            state_before=screen_before,
            state_after=screen_before,
        )

    screen_was = result.get("screen_was")
    if screen_was == "same_screen":
        agreement = result.get("agreement")
        if agreement is None:
            effect = outcome.UNKNOWN
        elif agreement >= IDENTICAL_AGREEMENT:
            effect = outcome.NONE
        else:
            effect = outcome.VARIANT
    elif screen_was in ("known_screen", "new_screen"):
        effect = outcome.TRANSITION
    else:
        effect = outcome.UNKNOWN

    recovered_to = result.get("recovered_to")
    return outcome.Outcome(
        action_id=result.get("action", ""),
        effect=effect,
        accepted=None,
        state_before=screen_before,
        state_after=result.get("screen_after") or "",
        reset_attempted=recovered_to is not None,
        # `recover` returns the bare main-screen id on success and a sentence
        # explaining itself otherwise, so this is an equality check rather than any
        # parsing of prose - see session.recover.
        reset_ok=None if recovered_to is None else recovered_to == reference.MAIN_SCREEN,
        latency=result.get("settle"),
        matched_prior=result.get("was_measured_before"),
    )


def execute_test(test: dict, test_number: int) -> dict:
    """Send one named tap at the live client and report the whole transition.

    Recovery is part of executing the test, not a separate step: a test that lands
    somewhere new leaves the client somewhere the *next* test did not expect, so
    every batch would otherwise depend on the order it happened to run in. Coming
    back to the main screen after each discovery is what makes the tests in a batch
    independent, which is what the casting prompt promises the Driver they are.
    """
    action_name = test["action"]
    predicted = test["predicted_screen"]

    if action_name not in BY_NAME:
        # Unreachable through the schema's enum, and kept anyway: this is the one
        # place where an action name that nothing can execute would otherwise
        # become a KeyError mid-run, and a refused test the Driver can read is
        # strictly better than a crashed run.
        return outcome.attach({
            "test_number": test_number,
            "request": {"action": action_name},
            "predicted_outcome": test["predicted_outcome"],
            "predicted_screen": predicted,
            "skipped": True,
            "skip_reason": (
                f"{action_name!r} is not in the action catalogue, so there is no vetted "
                f"coordinate for it. Choose from: {', '.join(CASTING_ACTIONS)}."
            ),
            "prediction_matched": False,
        }, outcome.Outcome(
            # Nothing was sent and nothing was observed, so every state field stays
            # empty and the effect stays UNKNOWN. `accepted=False` is the accurate
            # generic statement: the input never reached the SUT.
            action_id=action_name, effect=outcome.UNKNOWN, accepted=False,
        ))

    session = live_session.live()
    result = session.act(action_name)

    if result["screen_was"] == "new_screen":
        result["recovered_to"] = session.recover()

    return outcome.attach({
        "test_number": test_number,
        "request": {"action": action_name, "at": result["at"], "what": result["what"]},
        "predicted_outcome": test["predicted_outcome"],
        "predicted_screen": predicted,
        "result": result,
        "actual_screen": result["screen_was"],
        "prediction_matched": result["screen_was"] == predicted,
    }, outcome_for(result))


def fetch_happy_day_example(adapter: SUTAdapter) -> dict:
    """One real tap at the live client, so onboarding starts from a fact.

    The alternative - writing the example down in this file - would put a claim
    about the client in front of the Driver that nothing checks, and this client
    changes: it has resized itself between sessions and interrupted itself with a
    content update. A live example also means the first thing the run proves is
    that a tap gets through at all.
    """
    session = live_session.live()
    return {
        "request": {"action": HAPPY_DAY_ACTION, "what": BY_NAME[HAPPY_DAY_ACTION].what},
        "response": session.act(HAPPY_DAY_ACTION),
    }


def describe_test_for_log(test: dict) -> str:
    return f"{test['action']} -> predicting {test['predicted_screen']}"


def describe_result_for_log(result: dict) -> str:
    if result.get("skipped"):
        return f"SKIPPED - {result['skip_reason']}"
    detail = result["result"]
    if detail["verdict"] == "refused":
        return f"REFUSED by the guard - {detail['why']}"
    line = (f"{detail['screen_before']} -> {detail.get('screen_after_label') or detail['screen_after']} "
            f"({detail['screen_was']}, agrees {detail.get('agreement')}, settled {detail['settle']}s)")
    if detail.get("first_sight_this_run") and detail.get("was_measured_before"):
        # Called out because it is the console's only sign that the carried map is
        # being reached at all: a run whose log never says this has matched none of
        # the eleven measured screens, and that is worth seeing while it happens
        # rather than working out afterwards from which names are absent.
        line += " [first sight this run of a previously measured screen]"
    if "recovered_to" in detail:
        line += f", recovered to {detail['recovered_to']}"
    return line


CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": "Propose a batch of taps against the live Clash Royale client.",
    "input_schema": {
        "type": "object",
        "properties": {
            "give_up": {
                "type": "boolean",
                "description": "Set true only if you have no more good ideas worth proposing this round.",
            },
            "reasoning": {
                "type": "string",
                "description": "Your reasoning for this round's batch, per the system prompt's instructions.",
            },
            "candidate_tests": {
                "type": "array",
                "description": (
                    "See the system prompt for how many tests to propose this round. Each is EITHER "
                    "tied to a specific candidate hypothesis (set linked_hypothesis to that theory, "
                    "stated in full) OR a pure probe not tied to any theory (set linked_hypothesis to "
                    "an empty string). Mix both kinds in the same list."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "linked_hypothesis": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": list(CASTING_ACTIONS),
                            "description": (
                                "Which named tap to send. This is the ONLY way to specify an input: "
                                "there is no coordinate field, because this is a live client on a real "
                                "account and only hand-vetted points may be touched."
                            ),
                        },
                        "predicted_screen": {
                            "type": "string",
                            "enum": list(PREDICTIONS),
                            "description": (
                                "Where you predict this tap lands. 'same_screen' - nothing changes. "
                                "'known_screen' - it goes to a screen this session has already seen, "
                                "which for a navigation tab means it has been opened before. "
                                "'new_screen' - somewhere not seen yet this session. Note that the "
                                "SECOND time you open the same tab, the honest prediction is "
                                "'known_screen', not 'new_screen'; predicting 'new_screen' twice for "
                                "one control is a prediction that the game shows you something "
                                "different each time, which is a real claim you may well want to make "
                                "about a tab that carries rotating content."
                            ),
                        },
                        "predicted_outcome": {
                            "type": "string",
                            "description": (
                                "What you predict happens and why, in words - including what you "
                                "expect to be able to do from there and whether you expect to get "
                                "back. This is where the substance of the prediction goes; "
                                "predicted_screen is only the part that can be checked mechanically."
                            ),
                        },
                    },
                    "required": ["linked_hypothesis", "action", "predicted_screen", "predicted_outcome"],
                },
            },
        },
        "required": ["give_up", "reasoning", "candidate_tests"],
    },
}


def casting_system_prompt(test_budget: int, is_first_round: bool) -> str:
    if is_first_round:
        context_instruction = """You have not touched this client yet. Before proposing anything, think
about context: what does a free-to-play mobile game's main screen normally do, and what goes wrong in
that category of interface (a tab that silently does nothing until some unlock, a panel with no way
out except a button that is off-screen, a control whose meaning changes with an event, two controls
that lead to the same place, a transition slow enough that a second tap lands somewhere unintended)?
Use that to decide what to look at first. State this reasoning explicitly."""
    else:
        context_instruction = """You now have real transitions, and prior_checkpoint_feedback holds the
previous checkpoint's hypothesis plus Skeptic's cold critique of it. If that hypothesis claimed an
anomaly Skeptic found weak, prioritise taps that could confirm OR refute that SPECIFIC claim - and
remember that repeating a tap is a real experiment here, because the same control landing somewhere
different on the second visit, or the same screen being registered as new twice, are both findings.
Briefly state what THIS client has actually shown you so far and how it changes your approach."""

    return f"""You are exploring a live Clash Royale client to build a falsifiable model of its
navigation, and to notice anything that does not behave the way its interface implies. You
have been shown what can be observed, the complete list of taps you may ask for, and one
real tap already executed against the live client.

{context_instruction}

In one round, propose a BATCH of taps - up to {test_budget} total:
1. Candidate hypotheses: specific, falsifiable theories about what a control does or fails
   to do. For each, propose 1-2 taps that would check it, with a predicted_screen and a
   predicted_outcome saying what you expect and why. Set linked_hypothesis to the full
   theory text.
2. Pure probes: taps not tied to any theory, just to see where they go. For these predict
   whatever you honestly think happens and set linked_hypothesis to an empty string.

Every tap in the batch is executed before you see any result, so make each one an
independent check rather than a step in a sequence. You cannot chain taps within a round:
after any tap that lands somewhere new, the run returns to the main screen before the next
test, precisely so that the order within a batch does not change the outcome. If you want
to reach somewhere two taps deep, that takes two rounds - propose the first tap now and use
what it shows you next round.

The action space is small and fixed, so most of what there is to learn is in REPEATING
taps under different conditions and in the numbers that come back - settle time and
agreement - not in finding new controls. A control you have already used is still worth
another test if you have a specific reason to expect a different result this time. It is
not worth another test just to fill the budget: propose fewer taps rather than arbitrary
ones, and set give_up to true if you genuinely have no good ideas left.

{SAFETY_NOTE}

Call submit_casting_round with your answer."""


def validate_casting_response(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]

    for key in ("give_up", "reasoning", "candidate_tests"):
        if key not in data:
            errors.append(f"missing required field '{key}'")

    if not isinstance(data.get("give_up"), bool):
        errors.append("'give_up' must be a boolean")

    tests = data.get("candidate_tests")
    if not isinstance(tests, list):
        errors.append("'candidate_tests' must be a list")
    elif not data.get("give_up") and not tests:
        errors.append("'candidate_tests' must be non-empty unless give_up is true")
    else:
        for i, test in enumerate(tests or []):
            if not isinstance(test, dict):
                errors.append(f"candidate_tests[{i}] must be an object")
                continue
            for key in ("linked_hypothesis", "action", "predicted_screen", "predicted_outcome"):
                if key not in test:
                    errors.append(f"candidate_tests[{i}] missing '{key}'")
                elif not isinstance(test[key], str):
                    errors.append(f"candidate_tests[{i}].{key} must be a string")
            # Checked here as well as in the tool schema, because the schema is a
            # request and this is the enforcement. A name outside the catalogue has
            # no vetted coordinate behind it, which is the whole safety argument -
            # so it is rejected and resubmitted rather than sent.
            if "action" in test and test["action"] not in CASTING_ACTIONS:
                errors.append(
                    f"candidate_tests[{i}].action must be one of: {', '.join(CASTING_ACTIONS)} "
                    f"(got {test['action']!r})"
                )
            if "predicted_screen" in test and test["predicted_screen"] not in PREDICTIONS:
                errors.append(
                    f"candidate_tests[{i}].predicted_screen must be one of: {', '.join(PREDICTIONS)}"
                )

    return errors


def _screen_badge(screen_was) -> str:
    if screen_was == "new_screen":
        return badge("new screen", "warn")
    if screen_was == "known_screen":
        return badge("known screen", "good")
    return badge("no change", "neutral")


def render_test_entry(entry) -> str:
    if not entry:
        return ""
    request = entry.get("request", {})
    linked = entry.get("linked_hypothesis")
    linked_html = f"<strong>Hypothesis:</strong> {esc(linked)}" if linked else (
        '<span class="probe-label">Probe</span> (no linked hypothesis)'
    )
    test_number = entry.get("test_number")
    number_html = f'<span class="test-number">Test #{esc(test_number)}</span>' if test_number is not None else ""
    action_html = f'<span class="test-number">{esc(request.get("action"))}</span>'

    if entry.get("skipped"):
        return f"""
        <article class="test test-skipped">
          <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
          <div class="test-outcome">{badge('skipped', 'warn')} {inline_markdown(entry.get('skip_reason'))}</div>
        </article>
        """

    result = entry.get("result", {})
    matched = entry.get("prediction_matched")

    if result.get("verdict") == "refused":
        # A refusal is rendered as its own outcome rather than as a failure,
        # because the guard doing its job is not a defect in the SUT and reading
        # it as one in the report would be misleading.
        return f"""
        <article class="test">
          <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
          <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
            {_screen_badge(entry.get('predicted_screen'))}</div>
          <div class="test-outcome">{badge('refused by the coordinate guard', 'bad')}
            {esc(result.get('why'))}</div>
        </article>
        """

    recovered = result.get("recovered_to")
    recovered_html = (f'<span class="sep">&middot;</span> recovered to '
                      f'<span class="num">{esc(recovered)}</span>') if recovered else ""
    # The measured name where there is one, so the report reads as navigation rather
    # than as a list of ids. Falls back to the bare token rather than to nothing,
    # because an unknown screen is the case most worth being able to read.
    landed = result.get("screen_after_label") or result.get("screen_after")
    return f"""
    <article class="test">
      <div class="test-hypothesis">{number_html}{action_html}{linked_html}</div>
      {render_json_block({"action": request.get("action"), "at": request.get("at"),
                          "what": request.get("what")})}
      <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
        {_screen_badge(entry.get('predicted_screen'))}</div>
      <div class="test-outcome">
        <span class="num">{esc(result.get('screen_before'))}</span> &rarr;
        <span class="num">{esc(landed)}</span>
        {_screen_badge(entry.get('actual_screen'))}
        <span class="sep">&middot;</span> prediction {bool_badge(matched, 'matched', 'missed')}
        {recovered_html}
      </div>
      <div class="test-outcome prose-muted">agreement <span class="num">{esc(result.get('agreement'))}</span>
        <span class="sep">&middot;</span> settled in <span class="num">{esc(result.get('settle'))}s</span></div>
    </article>
    """


def render_onboarding_section(api_schema, onboarding_extra, happy_day_example) -> str:
    happy_request = (happy_day_example or {}).get("request", {})
    happy_response = (happy_day_example or {}).get("response", {})
    extra = onboarding_extra or {}
    preflight_html = ""
    if extra.get("preflight"):
        # The safety preflight is in the report, not only on the console, because
        # the operator's standing rule is that the denylist and what it blocks are
        # shown - and a run is reviewed from its report long after the console
        # scrollback is gone.
        preflight_html = f"""
    <div class="exhibit">
      <h3>Safety preflight</h3>
      <pre class="schema-doc">{esc(extra['preflight'])}</pre>
    </div>
    """
    baseline_html = ""
    if extra.get("baseline"):
        # Where the run started, and how confidently that was established. In the
        # report because it qualifies every reading in it: if the first frame matched
        # no measured screen, every same_screen/new_screen below is relative to
        # whatever the client happened to be showing, and somebody reading the
        # findings later needs that in front of them rather than in a lost scrollback.
        warned = extra["baseline"].startswith("WARNING")
        baseline_html = f"""
    <div class="exhibit">
      <h3>Where the run started {badge('unconfirmed', 'warn') if warned else badge('main screen', 'good')}</h3>
      <pre class="schema-doc">{esc(extra['baseline'])}</pre>
    </div>
    """
    return f"""
    <div class="exhibit">
      <h3>What the Driver was told</h3>
      <pre class="schema-doc">{esc(api_schema)}</pre>
    </div>
    {preflight_html}
    {baseline_html}
    <div class="exhibit">
      <h3>Happy-day example</h3>
      <p class="eyebrow">Request</p>
      {render_json_block(happy_request)}
      <p class="eyebrow">Response</p>
      {render_json_block(happy_response)}
    </div>
    """


ADAPTER = SUTAdapter(
    name="clash_royale",
    display_name="Clash Royale (live client)",
    api_schema_doc=API_SCHEMA_DOC,
    # Mutable on purpose and filled by check_ready, which is the only thing that
    # can produce it: the preflight report is a statement about the denylist as
    # actually loaded against the live window, so writing it down here would be a
    # copy of a check rather than the check.
    onboarding_extra={"safety_note": SAFETY_NOTE},
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
    report_title="Clash Royale - live client exploration",
    # Small budgets, unlike the HTTP adapters': every test here is a real tap on a
    # real account taking a second or more, the action space has five entries, and
    # a round that proposes twelve taps against five controls is padding. The
    # operator is watching this run, so its length is a courtesy as well.
    default_max_checkpoints=3,
    default_first_round_test_budget=5,
    default_test_budget=4,
)
