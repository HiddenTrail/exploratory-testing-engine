"""trailhound.runner.run() writes output.json incrementally after every
checkpoint, not just once at the end - verified by making a checkpoint
raise partway through and confirming the earlier, already-completed
checkpoints survive on disk rather than being lost with the crash. No
network calls: the SUT readiness probe, happy-day fetch, and the three
Anthropic-calling functions inside the loop are all stubbed."""

import json

import httpx
import pytest

import trailhound.loop as loop
import trailhound.runner as runner
from trailhound.adapter import SUTAdapter
from trailhound.config import RunConfig

_FAKE_ADAPTER = SUTAdapter(
    name="fake_runner_test",
    display_name="Fake",
    base_url="http://example.invalid",
    test_endpoint_path="/x",
    casting_tool_schema={},
    casting_system_prompt=lambda budget, is_first: "",
    validate_casting_response=lambda data: [],
    execute_test=lambda test, test_number: {
        "test_number": test_number, "request": {}, "response": {}, "predicted_outcome": "", "prediction_matched": True,
    },
    render_test_entry=lambda entry: "",
    render_onboarding_section=lambda *a: "",
)


@pytest.fixture(autouse=True)
def _stub_sut_io(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(200))
    monkeypatch.setattr(runner, "get_happy_day_example", lambda adapter: {"request": {"body": {}}, "response": {"body": {}}})
    monkeypatch.setattr(runner, "build_client", lambda: object())


def _fake_casting_round(client, adapter, run_config, happy_day_example, casting_log, prior_feedback, *, test_budget, is_first_round, usage_sink=None, run_diagnostics=None, **_):
    return {"give_up": False, "reasoning": "r", "candidate_tests": [{"linked_hypothesis": "", "predicted_outcome": "x"}]}


def _fake_hypothesis(client, adapter, run_config, happy_day_example, casting_log, prior_skeptic_review=None, run_diagnostics=None, usage_sink=None, earlier_observations=None, **_):
    return {"summary": "b", "behaviors": [], "observations": [], "untested": [{"area": "u"}], "prior_gaps": []}


def _skeptic_review(verdict):
    return {
        "verdict": verdict, "verdict_reason": "r", "observation_checks": [], "coverage": {"material": verdict == "weak", "untouched": [], "note": "c"}, "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": False, "kind": "other", "about": []}], "prior_gaps_check": [],
    }


def test_output_json_written_incrementally_and_survives_a_mid_run_crash(monkeypatch, tmp_path):
    checkpoint_count = {"n": 0}

    def flaky_skeptic(client, run_config, hypothesis, prior_skeptic_review=None, usage_sink=None, test_coverage=None, previous_story=None, **_):
        checkpoint_count["n"] += 1
        if checkpoint_count["n"] == 2:
            raise ValueError("simulated unexpected failure mid-run")
        return _skeptic_review("weak")

    monkeypatch.setattr(loop, "get_casting_round", _fake_casting_round)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", flaky_skeptic)
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})

    run_config = RunConfig(max_checkpoints=4, out_dir=tmp_path)
    output = runner.run(_FAKE_ADAPTER, run_config)

    # The run as a whole reports the failure...
    assert "error" in output
    assert "simulated unexpected failure" in output["error"]

    # ...but checkpoint 1, which completed before the crash, was written to
    # disk by save_progress and is not lost.
    on_disk = json.loads((tmp_path / "output.json").read_text())
    assert len(on_disk["checkpoints"]) == 1
    assert on_disk["checkpoints"][0]["hypothesis"]["summary"] == "b"


def _casting_round_billing(tokens):
    """A casting stub that also reports what the call cost, the way
    call_tool_with_retry's usage_sink does for a real one."""
    def fake(client, adapter, run_config, happy_day_example, history_segments, prior_feedback,
             *, test_budget, is_first_round, usage_sink=None, run_diagnostics=None, **_):
        usage_sink.append({
            "call": "submit_casting_round", "at": "2026-08-26T09:00:00+00:00",
            "input_tokens": tokens, "output_tokens": 1,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        })
        return _fake_casting_round(
            client, adapter, run_config, happy_day_example, history_segments, prior_feedback,
            test_budget=test_budget, is_first_round=is_first_round,
        )
    return fake


