"""The generic Driver+Skeptic checkpoint loop: propose and execute a batch of
tests, form one hypothesis about behavior and any anomalies noticed, get a
cold Skeptic review, and either continue (Skeptic says "weak") or conclude
(Skeptic says "strong_enough" or the checkpoint cap is reached). Ported
almost verbatim from token-purchase-poc/run_live.py's unified checkpoint
loop - every module-global constant becomes a run_config/adapter read, and
every domain-specific call (test proposal schema, execute_test, prediction
matching) becomes an adapter read.
"""

import json

from anthropic import Anthropic

from engine.adapter import SUTAdapter
from engine.client import call_tool_with_retry
from engine.config import RunConfig
from engine.http import default_happy_day_example
from engine.redact import default_redact_history_for_model
from engine.tools import (
    BUG_REPORT_SYSTEM_PROMPT,
    BUG_REPORT_TOOL,
    HYPOTHESIS_SYSTEM_PROMPT,
    HYPOTHESIS_TOOL,
    SKEPTIC_SYSTEM_PROMPT,
    SKEPTIC_TOOL,
    validate_bug_reports,
    validate_hypothesis_response,
    validate_skeptic_response,
)


def _redact(adapter: SUTAdapter, casting_log: list[dict]) -> list[dict]:
    redact_fn = adapter.redact_history_for_model or default_redact_history_for_model
    return redact_fn(casting_log)


def _base_evidence(adapter: SUTAdapter, happy_day_example: dict) -> dict:
    return {
        "api_schema": adapter.api_schema_doc,
        **adapter.onboarding_extra,
        "happy_day_example": happy_day_example,
    }


def _render_history_fragment(checkpoint_num: int, entries: list[dict]) -> str:
    """One checkpoint's worth of redacted test entries, as a fragment meant to
    be *appended* to a running list of fragments and never regenerated - see
    the docstring-level note in run_checkpoint_loop for why that matters for
    prompt caching. sort_keys pins the serialization so a fragment can't come
    out byte-different for content that didn't change."""
    return f"\n\n--- checkpoint {checkpoint_num} ---\n{json.dumps(entries, indent=2, sort_keys=True)}"


def _cacheable_evidence_segments(
    adapter: SUTAdapter, happy_day_example: dict, section_title: str, history_segments: list[str]
) -> list[str]:
    """The static evidence (schema, known accounts, oracle data, happy-day
    example - identical for the whole run) followed by the growing test history,
    as SEPARATE segments rather than one joined string: each becomes its own
    request content block, and a cache entry can only begin or end at a block
    boundary. Joined into one block, every previous call's boundary would fall
    in the middle of this call's block - a place no entry can end - so nothing
    would ever be read back no matter how append-only the text was. See
    call_tool_with_retry's cached_segments and run_checkpoint_loop.
    """
    head = (
        json.dumps(_base_evidence(adapter, happy_day_example), indent=2, sort_keys=True)
        + f"\n\n=== {section_title} ==="
    )
    return [head, *history_segments]


def get_happy_day_example(adapter: SUTAdapter) -> dict:
    """The adapter's own fetch, or the HTTP one every adapter so far has wanted."""
    return (adapter.fetch_happy_day_example or default_happy_day_example)(adapter)


def get_casting_round(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    happy_day_example: dict,
    history_segments: list[str],
    prior_checkpoint_feedback: dict | None = None,
    *,
    test_budget: int,
    is_first_round: bool,
    usage_sink: list[dict] | None = None,
) -> dict:
    # Known and unavoidable: the casting system prompt varies with test_budget
    # and is_first_round, and system renders BEFORE the messages, so checkpoint 2
    # can't read checkpoint 1's cache however stable the evidence blocks are.
    # Rounds 2..N share a prompt and do hit - measured 0 read at checkpoint 2,
    # then ~14k at checkpoint 3 - so it costs one extra write per run, not one
    # per checkpoint. Not worth flattening the prompt over.
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "TESTS TRIED IN EARLIER ROUNDS", history_segments
    )
    fresh_evidence = {}
    if prior_checkpoint_feedback is not None:
        fresh_evidence["prior_checkpoint_feedback"] = prior_checkpoint_feedback
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=adapter.casting_system_prompt(test_budget, is_first_round),
        tools=[adapter.casting_tool_schema],
        tool_name="submit_casting_round",
        cached_segments=cached_segments,
        user_message=json.dumps(fresh_evidence, indent=2),
        validate_fn=adapter.validate_casting_response,
        max_tokens=adapter.casting_max_tokens(test_budget),
        max_attempts=run_config.max_attempts,
        cache_static_content=True,
        usage_sink=usage_sink,
    )


