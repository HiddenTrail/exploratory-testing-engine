"""engine/verify.py: a bug's tests run again before it's reported (issue #177), and a bug
whose tests don't come out the same is lowered to an anomaly. No model calls."""

import itertools
import json

import httpx
import pytest

import engine.loop as loop
import engine.runner as runner
from engine.adapter import SUTAdapter
from engine.config import RunConfig
from engine.redact import default_redact_history_for_model
from engine.verify import NOT_AVAILABLE, NOT_REPRODUCED, REPRODUCED, UNVERIFIABLE, replay_bugs


def _adapter(results, compare=True, before_replay=None):
    """An adapter whose execute_test answers from `results`, one per call, and whose
    comparison calls two results the same when their 'value' is."""
    answers = iter(results)
    return SUTAdapter(
        name="fake_verify", display_name="Fake", base_url="http://example.invalid", test_endpoint_path="/x",
        casting_tool_schema={}, casting_system_prompt=lambda b, f: "", validate_casting_response=lambda d: [],
        execute_test=lambda test, n: {"test_number": n, "value": next(answers)},
        render_test_entry=lambda e: "", render_onboarding_section=lambda *a: "",
        compare_replay=(lambda original, replayed: {"same": original["value"] == replayed["value"],
                                                    "detail": f"got {replayed['value']}"}) if compare else None,
        before_replay=before_replay,
    )


def _bug(tests, oid="C2.O1"):
    return {"id": oid, "kind": "bug", "tests": tests, "claim": "c", "severity": "high", "status": "corroborated"}


def _log(*values):
    return [{"test_number": n, "cast_test": {"n": n}, "value": v} for n, v in enumerate(values, start=1)]


def test_a_bug_whose_tests_come_out_the_same_stays_a_bug():
    bug = _bug([1, 2])
    records, replays = replay_bugs(_adapter(["500", "200"]), [bug], _log("500", "200"), itertools.count(3))
    assert bug["kind"] == "bug" and bug["replay"] == REPRODUCED
    assert [t["replay"] for t in records[0]["tests"]] == [3, 4]
    assert [r["replay_of"] for r in replays] == [1, 2]


def test_a_bug_that_doesnt_reproduce_is_lowered_to_an_anomaly():
    # The milestone run's shape: the 500 came from a stale session, and a fresh one gets 200.
    bug = _bug([1])
    records, _ = replay_bugs(_adapter(["200"]), [bug], _log("500"), itertools.count(2))
    assert records[0]["verdict"] == NOT_REPRODUCED
    assert bug["kind"] == "anomaly" and bug["driver_kind"] == "bug"
    assert "didn't come out the same" in bug["lowered_because"] and "got 200" in bug["lowered_because"]


def test_nothing_is_replayed_while_the_adapter_says_replays_cant_be_trusted():
    bug = _bug([1])
    records, replays = replay_bugs(_adapter([], before_replay=lambda: "the saved session has expired"),
                                   [bug], _log("500"), itertools.count(2))
    assert replays == [] and records[0]["verdict"] == UNVERIFIABLE
    assert bug["kind"] == "anomaly" and "the saved session has expired" in bug["lowered_because"]


def test_a_bug_citing_a_test_that_wasnt_kept_as_cast_cant_be_replayed():
    bug = _bug([1, 9])
    records, replays = replay_bugs(_adapter(["500"]), [bug], _log("500"), itertools.count(2))
    assert replays == [] and records[0]["verdict"] == UNVERIFIABLE and bug["kind"] == "anomaly"


def test_a_replay_that_crashes_is_a_missing_check_not_a_failed_run():
    def boom(test, n):
        raise RuntimeError("browser gone")
    adapter = _adapter([])
    adapter = SUTAdapter(**{**adapter.__dict__, "execute_test": boom})
    bug = _bug([1])
    records, _ = replay_bugs(adapter, [bug], _log("500"), itertools.count(2))
    assert records[0]["verdict"] == UNVERIFIABLE and "browser gone" in records[0]["detail"]


