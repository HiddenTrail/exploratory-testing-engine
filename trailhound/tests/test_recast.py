"""Asking a saved run's casting round again (issue #371). A stubbed model, no browser."""

import json

import pytest

import trailhound.loop as loop
import trailhound.runner as runner
from trailhound import recast
from trailhound.ask import saved_adapter
from trailhound.config import RunConfig
from trailhound.tests.test_rejudge import _adapter


def _model(sent):
    """Answers like a Driver and Skeptic would, with a debrief that promises a new approach,
    and records every casting call exactly as it was made."""
    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            sent.append(json.dumps({k: kw.get(k) for k in ("system", "user_message", "cached_segments", "tools")},
                                   sort_keys=True))
            n = len(sent)
            first = json.loads(kw["user_message"]).get("answer_first", "")
            tests = [{"linked_hypothesis": "", "state": f"s{n}{i}", "predicted_outcome": "x"} for i in range(2)]
            if first:
                gid = first.split(": ")[1][:5]
                tests[0].update(follows_up=gid, rules_out_if="r")
            return {"give_up": False, "reasoning": f"round {n}", "candidate_tests": tests}
        if tool == "submit_checkpoint_hypothesis":
            return {"summary": "s", "prior_gaps": [], "observations": [
                {"kind": "anomaly", "continues": "", "claim": "c", "tests": [1], "violates": "", "reproduced": "once",
                 "rival": "r", "rival_ruled_out": False, "severity": "low"}]}
        if tool == "submit_debrief_answers":
            gaps = json.loads(kw["user_message"])["skeptic_questions"]
            return {"answers": [{"gap_id": g["id"], "stance": "change_approach", "tests": [],
                                 "argument": "next round I'll open it in a new tab"} for g in gaps]}
        if tool == "submit_reconsideration":
            gaps = [a["question"]["id"] for a in json.loads(kw["user_message"])["answers"]]
            return {"judgements": [{"gap_id": g, "convinced": "partly", "why": "w"} for g in gaps],
                    "revised_checks": [], "verdict": "weak", "verdict_reason": "v"}
        oid = json.loads(kw["user_message"])["observations"][0]["id"]
        return {"verdict": "weak", "verdict_reason": "v", "coverage": {"material": False}, "prior_gaps_check": [],
                "observation_checks": [{"observation_id": oid, "discriminates_from_rival": False,
                                        "rival_is_genuine": True, "kind": "anomaly"}],
                "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": True, "kind": "rival_not_tested",
                          "about": [oid]},
                         {"gap": "h", "next_test": "t", "blocks_verdict": False, "kind": "coverage_overstated",
                          "about": []}]}
    return fake


@pytest.fixture
def saved_run(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(sent))
    monkeypatch.setattr(runner, "build_client", lambda: None)
    import trailhound.tests.test_rejudge as tr
    for n in (4, 5, 6):                       # the shared fake's results, put back after the test
        monkeypatch.setitem(tr.RESULTS, n, {"status": 200, "note": f"r{n}"})
    adapter = _adapter([])
    config = RunConfig(max_checkpoints=3, first_round_test_budget=4, default_test_budget=4, lean=True,
                       lean_with=frozenset({"debrief"}), out_dir=tmp_path / "live",
                       skeptic_history={"most_common": [{"kind": "rival_not_tested"}]})
    runner.run(adapter, config)
    return json.loads((tmp_path / "live" / "output.json").read_text(encoding="utf-8")), sent, adapter


def test_the_rebuilt_casting_call_is_the_one_the_loop_made(monkeypatch, saved_run):
    output, live_sent, adapter = saved_run
    assert output["settings"]["default_test_budget"] == 4 and output["settings"]["skeptic_history"]
    assert output["checkpoints"][1].get("promises")             # the run did carry promises and blocking questions
    rebuilt = []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(rebuilt))
    config = RunConfig(first_round_test_budget=4, default_test_budget=4, lean=True, lean_with=frozenset({"debrief"}),
                       skeptic_history=output["settings"]["skeptic_history"])
    saved = saved_adapter(adapter, output)
    for k in (1, 2, 3):
        call = recast.casting_call(output, saved, config, k)
        recast.get_casting_round(None, *call["args"], usage_sink=[], **call["kwargs"])
    assert rebuilt == live_sent                                  # byte for byte, every checkpoint


