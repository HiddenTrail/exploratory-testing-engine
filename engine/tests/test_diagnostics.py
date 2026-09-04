"""engine/diagnostics.py: the detectors, and the replay that justifies them.

Three groups of tests, in ascending order of how much they prove.

1. Unit tests per detector, including the false-positive case each threshold was
   chosen to exclude. A detector that fires on a healthy run is worse than no
   detector, because its findings then carry no information but still qualify the
   report's conclusions.

2. THE REPLAY. `test_replay_*` runs the verbatim casting log of a real 3-checkpoint
   run against the live Clash Royale client through the detectors. The assertions
   name no screen, no tap, no coordinate and no game concept - only finding codes,
   severities and test numbers - so if they pass, the abstraction is carrying the
   signal rather than the domain. This is the test the design was promised on: the
   run in question spent two checkpoints and eight tests inside a modal dialog its
   own log had already described, and nothing generic could read that description.

3. The generalization check. The same detectors, over a `complex_sut` log built by
   driving the real rate-limited mock, must find something too - otherwise this is a
   game-client feature in a generic costume.
"""

import json
from pathlib import Path

import pytest

from engine import diagnostics, outcome

FIXTURE = Path(__file__).parent / "fixtures" / "clash_royale_run_2026_09_04.json"


def _entry(test_number, checkpoint=1, **envelope) -> dict:
    """One casting-log entry carrying nothing but its envelope.

    The detectors read only the envelope, so a fixture that also carried a request
    body and a response would be asserting over data no detector looks at.
    """
    return outcome.attach(
        {"test_number": test_number, "checkpoint": checkpoint},
        outcome.Outcome(**envelope),
    )


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def _by_code(findings, code) -> diagnostics.Finding:
    matching = [f for f in findings if f.code == code]
    assert matching, f"expected a {code!r} finding, got {_codes(findings)}"
    assert len(matching) == 1, f"expected one {code!r} finding, got {len(matching)}"
    return matching[0]


# --- degenerate_state -------------------------------------------------------

def test_degenerate_state_fires_when_most_actions_in_a_state_do_nothing():
    log = [
        _entry(1, effect=outcome.NONE, action_id="a", state_before="S"),
        _entry(2, effect=outcome.NONE, action_id="b", state_before="S"),
        _entry(3, effect=outcome.NONE, action_id="c", state_before="S"),
        _entry(4, effect=outcome.TRANSITION, action_id="d", state_before="S"),
    ]
    finding = _by_code(diagnostics.diagnose(log), "degenerate_state")
    assert finding.severity == "warn"
    assert finding.tests == (1, 2, 3)
    # The one action that worked is named, because "everything is dead" and "only
    # this one still works" call for different next tests.
    assert "d" in finding.detail


def test_degenerate_state_ignores_a_healthy_state_with_some_inert_controls():
    # Two of five actions doing nothing is what an ordinary state looks like - a way
    # out and a dismiss that are no-ops where nothing needs dismissing. 2/5 = 0.4,
    # under the 0.6 fraction, so this must stay silent.
    log = [
        _entry(1, effect=outcome.NONE, action_id="a", state_before="S"),
        _entry(2, effect=outcome.NONE, action_id="b", state_before="S"),
        _entry(3, effect=outcome.TRANSITION, action_id="c", state_before="S"),
        _entry(4, effect=outcome.TRANSITION, action_id="d", state_before="S"),
        _entry(5, effect=outcome.VARIANT, action_id="e", state_before="S"),
    ]
    assert "degenerate_state" not in _codes(diagnostics.diagnose(log))


def test_degenerate_state_needs_more_than_two_actions_probed():
    # Both actions tried did nothing - a 100% inert fraction - but two is not a
    # sample. A state visited twice with a dead control and a deliberate no-op would
    # otherwise be reported as a collapsed action space.
    log = [
        _entry(1, effect=outcome.NONE, action_id="a", state_before="S"),
        _entry(2, effect=outcome.NONE, action_id="b", state_before="S"),
    ]
    assert "degenerate_state" not in _codes(diagnostics.diagnose(log))


def test_degenerate_state_never_counts_an_unmeasurable_result_as_inert():
    # The rule engine/outcome.py exists to enforce: UNKNOWN is not NONE. An adapter
    # that cannot see whether anything changed must not be able to produce a finding
    # about the SUT's controls being dead.
    log = [
        _entry(n, effect=outcome.UNKNOWN, action_id=name, state_before="S")
        for n, name in enumerate("abcd", start=1)
    ]
    assert diagnostics.diagnose(log) == []