def test_an_adapter_without_replay_keeps_its_bugs_marked_not_replayed():
    bug, finding = _bug([1]), {**_bug([1], "C2.O2"), "kind": "finding"}
    records, replays = replay_bugs(_adapter([], compare=False), [bug, finding], _log("500"), itertools.count(2))
    assert bug["kind"] == "bug" and bug["replay"] == NOT_AVAILABLE and "replay" not in finding
    assert replays == [] and [r["observation_id"] for r in records] == ["C2.O1"]


def test_the_test_as_cast_is_kept_for_replay_but_never_shown_to_the_model():
    assert default_redact_history_for_model([{"test_number": 1, "cast_test": {"a": 1}, "x": 2}]) == [
        {"test_number": 1, "x": 2}]


def test_a_run_writes_no_bug_report_for_a_bug_that_doesnt_reproduce(monkeypatch, tmp_path):
    values = iter(["500", "200"])   # the run's test, then its replay
    adapter = SUTAdapter(**{**_adapter([]).__dict__,
                            "execute_test": lambda test, n: {"test_number": n, "value": next(values)}})
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(200))
    monkeypatch.setattr(runner, "get_happy_day_example", lambda a: {"request": {"body": {}}, "response": {"body": {}}})
    monkeypatch.setattr(runner, "build_client", lambda: object())
    monkeypatch.setattr(loop, "get_casting_round", lambda *a, **k: {
        "give_up": False, "reasoning": "r", "candidate_tests": [{"linked_hypothesis": "", "predicted_outcome": "x"}]})
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", lambda *a, **k: {
        "summary": "s", "behaviors": [], "untested": [{"area": "u"}], "prior_gaps": [], "observations": [{
            "kind": "bug", "continues": "", "claim": "500", "tests": [1], "violates": "the docs", "reproduced": "consistent",
            "mechanism": "m", "rival": "r", "rival_ruled_out": True, "why": "w", "severity": "high"}]})
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **k: {
        "verdict": "satisfied", "verdict_reason": "r", "coverage": {"material": False, "untouched": [], "note": "c"},
        "observation_checks": [{"observation_id": "C1.O1", "kind": "bug", "discriminates_from_rival": True, "note": "n"}],
        "gaps": [], "prior_gaps_check": []})
    monkeypatch.setattr(runner, "get_bug_reports", lambda *a, **k: pytest.fail("a bug report was written"))

    output = runner.run(adapter, RunConfig(max_checkpoints=1, out_dir=tmp_path))
    assert output["observations"][0]["kind"] == "anomaly"
    assert output["replays"][0]["verdict"] == NOT_REPRODUCED
    assert output["replay_log"][0]["replay_of"] == 1 and output["replay_log"][0]["test_number"] == 2
    assert json.loads((tmp_path / "output.json").read_text())["casting_log"][0]["cast_test"]["predicted_outcome"] == "x"
    assert "replay: not reproduced" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_a_cited_test_whose_original_showed_nothing_doesnt_count_either_way():
    # The milestone bug cited tests 7 and 8, which never reached their state, beside test 13.
    def compare(original, replayed):
        if original["value"] == "nothing":
            return {"same": None, "detail": "the original didn't act", "original_ran": False}
        return {"same": original["value"] == replayed["value"], "detail": f"got {replayed['value']}"}
    adapter = SUTAdapter(**{**_adapter(["x", "500"]).__dict__, "compare_replay": compare})
    bug = _bug([1, 2])
    records, _ = replay_bugs(adapter, [bug], _log("nothing", "500"), itertools.count(3))
    assert records[0]["verdict"] == REPRODUCED and bug["kind"] == "bug"
    only_nothing = _bug([1])
    adapter = SUTAdapter(**{**_adapter(["x"]).__dict__, "compare_replay": compare})
    records, _ = replay_bugs(adapter, [only_nothing], _log("nothing"), itertools.count(3))
    assert records[0]["verdict"] == UNVERIFIABLE and "showed anything" in only_nothing["lowered_because"]