def test_a_round_is_counted_after_the_loops_limits(saved_run):
    output, _, adapter = saved_run
    config = RunConfig(first_round_test_budget=4, default_test_budget=4, lean=True)
    call = recast.casting_call(output, saved_adapter(adapter, output), config, 2)
    limits = call["limits"]
    assert limits["blocking"] and limits["promised"]
    gid = limits["blocking"][0]
    answer = {"candidate_tests": [{"follows_up": gid, "rules_out_if": "r", "state": "a"},
                                  {"follows_up": "C1.O1", "state": "b"}, {"follows_up": "C1.O1", "state": "b"},
                                  {"state": "c"}]}
    counts = recast.measure(answer, limits)
    assert counts["cast"] == 4 and counts["first_answered"] == 1 and counts["first_needed"] == 2
    assert counts["follow_ups"] == 2 and counts["dropped"] == 1           # one over the cap of 1
    assert counts["free"] == 1 and counts["starts"] == 3
    assert recast.saved_round(output, 2, limits)["to_run"] == 2


def test_a_run_too_short_or_without_settings_is_refused(saved_run, tmp_path):
    output, _, adapter = saved_run
    with pytest.raises(SystemExit, match="can't be rebuilt"):
        recast.casting_call(output, saved_adapter(adapter, output), RunConfig(), 5)
    old = {k: v for k, v in output.items() if k != "settings"}
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "output.json").write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(SystemExit):
        recast.main([str(tmp_path / "old"), "--adapter", "web_gui", "--checkpoint", "2", "--out", str(tmp_path / "o")])


def test_the_cli_asks_n_times_and_prints_a_row_each(monkeypatch, saved_run, tmp_path, capsys):
    output, _, adapter = saved_run
    (tmp_path / "saved").mkdir()
    (tmp_path / "saved" / "output.json").write_text(json.dumps(output), encoding="utf-8")
    monkeypatch.setattr(loop, "call_tool_with_retry", _model([]))
    monkeypatch.setattr(recast, "load_adapter", lambda name: adapter)
    monkeypatch.setattr(recast, "available_adapters", lambda: ["fake"])
    monkeypatch.setattr(recast, "build_client", lambda: None)
    recast.main([str(tmp_path / "saved"), "--adapter", "fake", "--checkpoint", "2", "--times", "2",
                 "--out", str(tmp_path / "exp")])
    out = capsys.readouterr().out
    assert "| saved |" in out and "| r1 |" in out and "| r2 |" in out
    saved = json.loads((tmp_path / "exp" / "rounds.json").read_text(encoding="utf-8"))
    assert saved["checkpoint"] == 2 and len(saved["rounds"]) == 2


def test_the_videos_a_live_run_kept_are_taken_off_the_history(monkeypatch, saved_run):
    # Found in review: the runner adds "video" to cited tests after the loop, which the loop never sent.
    output, live_sent, adapter = saved_run
    for e in output["casting_log"][:2]:
        e["video"] = f"videos/test_{e['test_number']}.webm"
    rebuilt = []
    monkeypatch.setattr(loop, "call_tool_with_retry", _model(rebuilt))
    config = RunConfig(first_round_test_budget=4, default_test_budget=4, lean=True, lean_with=frozenset({"debrief"}),
                       skeptic_history=output["settings"]["skeptic_history"])
    call = recast.casting_call(output, saved_adapter(adapter, output), config, 2)
    recast.get_casting_round(None, *call["args"], usage_sink=[], **call["kwargs"])
    assert rebuilt[0] == live_sent[1] and "video" not in rebuilt[0]


def test_the_round_after_the_last_can_be_asked_with_no_saved_round(saved_run):
    output, _, adapter = saved_run
    call = recast.casting_call(output, saved_adapter(adapter, output), RunConfig(default_test_budget=4), 4)
    assert recast.saved_round(output, 4, call["limits"]) is None
    assert "never cast" in recast.row("saved", None)


def test_the_salvage_drops_count_as_cast_and_dropped():
    limits = {"test_budget": 6, "parked_ids": set(), "idea_ids": frozenset(), "blocking": (), "promised": ()}
    counts = recast.measure({"candidate_tests": [{"start": "/"}], "dropped_tests": [{"test": {}, "errors": ["x"]}]},
                            limits)
    assert (counts["cast"], counts["to_run"], counts["dropped"], counts["starts"]) == (2, 1, 1, 1)
    assert recast.measure({"candidate_tests": [{"x": 1}]}, limits)["starts"] == "-"