def test_degenerate_state_ignores_rows_with_no_observable_state():
    # An adapter that cannot observe state reports "" and gets no state-based
    # findings, rather than having all its tests pooled into one imaginary state.
    log = [
        _entry(n, effect=outcome.NONE, action_id=name, state_before="")
        for n, name in enumerate("abcd", start=1)
    ]
    assert "degenerate_state" not in _codes(diagnostics.diagnose(log))


def test_degenerate_state_is_per_state_not_per_action():
    # The same action inert in one state and working in another is not a broken
    # control, and the finding must be attributed to the state where it did nothing.
    log = [
        _entry(1, effect=outcome.NONE, action_id="a", state_before="DEAD"),
        _entry(2, effect=outcome.NONE, action_id="b", state_before="DEAD"),
        _entry(3, effect=outcome.NONE, action_id="c", state_before="DEAD"),
        _entry(4, effect=outcome.TRANSITION, action_id="a", state_before="LIVE"),
        _entry(5, effect=outcome.TRANSITION, action_id="b", state_before="LIVE"),
        _entry(6, effect=outcome.TRANSITION, action_id="c", state_before="LIVE"),
    ]
    finding = _by_code(diagnostics.diagnose(log), "degenerate_state")
    assert "DEAD" in finding.headline
    assert finding.tests == (1, 2, 3)


# --- batch_not_independent --------------------------------------------------

def test_batch_not_independent_fires_when_one_checkpoint_spans_two_states():
    log = [
        _entry(1, checkpoint=2, effect=outcome.TRANSITION, action_id="a", state_before="S"),
        _entry(2, checkpoint=2, effect=outcome.TRANSITION, action_id="b", state_before="T"),
    ]
    finding = _by_code(diagnostics.diagnose(log), "batch_not_independent")
    assert finding.severity == "warn"
    assert "checkpoint 2" in finding.headline
    assert finding.tests == (1, 2)


def test_batch_not_independent_is_silent_when_every_test_starts_in_one_place():
    log = [
        _entry(n, effect=outcome.TRANSITION, action_id=str(n), state_before="S")
        for n in range(1, 5)
    ]
    assert "batch_not_independent" not in _codes(diagnostics.diagnose(log))


def test_batch_not_independent_reports_per_checkpoint():
    # A run that drifted in checkpoint 1 and recovered by checkpoint 2 must not have
    # checkpoint 2's results qualified by checkpoint 1's problem.
    log = [
        _entry(1, checkpoint=1, effect=outcome.TRANSITION, action_id="a", state_before="S"),
        _entry(2, checkpoint=1, effect=outcome.TRANSITION, action_id="b", state_before="T"),
        _entry(3, checkpoint=2, effect=outcome.TRANSITION, action_id="a", state_before="S"),
        _entry(4, checkpoint=2, effect=outcome.TRANSITION, action_id="b", state_before="S"),
    ]
    findings = [f for f in diagnostics.diagnose(log) if f.code == "batch_not_independent"]
    assert len(findings) == 1
    assert findings[0].tests == (1, 2)


# --- reset_failing ----------------------------------------------------------

def test_reset_failing_stops_the_run_at_two_consecutive_failures():
    log = [
        _entry(1, reset_attempted=True, reset_ok=True, action_id="a", state_before="S"),
        _entry(2, reset_attempted=True, reset_ok=False, action_id="b", state_before="S"),
        _entry(3, reset_attempted=True, reset_ok=False, action_id="c", state_before="T"),
    ]
    findings = diagnostics.diagnose(log)
    finding = _by_code(findings, "reset_failing")
    assert finding.severity == "stop"
    assert finding.tests == (2, 3)
    # And the loop must be able to act on it without inspecting severities itself.
    assert diagnostics.should_stop(findings) is finding


def test_one_isolated_reset_failure_warns_but_does_not_stop():
    # A single failure can be a transition that had not finished. It still qualifies
    # the test that followed it, so it is reported - just not as a reason to stop.
    log = [
        _entry(1, reset_attempted=True, reset_ok=False, action_id="a", state_before="S"),
        _entry(2, reset_attempted=True, reset_ok=True, action_id="b", state_before="S"),
        _entry(3, reset_attempted=True, reset_ok=True, action_id="c", state_before="S"),
    ]
    findings = diagnostics.diagnose(log)
    assert _by_code(findings, "reset_failing").severity == "warn"
    assert diagnostics.should_stop(findings) is None


