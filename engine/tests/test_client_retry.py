"""call_tool_with_retry's validate-fail -> retry-with-feedback -> RuntimeError
path, plus transient-vs-permanent API error handling, checked against a
stubbed Anthropic client - no network calls."""

from datetime import datetime

import httpx
import pytest

import anthropic
from engine.client import call_tool_with_retry, summarize_usage


class _FakeToolUse:
    def __init__(self, id, input):
        self.type = "tool_use"
        self.id = id
        self.input = input


class _FakeUsage:
    def __init__(self, input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _FakeMessage:
    def __init__(self, content, stop_reason="tool_use", usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class _FakeMessagesAPI:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        item = next(self._responses)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessagesAPI(responses)


_FROZEN_AT = "2026-08-26T09:00:00+00:00"


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pins the usage records' "at" stamp so they can still be asserted whole,
    rather than field by field around an unpredictable timestamp."""
    monkeypatch.setattr("engine.client._now_iso", lambda: _FROZEN_AT)


def _connection_error():
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=request), body=None)


def _auth_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError("invalid api key", response=httpx.Response(401, request=request), body=None)


def test_retry_succeeds_after_one_validation_failure():
    responses = [
        _FakeMessage([_FakeToolUse("id1", {"bad": True})]),
        _FakeMessage([_FakeToolUse("id2", {"ok": True})]),
    ]
    client = _FakeClient(responses)

    def validate(data):
        return [] if data.get("ok") else ["missing 'ok'"]

    result = call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=validate, max_tokens=10, max_attempts=3,
    )
    assert result == {"ok": True}


def test_raises_after_max_attempts_exhausted():
    responses = [_FakeMessage([_FakeToolUse(f"id{i}", {"bad": True})]) for i in range(5)]
    client = _FakeClient(responses)

    def validate(data):
        return ["always fails"]

    with pytest.raises(RuntimeError, match="Gave up after 2 attempts"):
        call_tool_with_retry(
            client, model="m", system="s", tools=[], tool_name="t", user_message="u",
            validate_fn=validate, max_tokens=10, max_attempts=2,
        )


def test_retries_when_no_tool_use_block_returned():
    responses = [
        _FakeMessage([], stop_reason="end_turn"),
        _FakeMessage([_FakeToolUse("id2", {"ok": True})]),
    ]
    client = _FakeClient(responses)

    def validate(data):
        return [] if data.get("ok") else ["missing 'ok'"]

    result = call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=validate, max_tokens=10, max_attempts=3,
    )
    assert result == {"ok": True}


def test_retries_on_transient_connection_error(monkeypatch):
    monkeypatch.setattr("engine.client.time.sleep", lambda s: None)
    responses = [_connection_error(), _FakeMessage([_FakeToolUse("id1", {"ok": True})])]
    client = _FakeClient(responses)

    result = call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, max_attempts=3,
    )
    assert result == {"ok": True}
    assert client.messages.call_count == 2


def test_retries_on_rate_limit_error(monkeypatch):
    monkeypatch.setattr("engine.client.time.sleep", lambda s: None)
    responses = [_rate_limit_error(), _FakeMessage([_FakeToolUse("id1", {"ok": True})])]
    client = _FakeClient(responses)

    result = call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, max_attempts=3,
    )
    assert result == {"ok": True}
    assert client.messages.call_count == 2


def test_raises_runtime_error_after_max_attempts_of_transient_errors(monkeypatch):
    monkeypatch.setattr("engine.client.time.sleep", lambda s: None)
    responses = [_connection_error(), _rate_limit_error(), _connection_error()]
    client = _FakeClient(responses)

    with pytest.raises(RuntimeError, match="Gave up after 3 attempts"):
        call_tool_with_retry(
            client, model="m", system="s", tools=[], tool_name="t", user_message="u",
            validate_fn=lambda d: [], max_tokens=10, max_attempts=3,
        )
    assert client.messages.call_count == 3


def test_cache_static_content_off_by_default_leaves_system_and_tools_untouched():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="a system prompt", tools=[{"name": "t"}], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10,
    )

    assert client.messages.last_kwargs["system"] == "a system prompt"
    assert client.messages.last_kwargs["tools"] == [{"name": "t"}]


def test_cache_static_content_marks_one_breakpoint_at_the_end_of_system():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="a system prompt", tools=[{"name": "t1"}, {"name": "t2"}], tool_name="t2",
        user_message="u", validate_fn=lambda d: [], max_tokens=10, cache_static_content=True,
    )

    sent = client.messages.last_kwargs
    assert sent["system"] == [{"type": "text", "text": "a system prompt", "cache_control": {"type": "ephemeral"}}]
    # Tools render BEFORE system, so the system marker already caches them too -
    # marking the last tool as well would spend a second of the four available
    # breakpoints on a strictly shorter prefix.
    assert sent["tools"] == [{"name": "t1"}, {"name": "t2"}]


def test_cache_static_content_does_not_mutate_the_original_tools_list():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])
    original_tools = [{"name": "t"}]

    call_tool_with_retry(
        client, model="m", system="s", tools=original_tools, tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, cache_static_content=True,
    )

    assert original_tools == [{"name": "t"}]


def _sent_content(client):
    return client.messages.last_kwargs["messages"][0]["content"]


def _marked_indexes(content):
    return [i for i, block in enumerate(content) if "cache_control" in block]


def test_no_cached_segments_sends_the_user_message_as_a_plain_string():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10,
    )

    assert _sent_content(client) == "u"


def test_cached_segments_become_one_content_block_each_ahead_of_the_user_message():
    # One block per segment is the whole point: a cache entry can only end at a
    # block boundary, so joining these would put the previous call's boundary
    # mid-block, where nothing can be read back.
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="fresh",
        validate_fn=lambda d: [], max_tokens=10, cached_segments=["base", "cp1", "cp2"],
    )

    content = _sent_content(client)
    assert [block["text"] for block in content] == ["base", "cp1", "cp2", "fresh"]
    assert "cache_control" not in content[-1], "the changing remainder must never be marked"


@pytest.mark.parametrize("count,expected", [
    (1, [0]),
    (2, [0, 1]),
    (3, [0, 1, 2]),
    (4, [0, 2, 3]),
    (7, [0, 5, 6]),
])
def test_breakpoints_sit_on_the_first_and_the_last_two_segments(count, expected):
    # first = the run-static floor; last = writes the entry the NEXT call reads;
    # second-to-last = the boundary the entry being read this call ends at.
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10,
        cached_segments=[f"s{i}" for i in range(count)],
    )

    assert _marked_indexes(_sent_content(client)) == expected


@pytest.mark.parametrize("count", [1, 2, 3, 4, 12, 60])
def test_total_breakpoints_never_exceed_the_four_anthropic_allows(count):
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="s", tools=[{"name": "t"}], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, cache_static_content=True,
        cached_segments=[f"s{i}" for i in range(count)],
    )

    sent = client.messages.last_kwargs
    system_marks = sum("cache_control" in block for block in sent["system"])
    tool_marks = sum("cache_control" in tool for tool in sent["tools"])
    assert system_marks + tool_marks + len(_marked_indexes(_sent_content(client))) <= 4


def test_a_growing_segment_list_reuses_the_previous_calls_last_boundary():
    # The regression this whole design exists to prevent: what call N marked
    # last has to still be a marked boundary at call N+1, or the entry it wrote
    # is unreadable and every call pays full price.
    client = _FakeClient([
        _FakeMessage([_FakeToolUse("id1", {"ok": True})]),
        _FakeMessage([_FakeToolUse("id2", {"ok": True})]),
    ])
    segments = ["base", "cp1", "cp2"]

    def send():
        call_tool_with_retry(
            client, model="m", system="s", tools=[], tool_name="t", user_message="u",
            validate_fn=lambda d: [], max_tokens=10, cached_segments=list(segments),
        )
        return {_sent_content(client)[i]["text"] for i in _marked_indexes(_sent_content(client))}

    first_call_marks = send()
    segments.append("cp3")
    second_call_marks = send()

    assert "cp2" in first_call_marks and "cp2" in second_call_marks


def test_usage_sink_records_one_entry_per_raw_response(frozen_clock):
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})], usage=_FakeUsage(
        input_tokens=120, output_tokens=45, cache_creation_input_tokens=0, cache_read_input_tokens=900,
    ))])
    usage_sink = []

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="submit_x", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, usage_sink=usage_sink,
    )

    assert usage_sink == [{
        "call": "submit_x", "at": _FROZEN_AT, "input_tokens": 120, "output_tokens": 45,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900,
    }]


def test_usage_records_carry_a_timestamp_so_a_cache_miss_can_be_attributed():
    # Without it, a cache_read of 0 is ambiguous: TTL expiry between two calls
    # looks exactly like the prompt's cacheable prefix having changed.
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})], usage=_FakeUsage(input_tokens=1))])
    usage_sink = []

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, usage_sink=usage_sink,
    )

    assert datetime.fromisoformat(usage_sink[0]["at"]).tzinfo is not None, "must be unambiguous UTC"


def test_usage_sink_records_every_attempt_including_a_failed_validation_retry():
    responses = [
        _FakeMessage([_FakeToolUse("id1", {"bad": True})], usage=_FakeUsage(input_tokens=100, output_tokens=10)),
        _FakeMessage([_FakeToolUse("id2", {"ok": True})], usage=_FakeUsage(input_tokens=110, output_tokens=12)),
    ]
    client = _FakeClient(responses)
    usage_sink = []

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [] if d.get("ok") else ["missing 'ok'"], max_tokens=10, usage_sink=usage_sink,
    )

    assert len(usage_sink) == 2
    assert [r["input_tokens"] for r in usage_sink] == [100, 110]


def test_usage_sink_untouched_when_message_has_no_usage_attribute():
    # No usage kwarg passed to _FakeMessage - matches every other test in this
    # file, and stubbed messages elsewhere that don't model .usage at all.
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])
    usage_sink = []

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, usage_sink=usage_sink,
    )

    assert usage_sink == []


def test_summarize_usage_aggregates_per_call_type():
    usage_log = [
        {"call": "submit_casting_round", "at": _FROZEN_AT, "input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        {"call": "submit_casting_round", "at": _FROZEN_AT, "input_tokens": 50, "output_tokens": 15, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900},
        {"call": "submit_skeptic_review", "at": _FROZEN_AT, "input_tokens": 300, "output_tokens": 40, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    ]

    summary = summarize_usage(usage_log)

    assert summary == {
        "submit_casting_round": {
            "calls": 2, "input_tokens": 150, "output_tokens": 35,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900,
        },
        "submit_skeptic_review": {
            "calls": 1, "input_tokens": 300, "output_tokens": 40,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        },
    }


def test_summarize_usage_of_empty_log_is_empty():
    assert summarize_usage([]) == {}


def test_non_retryable_error_propagates_immediately_without_retrying(monkeypatch):
    monkeypatch.setattr(
        "engine.client.time.sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("should not sleep/retry")),
    )
    responses = [_auth_error(), _FakeMessage([_FakeToolUse("id1", {"ok": True})])]
    client = _FakeClient(responses)

    with pytest.raises(anthropic.AuthenticationError):
        call_tool_with_retry(
            client, model="m", system="s", tools=[], tool_name="t", user_message="u",
            validate_fn=lambda d: [], max_tokens=10, max_attempts=3,
        )
    # A permanent error (bad API key) shouldn't burn attempt budget retrying -
    # only the first, failing call should have happened.
    assert client.messages.call_count == 1
