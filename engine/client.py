"""Anthropic client construction and the shared call->validate->retry loop
used by every tool-forced call in the checkpoint loop. Identical logic
existed in every prior experiment's run_live.py."""

import os
import time
from datetime import datetime, timezone

import anthropic
from anthropic import Anthropic, AnthropicBedrockMantle
from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-4-6"
# Bedrock's Messages-API endpoint does NOT carry claude-sonnet-4-6, so a
# Bedrock run cannot be on the same model as a direct-API run - this is the
# nearest equivalent: same Sonnet tier, and the same 1024-token minimum
# cacheable prefix, so prompt-caching behaviour stays comparable even though
# the model doesn't. Verified available in eu-west-1 alongside
# anthropic.claude-{opus-5,opus-4-8,opus-4-7,haiku-4-5}.
#
# Note these are NOT the IDs that `aws bedrock list-inference-profiles` prints:
# the eu.*/global.* inference-profile IDs belong to the older bedrock-runtime
# InvokeModel path and are rejected here. To check a candidate, attempt a
# one-token call - an unavailable model 404s immediately and costs nothing.
DEFAULT_BEDROCK_MODEL = "anthropic.claude-sonnet-5"
DEFAULT_MAX_ATTEMPTS = 3

# The SDK's own client already retries these internally (its own max_retries,
# default a couple of attempts) before ever raising - if one of these still
# reaches us, that budget is exhausted too. Worth another try at our level
# with backoff, since a checkpoint call is expensive to have to restart from
# scratch. Deliberately NOT retrying AuthenticationError/PermissionDeniedError/
# BadRequestError/NotFoundError/etc. - those are permanent problems (bad key,
# malformed request); retrying just burns time and attempt budget for nothing.
_RETRYABLE_API_ERRORS = (
    anthropic.APIConnectionError,  # covers APITimeoutError too (subclass)
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def use_bedrock() -> bool:
    """Whether to authenticate through Amazon Bedrock instead of a direct
    Anthropic API key. Mirrors how Claude Code itself is configured
    (CLAUDE_CODE_USE_BEDROCK=1 + AWS_PROFILE + AWS_REGION), but under the
    engine's own variable name so the two are independently switchable - the
    harness you author with and the engine you run are separate clients that
    happen to talk to the same models.
    """
    load_dotenv()
    return os.environ.get("ENGINE_USE_BEDROCK", "").strip().lower() in ("1", "true", "yes")


def default_model() -> str:
    """Resolved at call time, not import time: which model ID is valid depends
    on which provider build_client() is about to construct, and .env is only
    loaded once use_bedrock() runs."""
    return DEFAULT_BEDROCK_MODEL if use_bedrock() else DEFAULT_MODEL


def build_client() -> Anthropic | AnthropicBedrockMantle:
    """Both clients expose the same messages.create surface, so nothing
    downstream of here needs to know which provider is in play - only the model
    ID differs (see DEFAULT_BEDROCK_MODEL)."""
    if use_bedrock():
        # Credentials come from the standard AWS chain (SSO cache, profile,
        # env vars, instance role) - deliberately no key handling of our own.
        # Region is required: the SDK raises at construction rather than
        # silently defaulting, so fail here with an actionable message instead.
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            raise SystemExit(
                "ENGINE_USE_BEDROCK is set but no region is configured - "
                "set AWS_REGION (e.g. eu-west-1) in .env or your shell (see .env.example)"
            )
        profile = os.environ.get("AWS_PROFILE")
        return AnthropicBedrockMantle(aws_region=region, aws_profile=profile)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "Set ANTHROPIC_API_KEY in .env, or set ENGINE_USE_BEDROCK=1 to "
            "authenticate through Bedrock instead (see .env.example)"
        )
    return Anthropic(api_key=api_key)


