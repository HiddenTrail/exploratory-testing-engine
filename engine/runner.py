"""Orchestrates one full run against an adapter: SUT readiness probe,
happy-day fetch, the checkpoint loop, bug-report writing, and result files.
No domain knowledge lives here - everything SUT-specific comes from the
adapter."""

import itertools
import json
import traceback

import httpx

from engine.adapter import SUTAdapter, validate_adapter
from engine.client import build_client, summarize_usage
from engine.config import RunConfig
from engine.loop import get_bug_reports, get_happy_day_example, run_checkpoint_loop
from engine.report import render_report


def run(adapter: SUTAdapter, run_config: RunConfig) -> dict:
    validate_adapter(adapter)
    client = build_client()

    docs_url = adapter.base_url + adapter.docs_path
    try:
        httpx.get(docs_url, timeout=adapter.sut_ready_timeout)
    except httpx.TransportError:
        raise SystemExit(f"{adapter.name}'s SUT isn't running at {adapter.base_url} - start it first.")

    print("Fetching the one happy-day example from the live SUT...")
    happy_day_example = get_happy_day_example(adapter)
    print(f"  {happy_day_example['request']['body']} -> {happy_day_example['response']['body']}")

    out_dir = run_config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.json"

    output = {
        "api_schema": adapter.api_schema_doc,
        "onboarding_extra": adapter.onboarding_extra,
        "happy_day_example": happy_day_example,
    }
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
        anomalies = final_hypothesis.get("anomalies", [])
        output["anomaly_found"] = len(anomalies) > 0

        if anomalies:
            plural = "y" if len(anomalies) == 1 else "ies"
            print(f"Writing bug report(s) for {len(anomalies)} anomal{plural}...")
            bug_reports = get_bug_reports(
                client, adapter, run_config, final_hypothesis, final_skeptic_review, stopped_reason, casting_log,
                usage_sink=usage_log,
            )
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
            print("No anomaly found. See checkpoints for the final hypothesis and Skeptic's critique of it.")

    return output
