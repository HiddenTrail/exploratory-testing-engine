"""The generic Driver+Skeptic checkpoint loop: propose and execute a batch of
tests, form one hypothesis about behavior and anything that looks wrong, get a
cold Skeptic review, and either continue (Skeptic says "weak") or conclude
(Skeptic says "strong_enough" or the checkpoint cap is reached). Ported
almost verbatim from token-purchase-poc/run_live.py's unified checkpoint
loop - every module-global constant becomes a run_config/adapter read, and
every domain-specific call (test proposal schema, execute_test, prediction
matching) becomes an adapter read.
"""

import json

from anthropic import Anthropic

from engine import coverage, diagnostics
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
    TESTING_STORY_SYSTEM_PROMPT,
    TESTING_STORY_TOOL,
    DEBRIEF_ANSWER_SYSTEM_PROMPT,
    DEBRIEF_ANSWER_TOOL,
    RECONSIDER_SYSTEM_PROMPT,
    RECONSIDER_TOOL,
    merge_debrief,
    open_part,
    validate_debrief_answers,
    validate_reconsideration,
    lower_unsupported_bugs,
    reconcile_kinds,
    stamp_gap_ids,
    stamp_observation_ids,
    validate_bug_reports,
    validate_hypothesis_response,
    validate_skeptic_response,
    validate_testing_story,
)


def _redact(adapter: SUTAdapter, casting_log: list[dict]) -> list[dict]:
    redact_fn = adapter.redact_history_for_model or default_redact_history_for_model
    return redact_fn(casting_log)


def _base_evidence(adapter: SUTAdapter, happy_day_example: dict, skeptic_history: dict | None = None) -> dict:
    evidence = {
        "api_schema": adapter.api_schema_doc,
        **adapter.onboarding_extra,
        "happy_day_example": happy_day_example,
    }
    # The Driver learns from earlier runs' objections (#258). Never from the current
    # run's Skeptic beyond the review it's already given, so the Skeptic stays cold.
    if skeptic_history:
        evidence["skeptic_history"] = skeptic_history
    return evidence


def _render_history_fragment(checkpoint_num: int, entries: list[dict]) -> str:
    """One checkpoint's worth of redacted test entries, as a fragment meant to
    be *appended* to a running list of fragments and never regenerated - see
    the docstring-level note in run_checkpoint_loop for why that matters for
    prompt caching. sort_keys pins the serialization so a fragment can't come
    out byte-different for content that didn't change."""
    return f"\n\n--- checkpoint {checkpoint_num} ---\n{json.dumps(entries, indent=2, sort_keys=True)}"


def _cacheable_evidence_segments(
    adapter: SUTAdapter, happy_day_example: dict, section_title: str, history_segments: list[str],
    skeptic_history: dict | None = None,
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
        json.dumps(_base_evidence(adapter, happy_day_example, skeptic_history), indent=2, sort_keys=True)
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
    run_diagnostics: dict | None = None,
) -> dict:
    # Known and unavoidable: the casting system prompt varies with test_budget
    # and is_first_round, and system renders BEFORE the messages, so checkpoint 2
    # can't read checkpoint 1's cache however stable the evidence blocks are.
    # Rounds 2..N share a prompt and do hit - measured 0 read at checkpoint 2,
    # then ~14k at checkpoint 3 - so it costs one extra write per run, not one
    # per checkpoint. Not worth flattening the prompt over.
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "TESTS TRIED IN EARLIER ROUNDS", history_segments,
        skeptic_history=run_config.skeptic_history,
    )
    fresh_evidence = {}
    if prior_checkpoint_feedback is not None:
        fresh_evidence["prior_checkpoint_feedback"] = prior_checkpoint_feedback
    if run_diagnostics:
        fresh_evidence["run_diagnostics"] = run_diagnostics
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
    run_diagnostics: dict | None = None,
    earlier_observations: list[dict] | None = None,
) -> dict:
    """earlier_observations: every earlier checkpoint's observations, shown to the
    Driver as id, kind and claim so a new observation can 'continues' one of them
    instead of restating it under a new id. They are the only ids 'continues' may
    name."""
    earlier_observations = earlier_observations or []
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "ALL TESTS THIS SESSION", history_segments,
        skeptic_history=run_config.skeptic_history,
    )
    open_gap_ids = tuple(gap["id"] for gap in prior_skeptic_review["gaps"]) if prior_skeptic_review else ()
    # Both of these go in the FRESH message, not the cached segments: they change
    # every checkpoint, and one changing block at the end of a cached prefix costs
    # nothing, while a changing block inside it would invalidate everything after
    # it. See _cacheable_evidence_segments.
    fresh_evidence = {}
    if earlier_observations:
        fresh_evidence["earlier_observations"] = [
            {key: o[key] for key in ("id", "kind", "claim")} for o in earlier_observations
        ]
    if prior_skeptic_review is not None:
        fresh_evidence["prior_skeptic_review"] = prior_skeptic_review
    if run_diagnostics:
        fresh_evidence["run_diagnostics"] = run_diagnostics
    known_observation_ids = tuple(o["id"] for o in earlier_observations)
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=HYPOTHESIS_SYSTEM_PROMPT,
        tools=[HYPOTHESIS_TOOL],
        tool_name="submit_checkpoint_hypothesis",
        cached_segments=cached_segments,
        user_message=json.dumps(fresh_evidence, indent=2),
        validate_fn=lambda data: validate_hypothesis_response(
            data, known_observation_ids=known_observation_ids, open_gap_ids=open_gap_ids,
        ),
        # Room to spare: when the hypothesis carried the testing story (#265), answers ran
        # 2,000 to 2,560 tokens and were cut off at the old 2,560. The limit costs nothing
        # until it's hit.
        max_tokens=4096,
        max_attempts=run_config.max_attempts,
        cache_static_content=True,
        usage_sink=usage_sink,
    )


