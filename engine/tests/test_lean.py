"""Lean runs for experiments (issue #295): which calls a lean run makes, what it asks the
model for, how the dropped fields come back, and asking a saved run afterwards. A stubbed
client only, no model calls."""

import itertools
import json

import pytest

from engine import ask, lean, loop
from engine.config import RunConfig
from engine.report import render_report
from engine.run_summary import summarize
from engine.runner import lean_line
from engine.tests.test_client_retry import _FakeClient, _FakeMessage, _FakeToolUse
from engine.tools import HYPOTHESIS_TOOL, SKEPTIC_TOOL, validate_hypothesis_response, validate_skeptic_response

LEAN_OBSERVATION = {"kind": "anomaly", "continues": "", "claim": "c", "tests": [1], "violates": "",
                    "reproduced": "once", "rival": "r", "rival_ruled_out": False, "severity": "low"}
LEAN_HYPOTHESIS = {"summary": "s", "observations": [LEAN_OBSERVATION], "prior_gaps": []}
LEAN_REVIEW = {"verdict": "weak", "verdict_reason": "v",
               "observation_checks": [{"observation_id": "C1.O1", "discriminates_from_rival": False,
                                       "rival_is_genuine": True, "kind": "anomaly"}],
               "coverage": {"material": False},
               "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": True, "kind": "rival_not_tested",
                         "about": ["C1.O1"]}],
               "prior_gaps_check": []}


def test_a_lean_schema_doesnt_ask_for_the_dropped_fields():
    hypothesis = lean.strip_schema(HYPOTHESIS_TOOL, lean.HYPOTHESIS_DROPS)["input_schema"]
    assert "behaviors" not in hypothesis["properties"] and "untested" not in hypothesis["required"]
    observation = hypothesis["properties"]["observations"]["items"]
    assert {"mechanism", "why"}.isdisjoint(observation["properties"]) and "rival" in observation["required"]
    skeptic = lean.strip_schema(SKEPTIC_TOOL, lean.SKEPTIC_DROPS)["input_schema"]["properties"]
    assert set(skeptic["coverage"]["properties"]) == {"material"}
    assert "note" not in skeptic["observation_checks"]["items"]["properties"]
    # The shared schemas themselves are untouched.
    assert "behaviors" in HYPOTHESIS_TOOL["input_schema"]["properties"]


def test_the_dropped_fields_come_back_empty_so_nothing_downstream_changes():
    filled = lean.fill(json.loads(json.dumps(LEAN_HYPOTHESIS)), HYPOTHESIS_TOOL, lean.HYPOTHESIS_DROPS)
    assert (filled["behaviors"], filled["untested"]) == ([], [])
    assert (filled["observations"][0]["mechanism"], filled["observations"][0]["why"]) == ("", "")
    review = lean.fill(json.loads(json.dumps(LEAN_REVIEW)), SKEPTIC_TOOL, lean.SKEPTIC_DROPS)
    assert review["coverage"] == {"material": False, "untouched": [], "note": ""}
    assert review["observation_checks"][0]["note"] == ""
    # Something the model sent anyway is kept.
    sent = lean.fill({**LEAN_HYPOTHESIS, "untested": [{"area": "a"}]}, HYPOTHESIS_TOOL, lean.HYPOTHESIS_DROPS)
    assert sent["untested"] == [{"area": "a"}]


def test_the_validators_accept_a_lean_answer_only_in_a_lean_run():
    assert validate_hypothesis_response(LEAN_HYPOTHESIS, lean=True) == []
    assert "missing required field 'behaviors'" in validate_hypothesis_response(LEAN_HYPOTHESIS)
    observations = [{**LEAN_OBSERVATION, "id": "C1.O1"}]
    assert validate_skeptic_response(LEAN_REVIEW, observations=observations, lean=True) == []
    assert any("note" in e for e in validate_skeptic_response(LEAN_REVIEW, observations=observations))


def test_a_run_config_says_which_parts_it_makes():
    full, bare, story = RunConfig(), RunConfig(lean=True), RunConfig(lean=True, lean_with=frozenset({"story"}))
    assert all(full.wants(p) for p in lean.PARTS) and not any(bare.wants(p) for p in lean.PARTS)
    assert story.wants("story") and not story.wants("debrief")
    with pytest.raises(ValueError, match="unknown lean part"):
        RunConfig(lean=True, lean_with=frozenset({"poem"}))
    with pytest.raises(ValueError, match="only means something in a lean run"):
        RunConfig(lean_with=frozenset({"story"}))
    assert lean_line(story) == ("Lean run, for experiments: the model writes only what decides a finding; "
                                "skipped: debrief, bug reports; switched back on: story.")


