"""call_tool_with_retry's validate-fail -> retry-with-feedback -> RuntimeError
path, plus transient-vs-permanent API error handling, checked against a
stubbed Anthropic client - no network calls."""

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


def test_cache_static_content_marks_breakpoints_on_system_and_last_tool():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])

    call_tool_with_retry(
        client, model="m", system="a system prompt", tools=[{"name": "t1"}, {"name": "t2"}], tool_name="t2",
        user_message="u", validate_fn=lambda d: [], max_tokens=10, cache_static_content=True,
    )

    sent = client.messages.last_kwargs
    assert sent["system"] == [{"type": "text", "text": "a system prompt", "cache_control": {"type": "ephemeral"}}]
    assert sent["tools"] == [
        {"name": "t1"},
        {"name": "t2", "cache_control": {"type": "ephemeral"}},
    ]


def test_cache_static_content_does_not_mutate_the_original_tools_list():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})])])
    original_tools = [{"name": "t"}]

    call_tool_with_retry(
        client, model="m", system="s", tools=original_tools, tool_name="t", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, cache_static_content=True,
    )

    assert original_tools == [{"name": "t"}]


def test_usage_sink_records_one_entry_per_raw_response():
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"ok": True})], usage=_FakeUsage(
        input_tokens=120, output_tokens=45, cache_creation_input_tokens=0, cache_read_input_tokens=900,
    ))])
    usage_sink = []

    call_tool_with_retry(
        client, model="m", system="s", tools=[], tool_name="submit_x", user_message="u",
        validate_fn=lambda d: [], max_tokens=10, usage_sink=usage_sink,
    )

    assert usage_sink == [{
        "call": "submit_x", "input_tokens": 120, "output_tokens": 45,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900,
    }]


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
        {"call": "submit_casting_round", "input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        {"call": "submit_casting_round", "input_tokens": 50, "output_tokens": 15, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900},
        {"call": "submit_skeptic_review", "input_tokens": 300, "output_tokens": 40, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
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
