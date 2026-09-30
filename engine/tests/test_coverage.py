"""The coverage summary the Skeptic gets (issue #65): worked out in code from the
tests that ran and the adapter's casting schema, no LLM call."""

from engine import coverage, loop
from engine.adapters.registry import load_adapter


def _schema(sut):
    return load_adapter(sut).casting_tool_schema


def _fields(summary):
    return {f["field"]: f for f in summary["fields"]}


def test_complex_sut_shows_what_the_skeptic_once_called_untouched():
    # From runs/after41/complex_sut_2: the Skeptic listed "malformed/missing client_id"
    # and "priority=high" as untouched after tests #2 and #3 had sent them.
    tests = [
        {"linked_hypothesis": "h", "client_id": "race-test-1", "payload": "p", "priority": "normal",
         "request_count": 20, "concurrent": True, "predicted_outcome": "o", "predicted_correctness": "overcounted"},
        {"linked_hypothesis": "h", "client_id": "race-test-2", "payload": "p", "priority": "high",
         "request_count": 10, "concurrent": True, "predicted_outcome": "o", "predicted_correctness": "correct"},
        {"linked_hypothesis": "", "client_id": "", "payload": "empty client id test", "priority": "normal",
         "request_count": 1, "concurrent": False, "predicted_outcome": "o", "predicted_correctness": "correct"},
    ]
    summary = coverage.summarize(_schema("complex_sut"), tests)
    fields = _fields(summary)
    assert summary["tests_run"] == 3
    assert set(fields) == {"client_id", "payload", "priority", "request_count", "concurrent"}
    assert "" in fields["client_id"]["values_tried"]
    assert fields["priority"]["never_tried"] == []
    assert fields["request_count"]["values_tried"] == [1, 10, 20]
    assert fields["concurrent"]["never_tried"] == []


def test_token_purchase_lists_inputs_only_and_trims_long_values():
    tests = [{"linked_hypothesis": "h", "oracle_claim_id": "claim:data:01", "auth_token": "tok_live_9f2c8a41",
              "card_number": "4111001338908383", "expiry_month": 3, "expiry_year": 2028, "cvv": "915",
              "credit_count": 100, "predicted_outcome": "o", "predicted_status": "approved",
              "predicted_decline_reason": ""},
             {"auth_token": "x" * 50, "credit_count": 0}]
    fields = _fields(coverage.summarize(_schema("token_purchase"), tests))
    assert set(fields) == {"auth_token", "card_number", "expiry_month", "expiry_year", "cvv", "credit_count"}
    assert fields["credit_count"]["values_tried"] == [0, 100]
    assert fields["auth_token"]["values_tried"][1] == "x" * coverage.MAX_VALUE_CHARS + "..."
    assert "never_tried" not in fields["cvv"]   # free text has no fixed choices


def test_an_enum_value_never_sent_is_listed_and_long_value_lists_are_capped():
    tests = [{"priority": "normal", "concurrent": False, "request_count": n} for n in range(15)]
    fields = _fields(coverage.summarize(_schema("complex_sut"), tests))
    assert fields["priority"]["never_tried"] == ["high"]
    assert fields["concurrent"]["never_tried"] == [True]
    assert len(fields["request_count"]["values_tried"]) == coverage.MAX_VALUES
    assert fields["request_count"]["more_values"] == 5


def test_the_skeptic_gets_the_summary_as_evidence(monkeypatch):
    seen = {}
    monkeypatch.setattr(loop, "call_tool_with_retry", lambda client, **kw: seen.update(kw) or {})
    hypothesis = {"summary": "s", "behaviors": [], "observations": [], "untested": [], "prior_gaps": []}
    run_config = type("RC", (), {"model": "m", "max_attempts": 1})()
    loop.get_skeptic_review(None, run_config, hypothesis, test_coverage={"tests_run": 0, "fields": []})
    assert '"test_coverage"' in seen["user_message"]
