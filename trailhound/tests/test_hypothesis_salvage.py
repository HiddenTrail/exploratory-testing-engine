"""A hypothesis whose only fault at the last try is a behaviour citing a test with an
error loses that behaviour, not the run (issue #363). Stubbed client, no model calls."""

import pytest

from trailhound import ledger
from trailhound.client import call_tool_with_retry
from trailhound.report import _render_checkpoint
from trailhound.tests.test_cast_salvage import _EMPTY_CHECKPOINT
from trailhound.tests.test_client_retry import _FakeClient, _FakeMessage, _FakeToolUse
from trailhound.tests.test_hypothesis_schema import _hypothesis
from trailhound.tools import validate_hypothesis_response

LOGIN_401 = "console: Failed to load resource: the server responded with a status of 401 (Unauthorized)"
PROBLEMS = {13: [LOGIN_401], 14: [LOGIN_401]}


def _validate(data):
    # The error itself is answered (an observation cites test 1, which recorded nothing),
    # so the behaviour is the only fault.
    return validate_hypothesis_response(data, test_problems=PROBLEMS)


def _with_bad_behavior():
    return _hypothesis(behaviors=[{"claim": "Sequential requests stop at 5", "tests": [2, 3]},
                                  {"claim": "Login shows 'Invalid email or password'", "tests": [13]}],
                       dismissed_errors=[{"error": LOGIN_401, "reason": "a wrong password is refused"}])


def test_the_salvage_drops_only_the_behaviours_citing_a_test_with_an_error():
    salvaged = ledger.salvage_behaviors(PROBLEMS)(_with_bad_behavior())
    assert [b["claim"] for b in salvaged["behaviors"]] == ["Sequential requests stop at 5"]
    assert salvaged["dropped_behaviors"] == [{"behavior": {"claim": "Login shows 'Invalid email or password'",
                                                           "tests": [13]},
                                              "why": f'cites test 13, which recorded "{LOGIN_401}"'}]
    assert _validate(salvaged) == []
    assert ledger.salvage_behaviors(PROBLEMS)(_hypothesis()) is None        # nothing to drop: no salvage
    assert ledger.salvage_behaviors(PROBLEMS)({"behaviors": "x"}) is None


def test_the_run_goes_on_after_three_tries_and_any_other_fault_still_fails():
    bad = _with_bad_behavior()
    client = _FakeClient([_FakeMessage([_FakeToolUse(f"id{n}", bad)]) for n in (1, 2, 3)])
    result = call_tool_with_retry(client, model="m", system="s", tools=[], tool_name="submit_checkpoint_hypothesis",
                                  user_message="u", validate_fn=_validate, max_tokens=10, max_attempts=3,
                                  salvage_fn=ledger.salvage_behaviors(PROBLEMS))
    assert client.messages.call_count == 3 and len(result["dropped_behaviors"]) == 1
    worse = {**bad, "summary": 7}
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", worse)])])
    with pytest.raises(RuntimeError, match="Gave up after 1 attempts"):
        call_tool_with_retry(client, model="m", system="s", tools=[], tool_name="submit_checkpoint_hypothesis",
                             user_message="u", validate_fn=_validate, max_tokens=10, max_attempts=1,
                             salvage_fn=ledger.salvage_behaviors(PROBLEMS))


def test_the_report_shows_what_was_dropped():
    entry = {**_EMPTY_CHECKPOINT, "hypothesis": {**_EMPTY_CHECKPOINT["hypothesis"], "dropped_behaviors": [
        {"behavior": {"claim": "Login works", "tests": [13]}, "why": "cites test 13, which recorded \"x\""}]}}
    html = _render_checkpoint(1, entry, {}, lambda e: "")
    assert "Dropped from behaviour, still wrong at the last try" in html and "Login works" in html


def test_the_loop_gives_the_hypothesis_call_the_salvage(monkeypatch):
    from trailhound import loop
    from trailhound.config import RunConfig
    seen = {}

    def fake(client, **kw):
        seen.update(kw)
        return kw["salvage_fn"](_with_bad_behavior())
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    adapter = type("A", (), {"api_schema_doc": "doc", "onboarding_extra": {}, "redact_history_for_model": None})()
    hypothesis = loop.get_checkpoint_hypothesis(None, adapter, RunConfig(), {}, [], test_problems=PROBLEMS)
    assert seen["tool_name"] == "submit_checkpoint_hypothesis" and len(hypothesis["dropped_behaviors"]) == 1