def get_testing_story(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    happy_day_example: dict,
    history_segments: list[str],
    hypothesis: dict,
    usage_sink: list[dict] | None = None,
) -> dict:
    """The testing story behind the hypothesis just formed (#265, #271): areas and
    obstacles. Its own call, because inside the hypothesis the answer grew big enough to
    break too often: fields lost, or written in another tool-call format. It shares the
    hypothesis call's cached test history, so it costs little more than its own answer."""
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "ALL TESTS THIS SESSION", history_segments,
        skeptic_history=run_config.skeptic_history,
    )
    fresh_evidence = {"your_hypothesis": {key: hypothesis[key] for key in ("summary", "behaviors", "observations",
                                                                          "untested") if key in hypothesis}}
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=TESTING_STORY_SYSTEM_PROMPT,
        tools=[TESTING_STORY_TOOL],
        tool_name="submit_testing_story",
        cached_segments=cached_segments,
        user_message=json.dumps(fresh_evidence, indent=2),
        validate_fn=validate_testing_story,
        # 2,048 cut a five-area story off once in #266's benchmark.
        max_tokens=3072,
        max_attempts=run_config.max_attempts,
        cache_static_content=True,
        usage_sink=usage_sink,
    )


def get_debrief_answers(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    happy_day_example: dict,
    history_segments: list[str],
    hypothesis: dict,
    questions: list[dict],
    usage_sink: list[dict] | None = None,
) -> dict:
    """The Driver answers the Skeptic's questions (#266), with its whole test history in
    view through the same cached evidence as the hypothesis."""
    cached_segments = _cacheable_evidence_segments(
        adapter, happy_day_example, "ALL TESTS THIS SESSION", history_segments,
        skeptic_history=run_config.skeptic_history,
    )
    fresh = {"your_hypothesis": {k: hypothesis[k] for k in ("summary", "observations", "areas") if k in hypothesis},
             "skeptic_questions": [{k: g[k] for k in ("id", "kind", "gap", "next_test", "blocks_verdict", "about") if k in g}
                                   for g in questions]}
    gap_ids = tuple(g["id"] for g in questions)
    return call_tool_with_retry(
        client, model=run_config.model, system=DEBRIEF_ANSWER_SYSTEM_PROMPT, tools=[DEBRIEF_ANSWER_TOOL],
        tool_name="submit_debrief_answers", cached_segments=cached_segments, user_message=json.dumps(fresh, indent=2),
        validate_fn=lambda data: validate_debrief_answers(data, gap_ids=gap_ids),
        max_tokens=2048, max_attempts=run_config.max_attempts, cache_static_content=True, usage_sink=usage_sink,
    )


