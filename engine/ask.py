"""Ask a finished run for something it didn't write (issue #295).

A lean run skips the testing story, the debrief and the bug report write-ups. When we
read one and want a part after all, this makes the call for it on the saved run:

    python -m engine.ask runs/<run> --adapter web_gui --story [N]
    python -m engine.ask runs/<run> --adapter web_gui --bug-reports
    python -m engine.ask runs/<run> --adapter web_gui --question "Why was C3.O1 doubted?"

The model gets the same record the run had (the saved schema, onboarding and test
history), so it answers from what happened, not from the live system. Each answer
goes into <run>/asked/, next to the run's files; output.json is never changed. One
call each, at the run's usual spending limit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine import budget
from engine.adapter import SUTAdapter
from engine.adapters.registry import available_adapters, load_adapter
from engine.client import build_client, call_tool_with_retry, summarize_usage
from engine.config import RunConfig
from engine.loop import _cacheable_evidence_segments, _redact, _render_history_fragment, get_bug_reports, get_testing_story
from engine.run_summary import estimated_cost
from engine.tools import ASK_SYSTEM_PROMPT, ASK_TOOL, validate_answer


def saved_adapter(adapter: SUTAdapter, output: dict) -> SUTAdapter:
    """The adapter as the run saw it: its schema and onboarding come from output.json,
    because a web adapter only fills them in from a live session."""
    return replace(adapter, api_schema_doc=output.get("api_schema", ""),
                   onboarding_extra=output.get("onboarding_extra") or {})


def history_segments(adapter: SUTAdapter, casting_log: list[dict], up_to: int | None = None) -> list[str]:
    """The test history as the run's model calls saw it, one segment per checkpoint."""
    by_checkpoint: dict[int, list[dict]] = {}
    for entry in casting_log:
        if up_to is None or entry.get("checkpoint", 0) <= up_to:
            by_checkpoint.setdefault(entry.get("checkpoint", 0), []).append(entry)
    return [_render_history_fragment(n, _redact(adapter, entries)) for n, entries in sorted(by_checkpoint.items())]


def ask_question(client, adapter: SUTAdapter, run_config: RunConfig, output: dict, question: str,
                 usage_sink: list[dict]) -> dict:
    record = [{key: c.get(key) for key in ("checkpoint", "hypothesis", "skeptic_review", "debrief")}
              for c in output.get("checkpoints", [])]
    answer = call_tool_with_retry(
        client, model=run_config.model, system=ASK_SYSTEM_PROMPT, tools=[ASK_TOOL], tool_name="submit_answer",
        cached_segments=_cacheable_evidence_segments(adapter, output.get("happy_day_example") or {},
                                                     "ALL TESTS THIS SESSION",
                                                     history_segments(adapter, output.get("casting_log", []))),
        user_message=json.dumps({"question": question, "run": record}, indent=2),
        validate_fn=validate_answer, max_tokens=1024, max_attempts=run_config.max_attempts, usage_sink=usage_sink,
    )
    return {"question": question, **answer}


def ask_story(client, adapter: SUTAdapter, run_config: RunConfig, output: dict, checkpoint: int | None,
              usage_sink: list[dict]) -> dict:
    checkpoints = output.get("checkpoints") or []
    if not checkpoints:
        raise SystemExit("This run has no finished checkpoint to tell the story of.")
    entry = next((c for c in checkpoints if c["checkpoint"] == checkpoint), None) if checkpoint else checkpoints[-1]
    if entry is None:
        raise SystemExit(f"This run has no checkpoint {checkpoint}.")
    story = get_testing_story(client, adapter, run_config, output.get("happy_day_example") or {},
                              history_segments(adapter, output.get("casting_log", []), up_to=entry["checkpoint"]),
                              entry["hypothesis"], usage_sink=usage_sink)
    return {"checkpoint": entry["checkpoint"], **story}


def ask_bug_reports(client, adapter: SUTAdapter, run_config: RunConfig, output: dict,
                    usage_sink: list[dict]) -> list[dict]:
    bugs = [o for o in output.get("observations") or [] if o.get("kind") == "bug"]
    if not bugs:
        raise SystemExit("This run concluded no bugs, so there's nothing to write up.")
    return get_bug_reports(client, adapter, run_config, bugs, output["checkpoints"][-1]["skeptic_review"],
                           output.get("stopped_reason", ""), output.get("casting_log", []), usage_sink=usage_sink)


def save(run_dir: Path, name: str, data) -> Path:
    asked = run_dir / "asked"
    asked.mkdir(exist_ok=True)
    path = asked / f"{name}.json"
    n = 2
    while path.exists():     # never overwrite an earlier answer
        path, n = asked / f"{name}-{n}.json", n + 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "question"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Ask a finished run for a part it didn't write (issue #295).")
    parser.add_argument("run_dir", type=Path, help="The run's folder, with its output.json.")
    parser.add_argument("--adapter", required=True, choices=available_adapters())
    parser.add_argument("--model", default=None, help="Override the model (default: engine default).")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--story", nargs="?", const=0, type=int, metavar="CHECKPOINT",
                      help="The testing story of a checkpoint (default: the last one).")
    what.add_argument("--bug-reports", action="store_true", help="Write up the run's bugs.")
    what.add_argument("--question", help="One question about the run, answered from its record.")
    args = parser.parse_args(argv)

    output_path = args.run_dir / "output.json"
    if not output_path.exists():
        raise SystemExit(f"{output_path} doesn't exist.")
    output = json.loads(output_path.read_text(encoding="utf-8"))
    adapter = saved_adapter(load_adapter(args.adapter), output)
    run_config = RunConfig.for_adapter(adapter, model=args.model, out_dir=args.run_dir)
    budget.start_run()
    client = build_client()
    usage: list[dict] = []

    if args.question:
        path = save(args.run_dir, _slug(args.question), ask_question(client, adapter, run_config, output,
                                                                     args.question, usage))
    elif args.bug_reports:
        path = save(args.run_dir, "bug-reports", ask_bug_reports(client, adapter, run_config, output, usage))
    else:
        story = ask_story(client, adapter, run_config, output, args.story or None, usage)
        path = save(args.run_dir, f"story-C{story['checkpoint']}", story)
    print(path.read_text(encoding="utf-8"))
    print(f"\nWrote {path}. Estimated cost about ${estimated_cost(summarize_usage(usage)):.2f}.")


if __name__ == "__main__":
    main()
