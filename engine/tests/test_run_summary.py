"""The Markdown summary of a run for a CI job's page (issue #255). No model calls."""

from engine.run_summary import count_retries, estimated_cost, summarize

_OUTPUT = {
    "stopped_reason": "checkpoints_exhausted",
    "casting_log": [{}, {}, {}],
    "checkpoints": [{}, {}],
    "observations": [
        {"id": "C2.O2", "kind": "finding", "status": "inconclusive", "severity": "low", "claim": "Next page | odd"},
        {"id": "C2.O1", "kind": "anomaly", "driver_kind": "bug", "status": "corroborated", "severity": "high",
         "replay": "not reproduced", "claim": "Profile answers 500"},
    ],
    "usage_summary": {"submit_casting_round": {"calls": 2, "input_tokens": 1_000_000, "output_tokens": 0,
                                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
}


def test_the_summary_lists_what_was_found_worst_first_with_replays():
    text = summarize(_OUTPUT, log_text="attempt 1 produced malformed output: x\n", bugs=None)
    assert "0 bug(s), 1 anomaly(ies), 1 finding(s) from 3 tests and 2 checkpoint(s)" in text
    assert text.index("C2.O1") < text.index("C2.O2")
    assert "| C2.O1 | anomaly (Driver said bug) | corroborated | high | not reproduced | Profile answers 500 |" in text
    assert "Next page \| odd" in text                          # a pipe in a claim doesn't break the table
    assert "2 model call(s), 1 retried. Estimated cost about $3.00" in text


def test_an_errored_run_says_so_first():
    text = summarize({"error": "no key", "stopped_reason": "error"})
    assert text.splitlines()[2] == "**The run stopped with an error:** no key"


def test_cost_and_retries_are_counted_from_usage_and_the_log():
    usage = {"a": {"input_tokens": 0, "output_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000,
                   "cache_read_input_tokens": 1_000_000}}
    assert round(estimated_cost(usage), 2) == 19.05
    assert count_retries("produced malformed output\nproduced no tool call\nfine") == 2