def test_reset_failing_counts_consecutive_attempts_not_consecutive_tests():
    # Tests 2 and 5 both failed to reset; tests 3 and 4 never tried. The failure
    # persisted through them, so the run is two-in-a-row and must stop - a broken
    # escape route must not be able to hide behind tests that did not need one.
    log = [
        _entry(1, reset_attempted=True, reset_ok=True, action_id="a", state_before="S"),
        _entry(2, reset_attempted=True, reset_ok=False, action_id="b", state_before="S"),
        _entry(3, action_id="c", state_before="T", effect=outcome.NONE),
        _entry(4, action_id="d", state_before="T", effect=outcome.NONE),
        _entry(5, reset_attempted=True, reset_ok=False, action_id="e", state_before="T"),
    ]
    assert _by_code(diagnostics.diagnose(log), "reset_failing").severity == "stop"


def test_a_run_that_never_needed_a_reset_reports_nothing_about_resets():
    log = [_entry(n, effect=outcome.TRANSITION, action_id=str(n), state_before="S")
           for n in range(1, 4)]
    assert "reset_failing" not in _codes(diagnostics.diagnose(log))


# --- prior_yield ------------------------------------------------------------

def test_prior_yield_warns_when_the_prior_matched_nothing_at_all():
    log = [_entry(n, matched_prior=False, action_id=str(n)) for n in range(1, 7)]
    finding = _by_code(diagnostics.diagnose(log), "prior_yield")
    assert finding.severity == "warn"
    assert "NONE" in finding.headline


def test_prior_yield_is_only_informational_when_the_prior_matched_sometimes():
    log = [_entry(n, matched_prior=(n % 2 == 0), action_id=str(n)) for n in range(1, 7)]
    finding = _by_code(diagnostics.diagnose(log), "prior_yield")
    assert finding.severity == "info"
    assert "3 of 6" in finding.headline


def test_prior_yield_says_nothing_from_a_small_sample():
    # "It never matched" over three observations is a statement about the sample.
    log = [_entry(n, matched_prior=False, action_id=str(n)) for n in range(1, 4)]
    assert "prior_yield" not in _codes(diagnostics.diagnose(log))


def test_prior_yield_is_silent_for_an_adapter_with_no_prior():
    log = [_entry(n, action_id=str(n)) for n in range(1, 9)]
    assert "prior_yield" not in _codes(diagnostics.diagnose(log))


# --- inputs_rejected --------------------------------------------------------

def test_inputs_rejected_warns_on_a_run_of_refusals():
    log = [
        _entry(1, accepted=True, action_id="a"),
        _entry(2, accepted=False, action_id="b"),
        _entry(3, accepted=False, action_id="c"),
        _entry(4, accepted=False, action_id="d"),
    ]
    finding = _by_code(diagnostics.diagnose(log), "inputs_rejected")
    assert finding.severity == "warn"
    assert finding.tests == (2, 3, 4)


def test_scattered_refusals_are_only_informational():
    # Individual refusals are usually the answer to the test that asked, not a SUT
    # that has stopped accepting input.
    log = [
        _entry(1, accepted=False, action_id="a"),
        _entry(2, accepted=True, action_id="b"),
        _entry(3, accepted=False, action_id="c"),
        _entry(4, accepted=True, action_id="d"),
    ]
    assert _by_code(diagnostics.diagnose(log), "inputs_rejected").severity == "info"


def test_inputs_rejected_is_silent_when_no_adapter_can_answer_the_question():
    # `accepted is None` is the honest answer for a SUT that cannot distinguish an
    # ignored input from an accepted one that did nothing. The detector must then
    # report nothing rather than guessing from `effect`.
    log = [_entry(n, effect=outcome.NONE, action_id=str(n)) for n in range(1, 7)]
    assert "inputs_rejected" not in _codes(diagnostics.diagnose(log))


# --- the envelope contract --------------------------------------------------

def test_an_adapter_with_no_envelopes_gets_told_the_checks_did_not_run():
    # The distinction the whole design turns on: "nothing was detected" and "nothing
    # could be detected" must not render identically.
    findings = diagnostics.diagnose([{"test_number": 1, "checkpoint": 1, "request": {}}])
    assert _codes(findings) == ["diagnostics_unavailable"]
    assert "not performed" in findings[0].detail


def test_an_empty_log_produces_no_findings_at_all():
    assert diagnostics.diagnose([]) == []


def test_rows_without_an_envelope_are_dropped_rather_than_defaulted():
    log = [
        {"test_number": 1, "checkpoint": 1},
        _entry(2, effect=outcome.NONE, action_id="a", state_before="S"),
    ]
    rows = outcome.rows(log)
    assert [r["test_number"] for r in rows] == [2]