def cited_evidence(adapter: SUTAdapter, casting_log: list[dict], answers: dict) -> dict:
    """What the tests the Driver cites actually recorded, as the Driver itself saw them
    (the adapter's redacted view), keyed by test number. The Skeptic judges answers
    against this, not against the Driver's description of it."""
    cited = {n for a in answers.get("answers", []) for n in a.get("tests", [])}
    entries = [e for e in casting_log if e.get("test_number") in cited]
    return {e["test_number"]: e for e in _redact(adapter, entries)}


def get_reconsideration(
    client: Anthropic, run_config: RunConfig, review: dict, questions: list[dict], answers: dict,
    evidence: dict, hypothesis: dict, usage_sink: list[dict] | None = None,
) -> dict:
    """The Skeptic judges the Driver's answers against the evidence the engine attached
    (#266). It sees its own review, the answers with their evidence, and nothing of the
    Driver's reasoning beyond the answers."""
    by_id = {a["gap_id"]: a for a in answers.get("answers", [])}
    payload = {
        "your_review": {k: review[k] for k in ("verdict", "verdict_reason", "observation_checks") if k in review},
        "answers": [{"question": {k: g[k] for k in ("id", "kind", "gap", "blocks_verdict", "about") if k in g},
                     "answer": by_id.get(g["id"]),
                     "evidence": {str(n): evidence.get(n) for n in (by_id.get(g["id"]) or {}).get("tests", [])}}
                    for g in questions],
        "observations": [{k: o[k] for k in ("id", "kind", "claim", "rival") if k in o}
                         for o in hypothesis.get("observations", [])],
    }
    gap_ids = tuple(g["id"] for g in questions)
    blocking = tuple(g["id"] for g in questions if g.get("blocks_verdict"))
    observation_ids = tuple(o["id"] for o in hypothesis.get("observations", []))
    failing = tuple(c["observation_id"] for c in review.get("observation_checks", [])
                    if c.get("discriminates_from_rival") is False)
    defended = tuple(a["gap_id"] for a in answers.get("answers", []) if a.get("stance") == "defend")
    return call_tool_with_retry(
        client, model=run_config.model, system=RECONSIDER_SYSTEM_PROMPT, tools=[RECONSIDER_TOOL],
        tool_name="submit_reconsideration", user_message=json.dumps(payload, indent=2),
        validate_fn=lambda data: validate_reconsideration(data, gap_ids=gap_ids, blocking_ids=blocking,
                                                          observation_ids=observation_ids, failing_checks=failing,
                                                          defended_ids=defended),
        max_tokens=2048, max_attempts=run_config.max_attempts, cache_static_content=True, usage_sink=usage_sink,
    )