def _cache_breakpoint(system: str) -> list[dict]:
    """Marks the end of the system prompt as a cache breakpoint. A marker there
    covers the whole static prefix - tools render before system, so one system
    breakpoint caches tool schema *and* system prompt together, and marking the
    last tool as well would only spend one of the four available breakpoints to
    cache a strictly shorter prefix. Only the actual messages - which change
    every call - are then billed and processed fresh. Caching is a pure
    serving-cost optimization: the model still reasons over the same content
    either way, it's just not re-billed or re-processed when byte-identical to
    a recent prior call.
    """
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


# Anthropic allows 4 cache_control markers per request; _cache_breakpoint spends
# one on system+tools, leaving these for the message content blocks.
_MAX_MESSAGE_BREAKPOINTS = 3


def _breakpoint_indexes(segment_count: int) -> set[int]:
    """Which of cached_segments get a cache_control marker: the first, the
    second-to-last, and the last.

    The cache only ever matches at a *block boundary that carried a marker*, so
    for an append-only sequence of segments the marker positions are what decide
    whether the next call reads anything at all:

    - last: writes a cache entry covering everything sent this call, which is
      the prefix the NEXT call (this call's segments plus one new one) starts
      with. Without it that next call has nothing to hit.
    - second-to-last: where the *previous* call put its "last" marker, i.e. the
      boundary the entry being read actually ends at. Re-marking it is what
      keeps that entry alive as the window slides forward.
    - first: the run-static evidence. A floor - if the sliding pair ever misses,
      this still gets credited instead of dropping to zero.

    Three markers, so it fits _MAX_MESSAGE_BREAKPOINTS for any segment count.
    """
    return {index for index in (0, segment_count - 2, segment_count - 1) if index >= 0}


def _cacheable_content(cached_segments: list[str], user_message: str) -> list[dict]:
    marked = _breakpoint_indexes(len(cached_segments))
    content = []
    for index, segment in enumerate(cached_segments):
        block = {"type": "text", "text": segment}
        if index in marked:
            block["cache_control"] = {"type": "ephemeral"}
        content.append(block)
    content.append({"type": "text", "text": user_message})
    return content