def test_output_json_keeps_the_raw_per_call_usage_log_beside_the_summary(monkeypatch, tmp_path):
    # The aggregate alone can't say which call missed the cache or how long
    # since the previous one, which is exactly what diagnosing a caching
    # regression from a single real run needs.
    monkeypatch.setattr(loop, "get_casting_round", _casting_round_billing(120))
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **kw: _skeptic_review("weak"))
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})

    runner.run(_FAKE_ADAPTER, RunConfig(max_checkpoints=3, out_dir=tmp_path))

    on_disk = json.loads((tmp_path / "output.json").read_text())
    assert [record["input_tokens"] for record in on_disk["usage_log"]] == [120, 120, 120]
    assert all(record["at"] for record in on_disk["usage_log"])
    assert on_disk["usage_summary"]["submit_casting_round"]["calls"] == 3


def test_mid_run_saves_already_carry_the_usage_recorded_so_far(monkeypatch, tmp_path):
    # A run that dies mid-way is the one most worth having token numbers for -
    # those calls were still billed. Read the file from inside a later call,
    # since by then save_progress has written the earlier checkpoints but the
    # run's own final write hasn't happened yet.
    billing = _casting_round_billing(50)
    mid_run_views = []

    def peeking_casting(*args, **kwargs):
        path = tmp_path / "output.json"
        if path.exists():
            mid_run_views.append(json.loads(path.read_text())["usage_log"])
        return billing(*args, **kwargs)

    monkeypatch.setattr(loop, "get_casting_round", peeking_casting)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **kw: _skeptic_review("weak"))
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})

    runner.run(_FAKE_ADAPTER, RunConfig(max_checkpoints=3, out_dir=tmp_path))

    # Checkpoint 1 wrote nothing yet; checkpoints 2 and 3 each saw the previous
    # checkpoints' records already on disk.
    assert [len(view) for view in mid_run_views] == [1, 2]
    assert all(record["input_tokens"] == 50 for view in mid_run_views for record in view)


def _hypothesis_with(kind):
    def hypothesis(*a, **kw):
        return {"summary": "b", "behaviors": [], "untested": [{"area": "u"}], "prior_gaps": [],
                "observations": [{"kind": kind, "continues": "", "claim": "x", "tests": [1],
                                  "violates": "the limit is 5" if kind == "bug" else "",
                                  "reproduced": "consistent", "mechanism": "m", "rival": "r",
                                  "rival_ruled_out": True, "why": "w", "severity": "low"}]}
    return hypothesis


def _review_checking_one_observation(verdict):
    review = _skeptic_review(verdict)
    review["observation_checks"] = [{"observation_id": "C1.O1", "discriminates_from_rival": True,
                                     "rival_is_genuine": True, "kind": "bug", "note": "n"}]
    return review


def test_bug_report_failure_does_not_clobber_a_successful_run_verdict(monkeypatch, tmp_path):
    # A bug-report generation failure (e.g. the tool call exhausting its retries on a
    # max_tokens cutoff) must NOT rewrite a run that already concluded as "error" and
    # discard its verdict - it degrades to "no bug reports written" + a note.
    monkeypatch.setattr(loop, "get_casting_round", _fake_casting_round)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _hypothesis_with("bug"))
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **kw: _review_checking_one_observation("strong_enough"))
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})

    def boom(*a, **kw):
        raise RuntimeError("bug-report tool exhausted retries")
    monkeypatch.setattr(runner, "get_bug_reports", boom)

    output = runner.run(_FAKE_ADAPTER, RunConfig(max_checkpoints=3, out_dir=tmp_path))

    assert "error" not in output
    assert output["stopped_reason"] == "skeptic_satisfied"   # the real verdict, preserved
    assert output["anomaly_found"] is True
    assert "bug-report tool exhausted retries" in output.get("bug_report_error", "")
    on_disk = json.loads((tmp_path / "output.json").read_text())
    assert on_disk["stopped_reason"] == "skeptic_satisfied"