def get_skeptic_review(
    client: Anthropic, run_config: RunConfig, hypothesis: dict, prior_skeptic_review: dict | None = None,
    usage_sink: list[dict] | None = None, test_coverage: dict | None = None, previous_story: list | None = None,
) -> dict:
    # The testing story is part of what the Skeptic reviews (#265). It was left off this
    # list once, so the Skeptic was told to question a story it never received (#271).
    evidence = {key: hypothesis[key] for key in
                ("summary", "behaviors", "observations", "areas", "obstacles", "untested", "prior_gaps")
                if key in hypothesis}
    # The previous checkpoint's story, so the Skeptic can see whether anything moved.
    if previous_story:
        evidence["previous_story"] = previous_story
    if test_coverage is not None:
        evidence["test_coverage"] = test_coverage
    if prior_skeptic_review is not None:
        evidence["your_own_prior_review"] = prior_skeptic_review
    open_gap_ids = tuple(gap["id"] for gap in prior_skeptic_review["gaps"]) if prior_skeptic_review else ()
    return call_tool_with_retry(
        client,
        model=run_config.model,
        system=SKEPTIC_SYSTEM_PROMPT,
        tools=[SKEPTIC_TOOL],
        tool_name="submit_skeptic_review",
        user_message=json.dumps(evidence, indent=2),
        validate_fn=lambda data: validate_skeptic_response(
            data, observations=hypothesis["observations"], open_gap_ids=open_gap_ids,
        ),
        max_tokens=3072,
        max_attempts=run_config.max_attempts,
        # The system prompt and tool schema are the same on every checkpoint, and
        # Skeptic calls in a run are about 90 to 130 seconds apart, inside the
        # cache's 5-minute window. So every Skeptic call after the first reads them
        # from the cache. The evidence changes every call and stays uncached.
        cache_static_content=True,
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

    After every batch, engine/diagnostics.py runs over the whole log so far and its
    findings go three places: printed, into the hypothesis and next casting calls as
    evidence, and onto the checkpoint record for the report. A `stop` finding ends
    the run with `stopped_reason` = `diagnostics_<code>` - the loop's only exit that
    is neither the Skeptic nor the checkpoint cap, and it exists because a run that
    has lost the ability to return to its own baseline is spending budget on tests
    whose results cannot be attributed to the action that was sent.

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
    run_diagnostics = None
    stopped_reason = "checkpoints_exhausted"
    history_segments: list[str] = []
    # Every observation so far, in order: what a later 'continues' may point at.
    earlier_observations: list[dict] = []
    # Every test that ran, as the Driver cast it: what engine/coverage.py summarises.
    tests_run: list[dict] = []

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
            run_diagnostics=run_diagnostics,
        )

        entries_before = len(casting_log)
        if casting.get("give_up", False):
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
                    # The test exactly as cast, so engine/verify.py can run it again (#177).
                    "cast_test": test,
                    **result,
                })
                result_detail = adapter.describe_result_for_log(result) if adapter.describe_result_for_log else str(result.get("response", {}).get("body", {}))
                # A skipped test never ran, so there's no prediction to check. Not
                # every adapter sets prediction_matched on a skip, so don't read it.
                if result.get("skipped"):
                    print(f"    actual: {result_detail} - not run")
                else:
                    tests_run.append(test)
                    print(f"    actual: {result_detail} - prediction {'matched' if result.get('prediction_matched') else 'MISSED'}")

        new_entries = _redact(adapter, casting_log[entries_before:])
        if new_entries:
            history_segments.append(_render_history_fragment(checkpoint_num, new_entries))

        # Without the questions the debrief settled or the Driver conceded (#266).
        prior_skeptic_review = open_part(prior_feedback["skeptic_review"]) if prior_feedback else None

        # Run diagnostics over the whole log so far, not just this checkpoint's
        # entries: a collapsed action space and a broken reset both take more than
        # one batch to become visible, and re-deriving from the full log each time
        # is cheap (pure arithmetic, no calls). See engine/diagnostics.py.
        findings = diagnostics.diagnose(casting_log)
        if findings:
            print(f"  run diagnostics ({len(findings)}):")
            for line in diagnostics.console_lines(findings):
                print(line)

        print(f"Checkpoint {checkpoint_num}: forming a hypothesis...")
        hypothesis = get_checkpoint_hypothesis(
            client, adapter, run_config, happy_day_example, history_segments, prior_skeptic_review,
            usage_sink=usage_sink, run_diagnostics=diagnostics.for_model(findings),
            earlier_observations=list(earlier_observations),
        )
        # The testing story is asked for on its own (#271) and becomes part of the
        # hypothesis, so everything after this (Skeptic, report, summary) reads it there.
        print("  telling the testing story...")
        hypothesis.update(get_testing_story(
            client, adapter, run_config, happy_day_example, history_segments, hypothesis, usage_sink=usage_sink,
        ))
        print("  story: " + "; ".join(
            f"{a['area']}: {a['coverage'].replace('_', ' ')}, {a['quality'].replace('_', ' ')}" for a in hypothesis["areas"]))
        # Ids go on before the Skeptic sees the hypothesis, so its review can name them.
        lower_unsupported_bugs(hypothesis)
        stamp_observation_ids(checkpoint_num, hypothesis)
        earlier_observations.extend(hypothesis["observations"])
        print(f"  summary: {hypothesis['summary']}")
        for o in hypothesis["observations"]:
            print(f"  {o['id']} {o['kind']}: {o['claim']}")
        if hypothesis["prior_gaps"]:
            print(f"  prior gaps answered: {len(hypothesis['prior_gaps'])}")

        test_coverage = coverage.summarize(adapter.casting_tool_schema, tests_run)
        print("Asking Skeptic for a cold review...")
        skeptic_review = get_skeptic_review(
            client, run_config, hypothesis, prior_skeptic_review, usage_sink=usage_sink, test_coverage=test_coverage,
            previous_story=checkpoints[-1]["hypothesis"].get("areas") if checkpoints else None,
        )
        stamp_gap_ids(checkpoint_num, skeptic_review)
        reconcile_kinds(hypothesis, skeptic_review)
        print(f"  skeptic verdict: {skeptic_review['verdict']} - {skeptic_review['verdict_reason']}")

        # The debrief (#266): the Driver answers the Skeptic's questions with argument and
        # evidence, and the Skeptic reconsiders, before the next round of tests.
        debrief = []
        questions = skeptic_review["gaps"]
        if skeptic_review["verdict"] == "weak" and questions:
            print(f"  debrief: the Driver answers {len(questions)} question(s)...")
            answers = get_debrief_answers(client, adapter, run_config, happy_day_example, history_segments,
                                          hypothesis, questions, usage_sink=usage_sink)
            evidence = cited_evidence(adapter, casting_log, answers)
            reconsideration = get_reconsideration(client, run_config, skeptic_review, questions, answers, evidence,
                                                  hypothesis, usage_sink=usage_sink)
            debrief = merge_debrief(skeptic_review, questions, answers, reconsideration, evidence)
            print("  debrief: " + ", ".join(f"{d['gap_id']} {d['outcome']}" for d in debrief)
                  + f"; verdict now {skeptic_review['verdict']}")
        for o in hypothesis["observations"]:
            if "driver_kind" in o:
                print(f"  {o['id']} lowered from {o['driver_kind']} to {o['kind']}: {o['lowered_because']}")

        checkpoints.append({
            "checkpoint": checkpoint_num,
            "hypothesis": hypothesis,
            "skeptic_review": skeptic_review,
            "test_coverage": test_coverage,
            "diagnostics": diagnostics.as_dicts(findings),
            "debrief": debrief,
        })

        if on_checkpoint is not None:
            on_checkpoint(list(casting_log), list(checkpoints))
        if skeptic_review["verdict"] == "strong_enough":
            stopped_reason = "skeptic_satisfied"
            break

        # A `stop` finding ends the run, but only AFTER the checkpoint completed:
        # the batch that produced it was already executed and paid for, and its
        # hypothesis and review are the best account of what went wrong. Stopping
        # mid-checkpoint would throw that away to save nothing. What it does save
        # is every checkpoint after this one, which would spend budget sampling the
        # SUT from a state nobody chose.
        blocker = diagnostics.should_stop(findings)
        if blocker is not None:
            print(f"  STOPPING: {blocker.headline}")
            print(f"    {blocker.detail}")
            stopped_reason = f"diagnostics_{blocker.code}"
            break

        prior_feedback = {"hypothesis": hypothesis, "skeptic_review": skeptic_review}
        # A separate key rather than nested inside prior_checkpoint_feedback, whose
        # contents every adapter's casting prompt describes through the shared
        # PRIOR_FEEDBACK_GUIDE (engine/tools.py) as the previous checkpoint's
        # hypothesis and Skeptic review. Slipping a third thing in there would make
        # that description quietly inaccurate in four prompts at once.
        run_diagnostics = diagnostics.for_model(findings)

    return casting_log, checkpoints, stopped_reason


def get_bug_reports(
    client: Anthropic,
    adapter: SUTAdapter,
    run_config: RunConfig,
    bugs: list[dict],
    final_skeptic_review: dict,
    stopped_reason: str,
    casting_log: list[dict],
    usage_sink: list[dict] | None = None,
) -> list[dict]:
    """bugs: the final observations of kind 'bug', with the status the engine
    gave them (see final_observations). The model writes the report text; the
    id, kind, severity and status come from the observation, not from the model."""
    bug_ids = tuple(b["id"] for b in bugs)
    evidence = {
        "bugs": bugs,
        "blocking_gaps": [
            g for g in final_skeptic_review["gaps"] if g["blocks_verdict"] and set(g["about"]) & set(bug_ids)
        ],
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
        validate_fn=lambda data: validate_bug_reports(data, bug_ids=bug_ids),
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
    by_id = {b["id"]: b for b in bugs}
    return [
        {**report, **{key: by_id[report["observation_id"]][key] for key in ("kind", "severity", "status")}}
        for report in result["bugs"]
    ]
