"""Re-judging a saved run: the same tests, only the judging again (issue #370). A stubbed
model, no browser, no network."""

import json

import pytest

import trailhound.loop as loop
import trailhound.runner as runner
from trailhound import rejudge
from trailhound.adapter import SUTAdapter
from trailhound.config import RunConfig

RESULTS = {1: {"status": 200, "note": "ok"}, 2: {"status": 500, "note": "boom"}, 3: {"status": 200, "note": "again"}}


def _adapter(executed):
    def execute(test, n):
        executed.append(n)
        return {"test_number": n, "request": {"state": test["state"]}, "response": RESULTS[n],
                "predicted_outcome": test["predicted_outcome"], "prediction_matched": RESULTS[n]["status"] == 200}
    return SUTAdapter(
        name="fake", display_name="Fake", api_schema_doc="live doc",
        casting_tool_schema={"name": "submit_casting_round", "input_schema": {"properties": {
            "candidate_tests": {"type": "array", "items": {"properties": {}, "required": []}}}}},
        casting_system_prompt=lambda budget, first: "cast", validate_casting_response=lambda data: [],
        execute_test=execute, render_test_entry=lambda entry: "", render_onboarding_section=lambda *a: "",
        check_sut_ready=lambda a: None, fetch_happy_day_example=lambda a: {"request": {"r": 1}, "response": {"s": 2}})


def _model(sent):
    """Answers every call the same way, and records what each judging call was sent."""
    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            n = sum(1 for s in sent if s[0] == tool) + 1
            sent.append((tool, None))
            tests = [{"linked_hypothesis": "", "state": f"s{n}{i}", "predicted_outcome": "x"} for i in range(2 if n == 1 else 1)]
            return {"give_up": False, "reasoning": f"round {n}", "candidate_tests": tests}
        sent.append((tool, json.dumps({"system": kw.get("system"), "user": kw.get("user_message"),
                                       "cached": kw.get("cached_segments")}, sort_keys=True)))
        if tool == "submit_checkpoint_hypothesis":
            return {"summary": "s", "prior_gaps": [], "observations": [
                {"kind": "anomaly", "continues": "", "claim": "c", "tests": [1], "violates": "", "reproduced": "once",
                 "rival": "r", "rival_ruled_out": False, "severity": "low"}]}
        oid = json.loads(kw["user_message"])["observations"][0]["id"]
        return {"verdict": "weak", "verdict_reason": "v", "coverage": {"material": False}, "prior_gaps_check": [],
                "observation_checks": [{"observation_id": oid, "discriminates_from_rival": False,
                                        "rival_is_genuine": True, "kind": "anomaly"}],
                "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": True, "kind": "rival_not_tested",
                          "about": [oid]}]}
    return fake


def _live_run(monkeypatch, tmp_path):
    sent, executed = [], []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(sent))
    monkeypatch.setattr(runner, "build_client", lambda: None)
    adapter = _adapter(executed)
    output = runner.run(adapter, RunConfig(max_checkpoints=2, lean=True, out_dir=tmp_path / "live"))
    return output, sent, executed, adapter


def test_a_re_judged_run_sends_the_judging_exactly_what_the_live_run_did(monkeypatch, tmp_path):
    output, live_sent, executed, adapter = _live_run(monkeypatch, tmp_path)
    assert executed == [1, 2, 3] and len(output["checkpoints"]) == 2
    saved = json.loads((tmp_path / "live" / "output.json").read_text(encoding="utf-8"))

    replay = rejudge.saved_replay(saved, "live")
    assert replay["test_numbers"] == [1, 2, 3]
    assert [t["state"] for t in replay["rounds"][1]["tests"]] == ["s10", "s11"]
    executed.clear()
    re_sent = []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(re_sent))
    monkeypatch.setattr(runner, "start_run", lambda: pytest.fail("a re-judged run shares rejudge's spending limit"))
    again = runner.run(rejudge.replaying_adapter(adapter, saved, replay),
                       RunConfig(max_checkpoints=2, lean=True, out_dir=tmp_path / "again"), replay=replay)

    assert executed == []                                  # nothing ran: the saved results came back
    assert [s[0] for s in re_sent] == [s[0] for s in live_sent if s[0] != "submit_casting_round"]
    assert [s[1] for s in re_sent] == [s[1] for s in live_sent if s[0] != "submit_casting_round"]
    assert again["rejudged_from"] == "live" and again["replays"] == []
    assert [e["test_number"] for e in again["casting_log"]] == [1, 2, 3]
    assert again["casting_log"] == saved["casting_log"]