def test_findings_are_ordered_most_serious_first():
    log = [
        _entry(1, matched_prior=True, action_id="a", state_before="S", effect=outcome.TRANSITION),
        _entry(2, matched_prior=True, action_id="b", state_before="S", effect=outcome.TRANSITION),
        _entry(3, matched_prior=True, action_id="c", state_before="S", effect=outcome.TRANSITION),
        _entry(4, matched_prior=True, action_id="d", state_before="S", effect=outcome.TRANSITION),
        _entry(5, matched_prior=True, action_id="e", state_before="S", reset_attempted=True, reset_ok=False),
        _entry(6, matched_prior=True, action_id="f", state_before="S", reset_attempted=True, reset_ok=False),
    ]
    severities = [f.severity for f in diagnostics.diagnose(log)]
    assert severities == sorted(severities, key={"stop": 0, "warn": 1, "info": 2}.get)
    assert severities[0] == "stop"


def test_the_model_payload_explains_itself_and_is_absent_when_there_is_nothing():
    assert diagnostics.for_model([]) is None
    payload = diagnostics.for_model(diagnostics.diagnose(
        [_entry(n, accepted=False, action_id=str(n)) for n in range(1, 5)]
    ))
    # Self-describing on purpose: three adapters and a bootstrap template each write
    # their own casting prompt, so an explanation that lives in a prompt is one the
    # next adapter will not have.
    assert diagnostics.PREAMBLE in payload["what_this_is"]
    assert payload["findings"][0]["code"] == "inputs_rejected"


# --- THE REPLAY: a real run, with no domain knowledge in the assertions ------

@pytest.fixture(scope="module")
def real_run_log():
    """The verbatim casting log of a real run, with envelopes derived at load time.

    The envelopes are NOT stored in the fixture. They are computed here by the
    adapter's own `outcome_for` against the recorded results, which makes this a test
    of the real mapping against real data rather than a test of a hand-written
    expectation - and keeps the fixture an untouched record.
    """
    from engine.adapters.clash_royale import adapter as clash_royale

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    log = []
    for entry in data["casting_log"]:
        result = entry.get("result")
        log.append(entry if result is None
                   else outcome.attach(dict(entry), clash_royale.outcome_for(result)))
    assert len(log) == 12, "the fixture is the 12-test run this was designed against"
    return log


def test_replay_finds_the_dead_action_space_the_original_run_missed(real_run_log):
    # The promise this whole abstraction was built on. Tests 6-9 of that run were
    # inputs sent into a state that was accepting none of them, and its own log said
    # so in fields no generic code could read. Nothing below names a screen, a tap or
    # anything else about the system under test.
    finding = _by_code(diagnostics.diagnose(real_run_log), "degenerate_state")
    assert finding.severity == "warn"
    assert {6, 7, 8, 9} <= set(finding.tests)
    # And it points at the single-cause explanation rather than at N broken controls.
    assert "not have been accepting input" in finding.detail


def test_replay_would_have_stopped_the_run_two_checkpoints_early(real_run_log):
    findings = diagnostics.diagnose(real_run_log)
    blocker = diagnostics.should_stop(findings)
    assert blocker is not None and blocker.code == "reset_failing"

    # And it was already a stop by the end of the FIRST checkpoint, which is what
    # makes it worth having: the loop would have ended there instead of spending two
    # more checkpoints and eight more tests from a starting point nobody chose.
    first_checkpoint = [e for e in real_run_log if e["checkpoint"] == 1]
    assert diagnostics.should_stop(diagnostics.diagnose(first_checkpoint)) is not None


def test_replay_reports_that_the_supplied_prior_never_matched(real_run_log):
    finding = _by_code(diagnostics.diagnose(real_run_log), "prior_yield")
    assert finding.severity == "warn"
    assert "NONE of 12" in finding.headline


def test_replay_flags_the_checkpoints_whose_tests_did_not_share_a_starting_point(real_run_log):
    findings = [f for f in diagnostics.diagnose(real_run_log) if f.code == "batch_not_independent"]
    assert findings, "two of the three checkpoints spanned more than one state"
    flagged = {t for f in findings for t in f.tests}
    assert flagged & {1, 2, 3, 4}


def test_replay_says_nothing_about_refusals_because_that_run_could_not_tell(real_run_log):
    # Every tap in that run was sent and none was refused by the guard, and this SUT
    # cannot distinguish an ignored input from an accepted one - so the detector that
    # needs `accepted` must stay quiet instead of inferring it from `effect`.
    assert "inputs_rejected" not in _codes(diagnostics.diagnose(real_run_log))


