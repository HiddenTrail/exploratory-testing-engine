"""The hypothesis summary says what the tests found, never a verdict on the product (issue
#341). No model calls."""

import pytest

from trailhound import loop
from trailhound.config import RunConfig
from trailhound.tests.test_hypothesis_schema import _hypothesis
from trailhound.tools import HYPOTHESIS_SYSTEM_PROMPT, HYPOTHESIS_TOOL, summary_verdict_errors


@pytest.mark.parametrize("summary, said", [
    ("Juice Shop behaves largely as expected: no obvious new bugs found.", "as expected"),
    ("Core flows work mechanically, but the basket has no quantity input.", "work mechanically"),
    ("Juice Shop behaves normally across cart and checkout.", "behaves normally"),
    ("No new bugs; the profile 403 reproduces.", "No new bugs"),
    ("Search: no issues found.", "no issues"),
    ("Everything works.", "Everything works"),
    ("Nothing wrong found; the 403 reproduces.", "Nothing wrong"),
    ("Login is working as intended.", "as intended"),
    ("No regressions since the last checkpoint.", "No regressions"),
])
def test_a_verdict_on_the_product_is_sent_back(summary, said):
    [error] = summary_verdict_errors(_hypothesis(summary=summary))
    assert error.startswith(f"'summary' gives a verdict on the product (\"{said}\"): this checkpoint's tests can't show that.")
    assert error.endswith("this is asked once.")


def test_a_summary_of_what_the_tests_showed_is_fine():
    for summary in ("Checkout works from a reliable state; /profile emits a 403 on every load.",
                    "The profile 403 reproduces; login and basket were tested, checkout wasn't."):
        assert summary_verdict_errors(_hypothesis(summary=summary)) == []
    assert summary_verdict_errors({"summary": 7}) == [] and summary_verdict_errors(None) == []


def test_the_driver_is_told_and_asked_once_never_on_the_last_try(monkeypatch):
    from trailhound.client import call_tool_with_retry
    from trailhound.tests.test_client_retry import _FakeClient, _FakeMessage, _FakeToolUse
    from trailhound.tools import validate_hypothesis_response
    assert "never a verdict on the product or a whole area" in HYPOTHESIS_SYSTEM_PROMPT
    assert "Not a verdict on the product" in HYPOTHESIS_TOOL["input_schema"]["properties"]["summary"]["description"]
    judging = _hypothesis(summary="Juice Shop behaves largely as expected.")
    call = lambda client, attempts: call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="submit_checkpoint_hypothesis", user_message="u",
        validate_fn=validate_hypothesis_response, max_tokens=10, max_attempts=attempts, nudge_fn=summary_verdict_errors)
    # Asked once, then taken as it is.
    client = _FakeClient([_FakeMessage([_FakeToolUse(f"id{n}", judging)]) for n in (1, 2)])
    assert call(client, 3) == judging and client.messages.call_count == 2
    # Found in review: a verdict first seen on the last try failed the call and ended the run.
    broken = {k: v for k, v in judging.items() if k != "observations"}
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", broken)]), _FakeMessage([_FakeToolUse("id2", judging)])])
    assert call(client, 2) == judging and client.messages.call_count == 2
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", judging)])])
    assert call(client, 1) == judging


def test_the_loop_passes_the_summary_check_as_a_nudge(monkeypatch):
    seen = {}
    monkeypatch.setattr(loop, "call_tool_with_retry", lambda client, **kw: seen.update(kw) or _hypothesis())
    adapter = type("A", (), {"api_schema_doc": "doc", "onboarding_extra": {}, "redact_history_for_model": None})()
    loop.get_checkpoint_hypothesis(None, adapter, RunConfig(), {}, [])
    assert seen["nudge_fn"] is summary_verdict_errors
