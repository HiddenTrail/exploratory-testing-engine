"""Orchestrates one full run against an adapter: SUT readiness probe,
happy-day fetch, the checkpoint loop, bug-report writing, and result files.
No domain knowledge lives here - everything SUT-specific comes from the
adapter."""

import itertools
import json
import traceback

from engine.adapter import SUTAdapter, validate_adapter
from engine.client import build_client, summarize_usage
from engine.config import RunConfig
from engine.lean import PARTS as LEAN_PARTS
from engine.http import default_check_sut_ready
from engine.loop import get_bug_reports, get_happy_day_example, run_checkpoint_loop
from engine.tools import final_observations
from engine.report import render_report
from engine.verify import replay_bugs
from engine.budget import BudgetExceeded, start_run
from engine import interplay, steering


def _one_line(half: dict) -> str:
    """One half of the happy-day example, for the console only.

    `body` when there is one, because that is the interesting part of an HTTP
    request and printing the envelope around it buries it. A SUT whose halves
    have no `body` is not a broken adapter - see SUTAdapter's hooks - so this
    falls back to the whole half rather than raising on a shape it was not
    written for. Nothing but this print reads inside these two dicts.
    """
    return str(half.get("body", half)) if isinstance(half, dict) else str(half)


def cited_tests(output: dict) -> set[int]:
    """The tests a run's conclusions rest on (#286): the ones its observations cite, at
    every checkpoint and at the end (a bug report rests on its observation's), and the
    ones the debrief answers cite. Not the replays of bugs: the report shows those only
    as a verdict, so their videos would have nowhere to go."""
    cited = set()
    for checkpoint in output.get("checkpoints") or []:
        for o in (checkpoint.get("hypothesis") or {}).get("observations") or []:
            cited.update(o.get("tests") or [])
        for exchange in checkpoint.get("debrief") or []:
            cited.update((exchange.get("answer") or {}).get("tests") or [])
    for o in output.get("observations") or []:
        cited.update(o.get("tests") or [])
    return {n for n in cited if isinstance(n, int)}


def keep_test_media(adapter: SUTAdapter, output: dict, out_dir) -> None:
    """The adapter keeps the media of the cited tests (#286) and each test's entry gets
    its path. Media is an exhibit, so failing to keep it never fails the run."""
    try:
        kept = adapter.save_test_media(cited_tests(output), out_dir)
    except Exception as e:
        print(f"Couldn't keep the test videos ({type(e).__name__}: {e})")
        return
    for entry in output.get("casting_log") or []:
        if entry.get("test_number") in kept:
            entry["video"] = kept[entry["test_number"]]
    if kept:
        print(f"Kept the videos of {len(kept)} cited test(s), e.g. {out_dir / next(iter(kept.values()))}")


def lean_line(run_config: RunConfig) -> str:
    skipped = [p.replace("_", " ") for p in LEAN_PARTS if not run_config.wants(p)]
    kept = sorted(run_config.lean_with)
    return ("Lean run, for experiments: the model writes only what decides a finding"
            + (f"; skipped: {', '.join(skipped)}" if skipped else "")
            + (f"; switched back on: {', '.join(kept)}" if kept else "") + ".")