def get_checkpoint_hypothesis(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    happy_day_example: dict,
    history_segments: list[str],
    prior_skeptic_review: dict | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "ALL TESTS THIS SESSION", history_segments
    )
    fresh_evidence = {}
    if prior_skeptic_review is not None:
        fresh_evidence["prior_skeptic_review"] = prior_skeptic_review
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=HYPOTHESIS_SYSTEM_PROMPT,
        tools=[HYPOTHESIS_TOOL],
        tool_name="submit_checkpoint_hypothesis",
        cached_segments=cached_segments,
        user_message=json.dumps(fresh_evidence, indent=2),
        validate_fn=validate_hypothesis_response,
        max_tokens=2560,
        max_attempts=run_config.max_attempts,
        cache_static_content=True,
        usage_sink=usage_sink,
    )


def get_skeptic_review(
    client: Anthropic, run_config: RunConfig, hypothesis: dict, prior_skeptic_review: dict | None = None,
    usage_sink: list[dict] | None = None,
) -> dict:
    evidence = {
        "observed_behavior": hypothesis["observed_behavior"],
        "anomalies": hypothesis["anomalies"],
        "untested_areas": hypothesis["untested_areas"],
        "prior_gaps_response": hypothesis.get("prior_gaps_response", []),
    }
    if prior_skeptic_review is not None:
        evidence["your_own_prior_review"] = prior_skeptic_review
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=SKEPTIC_SYSTEM_PROMPT,
        tools=[SKEPTIC_TOOL],
        tool_name="submit_skeptic_review",
        user_message=json.dumps(evidence, indent=2),
        validate_fn=lambda data: validate_skeptic_response(data, expected_anomaly_count=len(hypothesis["anomalies"])),
        max_tokens=3072,
        max_attempts=run_config.max_attempts,
        usage_sink=usage_sink,
    )