def _now_iso() -> str:
    """Wall-clock stamp for usage records. Wall clock rather than a monotonic
    reading because the thing it exists to measure - cache TTL expiry - is a
    real-time, 5-minute window, and because an absolute timestamp survives being
    written to output.json as something a human can still read later."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_usage(usage_sink: list[dict] | None, tool_name: str, usage) -> None:
    """usage is the Anthropic response's .usage (input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens) - absent on stubbed
    messages in tests, so both the sink and the attribute are optional.
    Recorded per raw API response (including malformed-tool-use retries),
    since those still cost real tokens.

    "at" is what makes a zero cache_read diagnosable after the fact: a gap of
    more than the 5-minute TTL since the previous call of the same name explains
    it as plain expiry, while a short gap points at the prompt's own prefix
    having changed."""
    if usage_sink is None or usage is None:
        return
    usage_sink.append({
        "call": tool_name,
        "at": _now_iso(),
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    })


def summarize_usage(usage_log: list[dict]) -> dict[str, dict]:
    """Aggregates per-call usage records (see _record_usage) into one totals
    row per tool_name - the shape written to output.json's usage_summary and
    printed at the end of a run."""
    summary: dict[str, dict] = {}
    for record in usage_log:
        agg = summary.setdefault(record["call"], {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        })
        agg["calls"] += 1
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            agg[key] += record[key]
    return summary


def call_tool_with_retry(
    client, *, model, system, tools, tool_name, user_message, validate_fn, max_tokens,
    max_attempts=DEFAULT_MAX_ATTEMPTS, cache_static_content=False, cached_segments=None, usage_sink=None,
):
    """Retries are informed, not blind repeats: on failure, the model's own malformed call and
    the concrete validation errors are fed back as a tool_result before asking again, so a
    systematic misunderstanding (e.g. an omitted required field) has a chance to self-correct
    instead of reproducing the identical mistake on every attempt. Transient API errors (rate
    limits, connection issues, 5xx) share the same attempt budget, retried with backoff rather
    than fed back as a message, since there's no "correction" to make - just try again.

    cache_static_content marks the tool schema and system prompt as cacheable - worthwhile at
    call sites where they're byte-identical across many calls in a run (e.g. every checkpoint),
    left off by default so opting a given call site in is a deliberate choice, not a silent
    blanket change to every call's request shape.

    cached_segments, if given, are placed as their own content blocks BEFORE user_message, some of
    them marked cacheable (see _breakpoint_indexes) - for a call site whose evidence has a large,
    append-only-growing prefix (e.g. a replayed test history) shared with the immediately preceding
    call of the same kind. Anthropic caches by exact byte-prefix match, so this only pays off when
    the segments are byte-identical to, or an append-only extension of, what a recent call of the
    SAME call site already sent; it does not share anything across different call sites (they have
    different system prompts and content to begin with, so there is no prefix to match regardless).

    Passing them as a LIST rather than one concatenated string is the whole point: a cache entry
    can only start or end at a content-block boundary, so growing evidence held in a single block
    puts every previous call's boundary in the middle of this call's block, where no entry can end,
    and nothing is ever read back however append-only the text itself was. One block per appended
    chunk gives the boundaries somewhere real to land. user_message stays the small, call-specific
    remainder that changes every time and is never cached.

    usage_sink, if given, gets one record appended per raw API response (see _record_usage) -
    the caller's way of collecting real cache_read/cache_creation/input/output token counts
    across a run without changing this function's return value.
    """
    request_system = _cache_breakpoint(system) if cache_static_content else system
    content = _cacheable_content(cached_segments, user_message) if cached_segments else user_message
    messages = [{"role": "user", "content": content}]
    last_errors = ["no attempts made"]
    for attempt in range(1, max_attempts + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=request_system,
                tools=tools,
                tool_choice={"type": "tool", "name": tool_name},
                messages=messages,
            )
        except _RETRYABLE_API_ERRORS as e:
            action = "retrying" if attempt < max_attempts else "giving up"
            last_errors = [f"transient API error ({type(e).__name__}): {e}"]
            print(f"  attempt {attempt} hit {last_errors[0]} - {action}")
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 30))
            continue

        usage = getattr(message, "usage", None)
        _record_usage(usage_sink, tool_name, usage)
        if usage is not None:
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
            print(
                f"  [{tool_name}] tokens: input={usage.input_tokens} "
                f"(cache_read={cache_read}, cache_creation={cache_creation}) output={usage.output_tokens}"
            )

        tool_use = next((block for block in message.content if block.type == "tool_use"), None)
        if tool_use is None:
            last_errors = [f"no tool_use block in response (stop_reason={message.stop_reason})"]
            print(f"  attempt {attempt} produced no tool call: {last_errors} - retrying")
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call the tool. Try again."})
            continue

        errors = validate_fn(tool_use.input)
        if not errors:
            return tool_use.input

        # A reply that ran out of budget fails validation too, and it fails it in a way
        # that impersonates a model ignoring the instructions - a schema-shaped answer
        # missing whatever came last. Told "your output was invalid, fix it" the model
        # writes the same too-long answer again and is cut off at the same place, so the
        # whole attempt budget buys three identical failures. The actionable correction
        # is not "be correct", it is "be shorter", so say which one this is.
        truncated = message.stop_reason == "max_tokens"
        last_errors = ([f"reply was cut off at max_tokens={max_tokens}: " + "; ".join(errors)]
                       if truncated else errors)
        if truncated:
            print(f"  attempt {attempt} was cut off at max_tokens={max_tokens} "
                  f"({errors}) - retrying, asking for a terser answer")
        else:
            print(f"  attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        correction = (
            f"Your reply hit the {max_tokens}-token limit and was cut off, so it is "
            f"incomplete: {'; '.join(errors)}. Answer again, complete this time, and keep "
            f"every free-text field to one short sentence - completeness matters more "
            f"than detail."
            if truncated else
            "Invalid: " + "; ".join(errors) +
            ". Fix and call the tool again with a corrected, complete answer.")
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": correction,
                "is_error": True,
            }],
        })

    raise RuntimeError(f"Gave up after {max_attempts} attempts, last errors: {last_errors}")