def test_replay_assertions_contain_no_domain_vocabulary():
    """Guards the point of the exercise, by reading this file back.

    If a later edit makes the replay tests pass by asserting on a screen id or an
    action name, the abstraction has stopped carrying the signal and the tests have
    started smuggling it. This is the cheapest available check that the replay stays
    honest, and it is deliberately about the ASSERTIONS, not the fixture loading -
    that part is allowed to know which adapter it is exercising.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    replay = source.split("# --- THE REPLAY", 1)[1]
    body = "\n".join(line for line in replay.splitlines()
                     if line.strip().startswith("assert") or " = diagnostics" in line)
    # Without this the check passes by finding nothing to check, which is the one way
    # a guard like this fails silently.
    assert body.count("assert") >= 10, "the replay assertions were not located"
    for domain_word in ("unknown-", "sc01", "open_cards", "open_profile", "open_events",
                        "return_to_main", "dismiss", "screen", "tap", "elixir", "arena"):
        assert domain_word not in body, f"{domain_word!r} leaked into a replay assertion"


# --- generalization: the same detectors over a different SUT -----------------

HTTP_FIXTURE = Path(__file__).parent / "fixtures" / "complex_sut_quota_run.json"


def test_the_detectors_find_the_same_shape_on_a_rate_limited_http_sut():
    """A spent quota is the HTTP-shaped form of the same defect.

    Also a real recorded run, not hand-made envelopes: `complex_sut`'s
    `execute_test` was driven directly against the running mock with hand-written
    bursts, so every response came off the wire. The envelopes ARE stored this time,
    because they were produced by the adapter at execution time - which is the thing
    being replayed.

    Six bursts against one client. The first three are inside its window; the last
    three are not, and the SUT refuses every request in them. That is a completely
    different mechanism from a game client behind a modal dialog, and it produces the
    same two findings - which is the claim the abstraction has to earn.
    """
    data = json.loads(HTTP_FIXTURE.read_text(encoding="utf-8"))
    log = data["casting_log"]
    findings = diagnostics.diagnose(log)

    # The collapsed action space: three differently-shaped inputs, none of which did
    # anything, from one state. Same code and severity the game client produced.
    degenerate = _by_code(findings, "degenerate_state")
    assert degenerate.severity == "warn"
    assert degenerate.tests == (4, 5, 6)

    # And the refusal run, which the other SUT could not report at all because it
    # cannot tell an ignored input from an accepted one.
    rejected = _by_code(findings, "inputs_rejected")
    assert rejected.severity == "warn"
    assert rejected.tests == (4, 5, 6)


def test_the_http_replay_uses_envelopes_the_adapter_itself_wrote():
    """Guards the fixture against being quietly hand-edited into agreement.

    Re-derives each envelope from the recorded request and responses using the
    adapter's own mapping and requires it to match what was stored at execution time.
    If someone adjusts the fixture to make the test above pass, this fails.
    """
    from engine.adapters.complex_sut import adapter as complex_sut

    data = json.loads(HTTP_FIXTURE.read_text(encoding="utf-8"))
    for entry in data["casting_log"]:
        rederived = complex_sut._outcome_for(
            entry["request"], entry["responses"], entry["accepted_count"]
        )
        assert outcome.read(entry) == rederived.as_dict(), entry["test_number"]


def test_a_healthy_http_run_produces_no_warnings():
    """The other half of earning its keep: silence on a run with nothing wrong.

    token_purchase's envelope is deliberately the emptiest of the three - it cannot
    observe the SUT's state at all - so a clean run of it must produce no findings
    beyond the informational, and in particular must not have its unobservable state
    read as a single enormous one.
    """
    from engine.adapters.token_purchase import adapter as token_purchase

    log = []
    for n, status in enumerate(["approved", "declined", "approved", "declined",
                                "approved", "declined"], start=1):
        response = {"status": 200, "body": {"status": status}}
        log.append(outcome.attach(
            {"test_number": n, "checkpoint": 1},
            token_purchase._outcome_for(response, status),
        ))
    findings = diagnostics.diagnose(log)
    assert [f for f in findings if f.severity in ("warn", "stop")] == []


def test_a_run_of_server_errors_is_reported_as_a_refusal_not_as_a_finding_about_logic():
    from engine.adapters.token_purchase import adapter as token_purchase

    log = [outcome.attach(
        {"test_number": n, "checkpoint": 1},
        token_purchase._outcome_for({"status": 500, "body": {}}, None),
    ) for n in range(1, 5)]
    finding = _by_code(diagnostics.diagnose(log), "inputs_rejected")
    assert finding.severity == "warn"
    assert finding.tests == (1, 2, 3, 4)