def run_checkpoint_loop(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    happy_day_example: dict,
    test_counter,
    on_checkpoint=None,
    usage_sink: list[dict] | None = None,
):
    """Returns (casting_log, checkpoints, stopped_reason).

    on_checkpoint(casting_log, checkpoints), if given, is called after every
    checkpoint completes - not just once at the end - so a crash partway
    through (a non-retryable API error, an unexpected bug) doesn't discard
    checkpoints that already finished. Each call is a full, self-consistent
    snapshot; the caller decides what to do with it (e.g. write it to disk).

    usage_sink, if given, is passed straight through to every Driver/Skeptic
    call this makes - see call_tool_with_retry.

    history_segments (below) is a growing LIST of per-checkpoint fragments, each
    rendered once by _render_history_fragment and never touched again, rather
    than either of the two things that came before it:

    - Re-serializing the whole growing casting_log fresh every call reshuffles
      JSON array/object closing punctuation every time it grows, so the text
      isn't even append-only and prefix matching breaks almost entirely.
    - Appending to a single growing *string* fixes that, but a cache entry can
      only end at a request content-block boundary, and one string is one block:
      the previous call's boundary lands mid-block this call, where no entry can
      end. A live loop measured this still landing ~0 cache_read on the evidence.

    Keeping the fragments separate means each one is its own content block, so
    the previous call's boundary is a real boundary this call too - which is what
    finally lets the cache credit the unchanged leading portion. See
    _cacheable_evidence_segments and call_tool_with_retry's cached_segments.
    """
    casting_log = []
    checkpoints = []
    prior_feedback = None
    stopped_reason = "checkpoints_exhausted"
    history_segments: list[str] = []

    for checkpoint_num in range(1, run_config.max_checkpoints + 1):
        is_first_checkpoint = checkpoint_num == 1
        test_budget = run_config.first_round_test_budget if is_first_checkpoint else run_config.default_test_budget
        print(f"Asking Claude for a casting round (checkpoint {checkpoint_num}, budget {test_budget})...")
        casting = get_casting_round(
            client,
            adapter,
            run_config,
            happy_day_example,
            history_segments,
            prior_feedback,
            test_budget=test_budget,
            is_first_round=is_first_checkpoint,
            usage_sink=usage_sink,
        )

        entries_before = len(casting_log)
        if casting["give_up"]:
            print(f"  Claude gave up casting: {casting['reasoning']}")
        else:
            print(f"  round reasoning: {casting['reasoning']}")
            for test in casting["candidate_tests"]:
                linked = test["linked_hypothesis"]
                label = f"hypothesis: {linked}" if linked else "edge case"
                test_number = next(test_counter)
                detail = adapter.describe_test_for_log(test) if adapter.describe_test_for_log else str(
                    {k: v for k, v in test.items() if k != "linked_hypothesis"}
                )
                print(f"  test #{test_number} ({label}): {detail}")

                result = adapter.execute_test(test, test_number)
                casting_log.append({
                    "checkpoint": checkpoint_num,
                    "round": 1,
                    "round_reasoning": casting["reasoning"],
                    "linked_hypothesis": linked,
                    "oracle_claim_id": test.get("oracle_claim_id", ""),
                    **result,
                })
                result_detail = adapter.describe_result_for_log(result) if adapter.describe_result_for_log else str(result.get("response", {}).get("body", {}))
                print(f"    actual: {result_detail} - prediction {'matched' if result['prediction_matched'] else 'MISSED'}")

        new_entries = _redact(adapter, casting_log[entries_before:])
        if new_entries:
            history_segments.append(_render_history_fragment(checkpoint_num, new_entries))

        prior_skeptic_review = prior_feedback["skeptic_review"] if prior_feedback else None

        print(f"Checkpoint {checkpoint_num}: forming a hypothesis...")
        hypothesis = get_checkpoint_hypothesis(
            client, adapter, run_config, happy_day_example, history_segments, prior_skeptic_review,
            usage_sink=usage_sink,
        )
        print(f"  observed_behavior: {hypothesis['observed_behavior']}")
        print(f"  anomalies noticed: {len(hypothesis['anomalies'])}")
        if hypothesis["prior_gaps_response"]:
            print(f"  prior gaps responded to: {len(hypothesis['prior_gaps_response'])}")

        print("Asking Skeptic for a cold review...")
        skeptic_review = get_skeptic_review(client, run_config, hypothesis, prior_skeptic_review, usage_sink=usage_sink)
        print(f"  skeptic verdict: {skeptic_review['verdict']}")

        checkpoints.append({"checkpoint": checkpoint_num, "hypothesis": hypothesis, "skeptic_review": skeptic_review})

        if on_checkpoint is not None:
            on_checkpoint(list(casting_log), list(checkpoints))
        if skeptic_review["verdict"] == "strong_enough":
            stopped_reason = "skeptic_satisfied"
            break

        prior_feedback = {"hypothesis": hypothesis, "skeptic_review": skeptic_review}

    return casting_log, checkpoints, stopped_reason


def get_bug_reports(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    final_hypothesis: dict,
    final_skeptic_review: dict,
    stopped_reason: str,
    casting_log: list[dict],
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    evidence = {
        "final_hypothesis": final_hypothesis,
        "final_skeptic_review": final_skeptic_review,
        "stopped_reason": stopped_reason,
        "all_tests_this_session": _redact(adapter, casting_log),
    }
    result = call_tool_with_retry(
        client,
        model=run_config.model,
        system=BUG_REPORT_SYSTEM_PROMPT,
        tools=[BUG_REPORT_TOOL],
        tool_name="submit_bug_reports",
        user_message=json.dumps(evidence, indent=2),
        validate_fn=validate_bug_reports,
        max_tokens=3072,
        max_attempts=run_config.max_attempts,
        # Measured as a no-op in practice: this call site's tools+system prefix
        # is below the model's minimum cacheable length, so the marker is
        # silently ignored (0 creation, 0 read), and it runs once per run anyway
        # while caching only breaks even at two requests. Left on so a retry, or
        # a future longer bug-report prompt, gets it for free.
        cache_static_content=True,
        usage_sink=usage_sink,
    )
    return result["bugs"]