def test_output_json_reflects_final_state_on_a_clean_run(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "get_casting_round", _fake_casting_round)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **kw: _skeptic_review("strong_enough"))
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})

    run_config = RunConfig(max_checkpoints=4, out_dir=tmp_path)
    output = runner.run(_FAKE_ADAPTER, run_config)

    assert "error" not in output
    assert output["stopped_reason"] == "skeptic_satisfied"
    on_disk = json.loads((tmp_path / "output.json").read_text())
    assert on_disk["stopped_reason"] == "skeptic_satisfied"
    assert len(on_disk["checkpoints"]) == 1


def test_only_bugs_get_a_written_report_and_every_observation_gets_a_status(monkeypatch, tmp_path):
    # An anomaly is complete in output["observations"]; spending an LLM call to write
    # it up again is exactly what issue #41 removed.
    monkeypatch.setattr(loop, "get_casting_round", _fake_casting_round)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", _hypothesis_with("anomaly"))
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **kw: _review_checking_one_observation("strong_enough"))
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": []})
    monkeypatch.setattr(loop, "get_reconsideration", lambda client, run_config, review, *a, **k: {"judgements": [], "revised_checks": [], "verdict": review["verdict"], "verdict_reason": review["verdict_reason"]})
    calls = []
    monkeypatch.setattr(runner, "get_bug_reports", lambda *a, **kw: calls.append(a) or [])

    output = runner.run(_FAKE_ADAPTER, RunConfig(max_checkpoints=3, out_dir=tmp_path))

    assert calls == []
    assert output["anomaly_found"] is True
    assert [(o["id"], o["kind"], o["status"]) for o in output["observations"]] == [("C1.O1", "anomaly", "corroborated")]


def test_learn_feeds_the_run_into_the_context_after_it_ends(monkeypatch, tmp_path):
    # Issue #159: one command per run; the next run starts from what this one learned.
    import sys
    import trailhound.cli as cli
    import trailhound.ontology.feedback as feedback
    calls = []
    monkeypatch.setattr(cli, "run", lambda adapter, config: {"stopped_reason": "checkpoints_exhausted"})
    monkeypatch.setattr(feedback, "learn", lambda sut, path, product: calls.append((sut, path, product)) or ["ok"])
    monkeypatch.setattr(sys, "argv", ["cli", "--adapter", "token_purchase", "--out-dir", str(tmp_path), "--learn", "shop"])
    cli.main()
    assert calls == [("token_purchase", tmp_path / "output.json", "shop")]
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["cli", "--adapter", "token_purchase", "--out-dir", str(tmp_path), "--learn"])
    cli.main()
    assert calls == [("token_purchase", tmp_path / "output.json", None)]
    calls.clear()
    for reason in ("error", "budget_exceeded"):          # a run that broke or hit the limit teaches nothing
        monkeypatch.setattr(cli, "run", lambda adapter, config, r=reason: {"stopped_reason": r})
        with pytest.raises(SystemExit) as stopped:
            cli.main()
        assert stopped.value.code == 2 and calls == []
    monkeypatch.setattr(cli, "run", lambda adapter, config: {"stopped_reason": "checkpoints_exhausted"})
    monkeypatch.setattr(sys, "argv", ["cli", "--adapter", "token_purchase", "--out-dir", str(tmp_path)])
    cli.main()
    assert calls == []                                  # without --learn, nothing is written


def test_the_run_command_gives_the_driver_the_skeptics_history(monkeypatch, tmp_path):
    import json
    import sys
    import trailhound.cli as cli
    seen = []
    (tmp_path / "context_shop.json").write_text(json.dumps({"skeptic_objections": {
        "method_in_doubt": {"times": 3, "blocking": 2, "runs": ["r1"], "example": "e"}}}), encoding="utf-8")
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "run", lambda adapter, config: seen.append(config.skeptic_history) or {"stopped_reason": "x"})
    monkeypatch.setattr("trailhound.ontology.feedback.learn", lambda *a: [])
    monkeypatch.setattr(sys, "argv", ["cli", "--adapter", "token_purchase", "--out-dir", str(tmp_path), "--learn", "shop"])
    cli.main()
    assert [h["kind"] for h in seen[0]["most_common"]] == ["method_in_doubt"]
    monkeypatch.setattr(sys, "argv", ["cli", "--adapter", "token_purchase", "--out-dir", str(tmp_path)])
    cli.main()
    assert seen[1] is None                              # no context_token_purchase.json in this folder