def _lean_loop(monkeypatch, lean_with=frozenset()):
    calls = []

    def fake(client, **kw):
        calls.append(kw)
        answers = {"submit_casting_round": {"give_up": True, "reasoning": "r", "candidate_tests": []},
                   "submit_checkpoint_hypothesis": LEAN_HYPOTHESIS, "submit_skeptic_review": LEAN_REVIEW,
                   "submit_testing_story": {"areas": [], "obstacles": []}}
        answer = json.loads(json.dumps(answers[kw["tool_name"]]))
        if kw["tool_name"] != "submit_testing_story":     # an empty story is only a stand-in here
            assert kw["validate_fn"](answer) == [], kw["tool_name"]
        return answer
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    adapter = type("A", (), {"casting_tool_schema": {"name": "submit_casting_round"}, "redact_history_for_model": None,
                             "casting_system_prompt": staticmethod(lambda budget, first: "cast"),
                             "validate_casting_response": staticmethod(lambda data: []),
                             "casting_max_tokens": staticmethod(lambda budget: 100),
                             "api_schema_doc": "doc", "onboarding_extra": {}})()
    config = RunConfig(max_checkpoints=1, lean=True, lean_with=frozenset(lean_with))
    _, checkpoints, _ = loop.run_checkpoint_loop(None, adapter, config, {}, itertools.count(1))
    return calls, checkpoints


def test_a_lean_checkpoint_skips_the_story_and_the_debrief(monkeypatch):
    calls, checkpoints = _lean_loop(monkeypatch)
    assert [c["tool_name"] for c in calls] == ["submit_casting_round", "submit_checkpoint_hypothesis",
                                               "submit_skeptic_review"]
    assert calls[0]["system"].endswith(lean.CASTING_NOTE)
    assert "behaviors" not in calls[1]["tools"][0]["input_schema"]["properties"]
    assert '"behaviors"' not in calls[2]["user_message"]          # the Skeptic isn't sent empty lists
    checkpoint = checkpoints[0]
    assert checkpoint["debrief"] == [] and checkpoint["hypothesis"]["behaviors"] == []
    assert checkpoint["skeptic_review"]["observation_checks"][0]["note"] == ""


def test_a_part_can_be_switched_back_on(monkeypatch):
    calls, _ = _lean_loop(monkeypatch, {"story"})
    assert "submit_testing_story" in [c["tool_name"] for c in calls]
    skeptic = next(c for c in calls if c["tool_name"] == "submit_skeptic_review")
    assert '"areas"' in skeptic["user_message"] and '"behaviors"' not in skeptic["user_message"]


def test_the_summary_and_the_report_say_a_run_was_lean():
    output = {"lean": {"with": ["story"]}, "casting_log": [], "checkpoints": []}
    assert "**Lean run, for experiments** (#295): compare it only with lean runs with the same parts on (story)." \
        in summarize(output)
    adapter = type("A", (), {"report_title": "R", "display_name": "D",
                             "render_onboarding_section": staticmethod(lambda *a: ""),
                             "render_test_entry": staticmethod(lambda e: "")})()
    assert "Checkpoints concluded · lean run with story" in render_report(output, [], adapter)


SAVED_RUN = {
    "api_schema": "doc", "onboarding_extra": {"carried_map": "m"}, "happy_day_example": {},
    "casting_log": [{"checkpoint": 1, "test_number": 1}, {"checkpoint": 2, "test_number": 2}],
    "checkpoints": [{"checkpoint": 1, "hypothesis": {"summary": "s1"}, "skeptic_review": {}, "debrief": []},
                    {"checkpoint": 2, "hypothesis": {"summary": "s2"}, "skeptic_review": {}, "debrief": []}],
    "observations": [{"id": "C2.O1", "kind": "anomaly"}],
}


def _adapter():
    from engine.adapter import SUTAdapter
    return SUTAdapter(name="x", display_name="X", base_url="", api_schema_doc="live doc")


def test_ask_answers_from_the_saved_record_and_never_overwrites(tmp_path):
    adapter = ask.saved_adapter(_adapter(), SAVED_RUN)
    assert (adapter.api_schema_doc, adapter.onboarding_extra) == ("doc", {"carried_map": "m"})
    assert len(ask.history_segments(adapter, SAVED_RUN["casting_log"], up_to=1)) == 1
    client = _FakeClient([_FakeMessage([_FakeToolUse("id1", {"answer": "Because test 2 also fits.", "tests": [2]})])])
    answer = ask.ask_question(client, adapter, RunConfig(), SAVED_RUN, "Why was C2.O1 doubted?", [])
    assert answer == {"question": "Why was C2.O1 doubted?", "answer": "Because test 2 also fits.", "tests": [2]}
    sent = client.messages.last_kwargs["messages"][0]["content"][-1]["text"]
    assert '"Why was C2.O1 doubted?"' in sent and '"s2"' in sent
    first, second = ask.save(tmp_path, "why", answer), ask.save(tmp_path, "why", answer)
    assert (first.name, second.name) == ("why.json", "why-2.json")


def test_ask_says_when_there_is_nothing_to_ask_for():
    with pytest.raises(SystemExit, match="no bugs"):
        ask.ask_bug_reports(None, _adapter(), RunConfig(), SAVED_RUN, [])
    with pytest.raises(SystemExit, match="no checkpoint 9"):
        ask.ask_story(None, _adapter(), RunConfig(), SAVED_RUN, 9, [])