def run(adapter: SUTAdapter, run_config: RunConfig) -> dict:
    validate_adapter(adapter)
    # Before anything that could spend: a bad limit stops the run here, at no cost.
    limits = start_run()
    print(f"Spending limit: about ${limits.max_cost_usd:.2f} or {limits.max_calls} model calls, whichever comes first.")
    if run_config.lean:
        print(lean_line(run_config))
    client = build_client()

    (adapter.check_sut_ready or default_check_sut_ready)(adapter)

    happy_day_example = get_happy_day_example(adapter)
    if happy_day_example.get("request") or happy_day_example.get("response"):
        print("The happy-day example from the live SUT:")
        print(f"  {_one_line(happy_day_example['request'])} -> {_one_line(happy_day_example['response'])}")

    out_dir = run_config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.json"

    output = {
        "api_schema": adapter.api_schema_doc,
        "onboarding_extra": adapter.onboarding_extra,
        "happy_day_example": happy_day_example,
    }
    if run_config.lean:
        # So a lean run is only ever compared with lean runs (#295).
        output["lean"] = {"with": sorted(run_config.lean_with)}
    bug_reports = []
    test_counter = itertools.count(1)
    usage_log: list[dict] = []
    # The same list object, so every write below - including save_progress's
    # partial ones - serializes whatever has accumulated by then. The per-call
    # records are kept alongside the aggregate on purpose: a summary showing
    # cache_read=0 can't say WHICH calls missed or how far apart they were, so
    # diagnosing a caching regression from one real run needs the raw rows.
    output["usage_log"] = usage_log

    def save_progress(casting_log, checkpoints):
        # Called after every checkpoint, not just once at the end - a crash
        # partway through (a non-retryable API error, an unexpected bug)
        # shouldn't discard checkpoints that already finished and cost real
        # API calls to produce.
        output["casting_log"] = casting_log
        output["checkpoints"] = checkpoints
        output["usage_summary"] = summarize_usage(usage_log)
        output["stopped_reason"] = "in_progress"
        tmp_path = out_path.with_name(out_path.name + ".tmp")
        tmp_path.write_text(json.dumps(output, indent=2))
        tmp_path.replace(out_path)

    try:
        casting_log, checkpoints, stopped_reason = run_checkpoint_loop(
            client, adapter, run_config, happy_day_example, test_counter,
            on_checkpoint=save_progress, usage_sink=usage_log,
        )
        output["casting_log"] = casting_log
        output["checkpoints"] = checkpoints
        output["stopped_reason"] = stopped_reason

        final_hypothesis = checkpoints[-1]["hypothesis"]
        final_skeptic_review = checkpoints[-1]["skeptic_review"]
        observations = final_observations(final_hypothesis, final_skeptic_review)
        # A parked claim stays in the conclusion even if the Driver stopped repeating it (#305).
        observations = steering.keep_parked(observations, checkpoints, steering.parked_claims(checkpoints))
        # Every bug's tests run again before anything is written up (#177). One that
        # doesn't reproduce is lowered to an anomaly here, so it never gets a bug report.
        output["replays"], output["replay_log"] = replay_bugs(adapter, observations, casting_log, test_counter)
        for record in output["replays"]:
            print(f"  replayed {record['observation_id']}: {record['verdict']}"
                  + (f" ({record['detail']})" if record.get("detail") else ""))
        output["observations"] = observations
        # Findings alone don't count: an anomaly_found run has a real problem in it.
        output["anomaly_found"] = any(o["kind"] in ("anomaly", "bug") for o in observations)
        for o in observations:
            print(f"  {o['id']} {o['kind']} ({o['status']}): {o['claim']}")

        # Only bugs get a written report. Findings and anomalies are already complete
        # in output["observations"], so they need no LLM call.
        bugs = [o for o in observations if o["kind"] == "bug"]
        if bugs and not run_config.wants("bug_reports"):
            print(f"Lean run: no bug reports written for {len(bugs)} bug(s). Ask for them afterwards with "
                  f"python -m engine.ask {out_dir} --adapter {adapter.name} --bug-reports")
        elif bugs:
            plural = "" if len(bugs) == 1 else "s"
            print(f"Writing bug report{plural} for {len(bugs)} bug{plural}...")
            # Isolated from the run's verdict: the checkpoint loop has already concluded
            # (stopped_reason / anomaly_found are set above), so a bug-report generation
            # failure - e.g. the tool call exhausting its retries on a max_tokens cutoff -
            # must degrade to "no bug reports written", not rewrite a successful run as
            # "error" and discard its conclusion.
            try:
                bug_reports = get_bug_reports(
                    client, adapter, run_config, bugs, final_skeptic_review, stopped_reason, casting_log,
                    usage_sink=usage_log,
                )
            except Exception as e:
                print(f"  bug-report generation failed ({type(e).__name__}: {e}); "
                      f"keeping the run verdict, writing no bug reports.")
                output["bug_report_error"] = str(e)
    except BudgetExceeded as e:
        # Everything finished so far is kept; the run just can't spend any more.
        print(e)
        output["error"] = str(e)
        output["stopped_reason"] = "budget_exceeded"
    except RuntimeError as e:
        print(f"Stopped early: {e}")
        output["error"] = str(e)
        output["stopped_reason"] = "error"
    except Exception as e:
        # Anything else (a non-retryable API error like a bad key, a genuine
        # bug) - keep whatever checkpoints save_progress already wrote rather
        # than losing them, but print the full traceback since this path is
        # unexpected and worth being able to actually debug.
        print(f"Stopped early due to an unexpected error: {e!r}")
        traceback.print_exc()
        output["error"] = str(e)
        output["stopped_reason"] = "error"

    output["usage_summary"] = summarize_usage(usage_log)
    # Found X of Y known problems (#277), when the target has a list.
    if adapter.score_run is not None and output.get("observations") is not None:
        score = adapter.score_run(output)
        if score:
            output["score"] = score
            print(f"Known problems found: {len(score['found'])} of {score['known']}")
    if adapter.save_test_media is not None:
        keep_test_media(adapter, output, out_dir)
    # How the Driver answered the Skeptic (#257), from whatever checkpoints finished.
    output["interplay"] = interplay.measure(output.get("checkpoints") or [])
    if output["usage_summary"]:
        print("\nToken usage by call type:")
        for call, agg in output["usage_summary"].items():
            print(
                f"  {call}: {agg['calls']} call(s), input={agg['input_tokens']}, "
                f"cache_read={agg['cache_read_input_tokens']}, cache_creation={agg['cache_creation_input_tokens']}, "
                f"output={agg['output_tokens']}"
            )

    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nWrote result to {out_path}")

    if bug_reports:
        bugs_path = out_dir / "bugs.json"
        bugs_path.write_text(json.dumps(bug_reports, indent=2))
        print(f"Wrote {len(bug_reports)} bug report(s) to {bugs_path}")

    report_path = out_dir / "report.html"
    report_path.write_text(render_report(output, bug_reports, adapter), encoding="utf-8")
    print(f"Wrote report to {report_path}")

    if "error" not in output:
        if output.get("anomaly_found"):
            print("Now score it by hand against rubric.md.")
        else:
            print("No anomaly or bug found. See checkpoints for the final hypothesis and the Skeptic's review of it.")

    return output
