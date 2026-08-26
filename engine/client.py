"""Anthropic client construction and the shared call->validate->retry loop
used by every tool-forced call in the checkpoint loop. Identical logic
existed in every prior experiment's run_live.py."""

import os
import time

import anthropic
from anthropic import Anthropic
from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-4-6"
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


def build_client() -> Anthropic:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env (see .env.example)")
    return Anthropic(api_key=api_key)


def _cache_breakpoint(tools: list[dict], system: str) -> tuple[list[dict], list[dict] | str]:
    """Marks the end of tools and the end of system as cache breakpoints, so
    Anthropic caches that whole static prefix (tool schema + system prompt)
    and only the actual messages - which change every call - are billed and
    processed fresh. Caching is a pure serving-cost optimization: the model
    still reasons over the same content either way, it's just not re-billed
    or re-processed when byte-identical to a recent prior call.
    """
    cached_tools = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}] if tools else tools
    cached_system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return cached_tools, cached_system


def call_tool_with_retry(
    client, *, model, system, tools, tool_name, user_message, validate_fn, max_tokens,
    max_attempts=DEFAULT_MAX_ATTEMPTS, cache_static_content=False, cached_content=None,
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

    cached_content, if given, is placed as its own content block BEFORE user_message and marked
    cacheable - for a call site whose evidence has a large, append-only-growing prefix (e.g. a
    replayed test history) shared with the immediately preceding call of the same kind. Anthropic
    caches by exact byte-prefix match, so this only pays off when cached_content is either
    byte-identical to, or an extension of, what a recent call of the SAME call site already sent;
    it does not share anything across different call sites (they have different system prompts
    and content to begin with, so there is no prefix to match regardless). user_message stays the
    small, call-specific remainder that changes every time and is never cached.
    """
    request_tools, request_system = (
        _cache_breakpoint(tools, system) if cache_static_content else (tools, system)
    )
    if cached_content is not None:
        content = [
            {"type": "text", "text": cached_content, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": user_message},
        ]
    else:
        content = user_message
    messages = [{"role": "user", "content": content}]
    last_errors = ["no attempts made"]
    for attempt in range(1, max_attempts + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=request_system,
                tools=request_tools,
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

        last_errors = errors
        print(f"  attempt {attempt} produced malformed output: {errors} - retrying")
        messages.append({"role": "assistant", "content": message.content})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": "Invalid: " + "; ".join(errors) + ". Fix and call the tool again with a corrected, complete answer.",
                "is_error": True,
            }],
        })

    raise RuntimeError(f"Gave up after {max_attempts} attempts, last errors: {last_errors}")
