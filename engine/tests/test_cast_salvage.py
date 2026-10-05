"""A casting round that is mostly fine doesn't end the run (issue #288): the last attempt
keeps its usable tests, and a rejected pair names the controls the state really has.
Stubbed client, no model calls."""

import pytest

from engine.adapters.web_gui import adapter as adp
from engine.adapters.web_gui import session as live_session
from engine.client import call_tool_with_retry
from engine.run_summary import summarize
from engine.tools import salvage_casting
from engine.tests.test_client_retry import _FakeClient, _FakeMessage, _FakeToolUse

PAIRS = {("st01", "button:A"), ("st01", "button:B"), ("st02", "button:C")}


def _test(state_id="st01", control_key="button:A"):
    return {"linked_hypothesis": "", "oracle_claim_id": "", "state_id": state_id, "control_key": control_key,
            "predicted_screen": "known_screen", "predicted_outcome": "goes to page 2"}


def _round(*tests):
    return {"give_up": False, "reasoning": "r", "candidate_tests": list(tests)}


@pytest.fixture
def live_map(monkeypatch):
    monkeypatch.setattr(live_session, "valid_pairs", lambda: PAIRS)


def test_a_rejected_pair_lists_the_controls_its_state_really_has(live_map):
    [error] = adp.validate_casting_response(_round(_test(control_key="button:button to deposit")))
    assert "The controls of st01 are exactly: button:A, button:B." in error
    [error] = adp.validate_casting_response(_round(_test(state_id="st99")))
    assert "names state st99, which is not in the carried map" in error


def test_the_salvage_keeps_the_usable_tests_when_at_least_half_are(live_map):
    salvage = salvage_casting(adp.validate_casting_response)
    kept = salvage(_round(_test(), _test(control_key="button:B"), _test(control_key="textbox:")))
    assert [t["control_key"] for t in kept["candidate_tests"]] == ["button:A", "button:B"]
    assert kept["dropped_tests"][0]["test"]["control_key"] == "textbox:"
    assert "not a (state, control) pair" in kept["dropped_tests"][0]["errors"][0]
    # Half is enough; less than half means the round is badly wrong, so it still fails.
    assert salvage(_round(_test(), _test(control_key="textbox:"))) is not None
    assert salvage(_round(_test(), _test(control_key="x:1"), _test(control_key="x:2"))) is None
    # A fault in the round itself fails every test alone, so nothing is kept.
    assert salvage({**_round(_test(), _test(control_key="x:1")), "reasoning": 7}) is None


def test_only_the_last_attempt_is_salvaged(live_map):
    bad_round = _round(_test(), _test(control_key="button:B"), _test(control_key="textbox:"))
    client = _FakeClient([_FakeMessage([_FakeToolUse(f"id{n}", bad_round)]) for n in (1, 2, 3)])
    result = call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="submit_casting_round", user_message="u",
        validate_fn=adp.validate_casting_response, max_tokens=10, max_attempts=3,
        salvage_fn=salvage_casting(adp.validate_casting_response))
    assert client.messages.call_count == 3
    assert len(result["candidate_tests"]) == 2 and len(result["dropped_tests"]) == 1


def test_a_salvage_that_returns_a_broken_answer_is_not_used():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"bad": True})])])
    with pytest.raises(RuntimeError, match="Gave up after 1 attempts"):
        call_tool_with_retry(
            client, model="m", system="s", tools=[], tool_name="t", user_message="u",
            validate_fn=lambda data: [] if data.get("ok") else ["missing 'ok'"], max_tokens=10, max_attempts=1,
            salvage_fn=lambda answer: {"still": "bad"})


def test_the_summary_counts_dropped_tests():
    output = {"usage_summary": {"submit_casting_round": {"calls": 3}},
              "checkpoints": [{"dropped_tests": [{"test": {}, "errors": ["e"]}]}, {"dropped_tests": []}]}
    assert "1 cast test(s) dropped as unusable" in summarize(output, log_text="")


def test_the_report_shows_dropped_tests():
    from engine.report import _render_checkpoint
    html = _render_checkpoint(1, {"dropped_tests": [{"test": {"state_id": "st01", "control_key": "textbox:"},
                                                     "errors": ["not in the map"]}]} | _EMPTY_CHECKPOINT,
                              {}, lambda e: "")
    assert "Tests this checkpoint (0, 1 dropped)" in html
    assert "st01 :: textbox:: not in the map" in html


_EMPTY_CHECKPOINT = {
    "hypothesis": {"observations": [], "behaviors": [], "untested": [], "prior_gaps": [], "summary": "s"},
    "skeptic_review": {"observation_checks": [], "gaps": [], "coverage": {"untouched": [], "material": False, "note": ""},
                       "prior_gaps_check": [], "verdict": "weak", "verdict_reason": "r"},
}
