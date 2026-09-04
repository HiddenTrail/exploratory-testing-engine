"""The property prompt caching actually depends on: the evidence a checkpoint
call sends is an append-only extension, segment for segment, of what the
previous call of the SAME call site sent. Anthropic credits a cached prefix
only where a marked content-block boundary matches byte for byte, so a segment
that gets re-rendered - even into identical-looking text - or a list that gets
joined into one block invalidates everything after it. Checked here without any
network calls, by capturing what the loop hands to the Anthropic-calling
functions rather than by inspecting a real request.
"""

import itertools

import engine.loop as loop
from engine.adapter import SUTAdapter
from engine.config import RunConfig

_ADAPTER = SUTAdapter(
    name="fake",
    display_name="Fake",
    base_url="http://example.invalid",
    test_endpoint_path="/x",
    casting_tool_schema={},
    casting_system_prompt=lambda budget, is_first: "",
    validate_casting_response=lambda data: [],
    execute_test=lambda test, test_number: {
        "test_number": test_number, "request": {"n": test_number}, "response": {},
        "predicted_outcome": "", "prediction_matched": True,
    },
    render_test_entry=lambda entry: "",
    render_onboarding_section=lambda *a: "",
)

_HAPPY_DAY = {"request": {"method": "POST", "path": "/x", "body": {}}, "response": {"status": 200, "body": {}}}


def _capture_segments(monkeypatch, *, max_checkpoints):
    """Runs the loop with the three LLM calls stubbed, returning the
    history_segments list each casting/hypothesis call was given, in order."""
    seen = {"casting": [], "hypothesis": []}

    def fake_casting(client, adapter, run_config, happy_day_example, history_segments, prior_feedback,
                     *, test_budget, is_first_round, usage_sink=None, run_diagnostics=None):
        seen["casting"].append(list(history_segments))
        return {"give_up": False, "reasoning": "r", "candidate_tests": [{"linked_hypothesis": "", "predicted_outcome": "x"}]}

    def fake_hypothesis(client, adapter, run_config, happy_day_example, history_segments,
                        prior_skeptic_review=None, run_diagnostics=None, usage_sink=None):
        seen["hypothesis"].append(list(history_segments))
        return {"observed_behavior": "b", "anomalies": [], "untested_areas": ["u"], "prior_gaps_response": []}

    def fake_skeptic(client, run_config, hypothesis, prior_skeptic_review=None, usage_sink=None):
        return {
            "verdict": "weak", "gaps": ["g"], "coverage_breadth": {"material": False, "note": "c"},
            "anomaly_checks": [], "recommended_next_tests": ["t"], "prior_critique_addressed": "n/a",
        }

    monkeypatch.setattr(loop, "get_casting_round", fake_casting)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", fake_skeptic)

    loop.run_checkpoint_loop(
        client=None, adapter=_ADAPTER, run_config=RunConfig(max_checkpoints=max_checkpoints),
        happy_day_example=_HAPPY_DAY, test_counter=itertools.count(1),
    )
    return seen


def _assert_append_only(calls):
    for previous, current in zip(calls, calls[1:]):
        assert current[:len(previous)] == previous, (
            "a segment already sent was re-rendered or reordered - everything from "
            "there on stops matching the cached prefix"
        )
        assert len(current) >= len(previous)


def test_history_grows_append_only_for_the_casting_call_site(monkeypatch):
    seen = _capture_segments(monkeypatch, max_checkpoints=4)
    assert [len(segments) for segments in seen["casting"]] == [0, 1, 2, 3]
    _assert_append_only(seen["casting"])


def test_history_grows_append_only_for_the_hypothesis_call_site(monkeypatch):
    seen = _capture_segments(monkeypatch, max_checkpoints=4)
    assert [len(segments) for segments in seen["hypothesis"]] == [1, 2, 3, 4]
    _assert_append_only(seen["hypothesis"])


def test_each_checkpoint_contributes_exactly_one_new_segment(monkeypatch):
    # One block per checkpoint, not per test: the boundary that matters is the
    # one a whole checkpoint's worth of evidence ends at.
    seen = _capture_segments(monkeypatch, max_checkpoints=3)
    last = seen["hypothesis"][-1]
    assert len(last) == 3
    assert [f"--- checkpoint {n} ---" in segment for n, segment in enumerate(last, start=1)] == [True] * 3


def test_evidence_segments_pass_the_history_through_verbatim():
    segments = loop._cacheable_evidence_segments(_ADAPTER, _HAPPY_DAY, "ALL TESTS THIS SESSION", ["cp1", "cp2"])

    # The static head is one segment of its own; the history fragments are
    # forwarded untouched, so a fragment is byte-identical on every later call.
    assert segments[1:] == ["cp1", "cp2"]
    assert "=== ALL TESTS THIS SESSION ===" in segments[0]


def test_the_static_head_is_byte_identical_across_calls():
    # It's re-rendered from the adapter every call, so dict iteration order or
    # an unsorted json.dumps here would silently invalidate the whole prefix.
    first = loop._cacheable_evidence_segments(_ADAPTER, _HAPPY_DAY, "T", [])[0]
    second = loop._cacheable_evidence_segments(_ADAPTER, _HAPPY_DAY, "T", ["cp1"])[0]
    assert first == second


def test_a_rendered_fragment_is_stable_for_the_same_entries():
    entries = [{"b": 2, "a": 1, "response": {"z": 0, "y": 1}}]
    reordered = [{"a": 1, "response": {"y": 1, "z": 0}, "b": 2}]

    assert loop._render_history_fragment(2, entries) == loop._render_history_fragment(2, reordered)