def test_a_re_judged_run_that_goes_past_the_saved_one_stops(monkeypatch, tmp_path):
    output, _, _, adapter = _live_run(monkeypatch, tmp_path)
    saved = json.loads((tmp_path / "live" / "output.json").read_text(encoding="utf-8"))
    replay = rejudge.saved_replay(saved, "live")
    monkeypatch.setattr(loop, "call_tool_with_retry", _model([]))
    again = runner.run(rejudge.replaying_adapter(adapter, saved, replay),
                       RunConfig(max_checkpoints=3, lean=True, out_dir=tmp_path / "again"), replay=replay)
    assert again["stopped_reason"] == "replay_ended" and len(again["checkpoints"]) == 2


def test_the_videos_a_live_run_kept_are_taken_off(monkeypatch, tmp_path):
    # Found in review: the runner adds "video" to cited tests after the loop, and handing it
    # back told the judging which tests the saved judging relied on.
    output, live_sent, _, adapter = _live_run(monkeypatch, tmp_path)
    saved = json.loads((tmp_path / "live" / "output.json").read_text(encoding="utf-8"))
    saved["casting_log"][0]["video"] = "videos/test_1.webm"
    replay = rejudge.saved_replay(saved, "live")
    assert "video" not in replay["results"][1]
    re_sent = []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(re_sent))
    runner.run(rejudge.replaying_adapter(adapter, saved, replay),
               RunConfig(max_checkpoints=2, lean=True, out_dir=tmp_path / "again"), replay=replay)
    assert [s[1] for s in re_sent] == [s[1] for s in live_sent if s[0] != "submit_casting_round"]


def test_a_saved_run_that_stopped_early_allows_one_more_checkpoint():
    assert rejudge.checkpoints_allowed({"checkpoints": [{}, {}], "stopped_reason": "skeptic_satisfied"}) == 3
    assert rejudge.checkpoints_allowed({"checkpoints": [{}, {}, {}], "stopped_reason": "checkpoints_exhausted"}) == 3


def test_a_run_saved_before_cast_tests_were_kept_is_refused():
    with pytest.raises(SystemExit, match="before cast tests were kept"):
        rejudge.saved_replay({"casting_log": [{"checkpoint": 1, "test_number": 1}], "checkpoints": []}, "old")


def test_the_cli_repeats_and_prints_one_row_each(monkeypatch, tmp_path, capsys):
    output, _, _, adapter = _live_run(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "call_tool_with_retry", _model([]))
    monkeypatch.setattr(rejudge, "load_adapter", lambda name: adapter)
    monkeypatch.setattr(rejudge, "available_adapters", lambda: ["fake"])
    rejudge.main([str(tmp_path / "live"), "--adapter", "fake", "--times", "2", "--out", str(tmp_path / "exp")])
    out = capsys.readouterr().out
    assert "| saved | checkpoints_exhausted | 2 |" in out and "| r1 |" in out and "| r2 |" in out
    assert (tmp_path / "exp" / "r2" / "output.json").exists() and (tmp_path / "exp" / "r2" / "report.html").exists()
    assert json.loads((tmp_path / "exp" / "r1" / "output.json").read_text(encoding="utf-8"))["lean"] == {"with": []}
