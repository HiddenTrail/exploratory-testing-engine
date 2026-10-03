"""The Driver's structured hypothesis (issue #41): the validator's rules for the
three observation kinds, ids and prior gaps, the word limits, and the ids the
engine stamps on. No LLM calls."""

import copy

from engine.tools import (
    HYPOTHESIS_TOOL,
    TESTING_STORY_TOOL,
    lower_unsupported_bugs,
    stamp_gap_ids,
    stamp_observation_ids,
    validate_hypothesis_response,
    validate_testing_story,
)

_OBSERVATION = {
    "kind": "bug", "continues": "", "claim": "Concurrent requests exceed the limit of 5",
    "tests": [1, 4], "violates": "The API reports limit=5 in every response", "reproduced": "consistent",
    "mechanism": "Non-atomic check-and-increment", "rival": "Per-connection counters",
    "rival_ruled_out": False, "why": "No test compared two clients", "severity": "high",
}

_HYPOTHESIS = {
    "summary": "Sequential requests are limited correctly, concurrent ones are not.",
    "behaviors": [{"claim": "Sequential requests stop at 5", "tests": [2, 3]}],
    "observations": [_OBSERVATION],
    "areas": [{"area": "Per-client rate limit", "approach": "API, sequential then concurrent bursts",
               "coverage": "common_and_critical", "coverage_of": "request timing and concurrency",
               "oracle": "accepted count above the disclosed limit", "not_tested": "Window reset, other clients",
               "tests": [1, 2, 3, 4], "quality": "problems_found", "confidence": "medium",
               "why": "Sequential holds at 5 (2, 3); bursts exceed it (1, 4)"}],
    "obstacles": [{"obstacle": "No way to reset the window on demand", "would_help": "A reset endpoint"}],
    "untested": [{"area": "Window reset timing"}],
    "prior_gaps": [],
}


def _hypothesis(**changes):
    data = copy.deepcopy(_HYPOTHESIS)
    data.update(changes)
    return data


def _with_observation(**changes):
    observation = {**_OBSERVATION, **changes}
    return _hypothesis(observations=[observation])


def test_a_complete_hypothesis_passes():
    assert validate_hypothesis_response(_hypothesis()) == []


def test_no_observations_is_fine():
    assert validate_hypothesis_response(_hypothesis(observations=[])) == []


def test_every_top_level_field_is_required():
    for key in HYPOTHESIS_TOOL["input_schema"]["required"]:
        data = _hypothesis()
        del data[key]
        assert f"missing required field '{key}'" in validate_hypothesis_response(data)


def test_an_unsupported_bug_is_accepted_and_then_lowered_to_an_anomaly():
    # Issue #99: rejecting it cost a whole retry, and by the rules it is an anomaly.
    for changes, reason in (({"violates": ""}, "it names no violated fact"),
                            ({"reproduced": "once"}, "it reproduced 'once', not consistently")):
        data = _with_observation(**changes)
        assert validate_hypothesis_response(data) == []
        lower_unsupported_bugs(data)
        observation = data["observations"][0]
        assert (observation["kind"], observation["driver_kind"], observation["lowered_because"]) == ("anomaly", "bug", reason)


def test_a_supported_bug_stays_a_bug():
    data = _hypothesis()
    lower_unsupported_bugs(data)
    assert data["observations"][0]["kind"] == "bug" and "driver_kind" not in data["observations"][0]


def test_an_anomaly_or_finding_needs_no_violated_fact():
    for kind in ("anomaly", "finding"):
        assert validate_hypothesis_response(_with_observation(kind=kind, violates="", reproduced="once")) == []


def test_an_unknown_kind_is_rejected():
    errors = validate_hypothesis_response(_with_observation(kind="defect"))
    assert any(".kind must be one of finding, anomaly, bug" in e for e in errors)


def test_continues_must_name_an_earlier_observation():
    data = _with_observation(continues="C1.O1")
    assert any("isn't an earlier observation id" in e for e in validate_hypothesis_response(data))
    assert validate_hypothesis_response(data, known_observation_ids=("C1.O1",)) == []


def test_an_observation_needs_test_numbers():
    errors = validate_hypothesis_response(_with_observation(tests=[]))
    assert any("tests must be a non-empty list of test numbers" in e for e in errors)


def test_a_slightly_long_field_passes_but_a_paragraph_does_not():
    # The limit for a claim is 30 words. A few words over costs no retry; more than
    # twice the limit does.
    assert validate_hypothesis_response(_with_observation(claim="word " * 33)) == []
    errors = validate_hypothesis_response(_with_observation(claim="word " * 61))
    assert any("far too long (61 words, limit 30)" in e for e in errors)


def test_every_prior_gap_must_be_answered_once():
    open_gaps = ("C1.G1", "C1.G2")
    answer = {"gap_id": "C1.G1", "status": "tested", "tests": [7], "reason": ""}

    errors = validate_hypothesis_response(_hypothesis(prior_gaps=[answer]), open_gap_ids=open_gaps)
    assert any("doesn't answer C1.G2" in e for e in errors)

    twice = [answer, answer, {**answer, "gap_id": "C1.G2"}]
    errors = validate_hypothesis_response(_hypothesis(prior_gaps=twice), open_gap_ids=open_gaps)
    assert any("answers C1.G1 more than once" in e for e in errors)

    both = [answer, {**answer, "gap_id": "C1.G2"}]
    assert validate_hypothesis_response(_hypothesis(prior_gaps=both), open_gap_ids=open_gaps) == []


def test_a_prior_gap_must_be_one_the_prior_review_named():
    answer = {"gap_id": "C9.G9", "status": "tested", "tests": [7], "reason": ""}
    errors = validate_hypothesis_response(_hypothesis(prior_gaps=[answer]), open_gap_ids=("C1.G1",))
    assert any("'C9.G9', which isn't a gap from the prior review" in e for e in errors)


def test_a_tested_gap_cites_tests_and_any_other_status_gives_a_reason():
    tested_without_tests = {"gap_id": "C1.G1", "status": "tested", "tests": [], "reason": ""}
    errors = validate_hypothesis_response(_hypothesis(prior_gaps=[tested_without_tests]), open_gap_ids=("C1.G1",))
    assert any("says tested, so 'tests' must cite" in e for e in errors)

    untestable_without_reason = {"gap_id": "C1.G1", "status": "untestable", "tests": [], "reason": ""}
    errors = validate_hypothesis_response(_hypothesis(prior_gaps=[untestable_without_reason]), open_gap_ids=("C1.G1",))
    assert any("prior_gaps[0].reason must not be empty" in e for e in errors)


def test_observation_ids_are_stamped_per_checkpoint():
    data = _hypothesis(observations=[dict(_OBSERVATION), dict(_OBSERVATION)])
    stamp_observation_ids(2, data)
    assert [o["id"] for o in data["observations"]] == ["C2.O1", "C2.O2"]


def test_gap_ids_are_stamped_per_checkpoint():
    review = {"gaps": [{"gap": "first gap"}, {"gap": "second gap", "blocks_verdict": True}]}
    stamp_gap_ids(3, review)
    assert [g["id"] for g in review["gaps"]] == ["C3.G1", "C3.G2"]


def test_the_next_checkpoint_is_shown_the_earlier_observations_with_their_ids(monkeypatch):
    # A live run restated checkpoint 1's bug under a new id, because the hypothesis
    # call was never shown what earlier checkpoints had found.
    import itertools

    import engine.loop as loop
    from engine.config import RunConfig
    from engine.tests.test_prompt_cache_prefix import _ADAPTER, _HAPPY_DAY

    seen = []

    def fake_casting(*a, **kw):
        return {"give_up": False, "reasoning": "r", "candidate_tests": [{"linked_hypothesis": "", "predicted_outcome": "x"}]}

    def fake_hypothesis(*a, earlier_observations=None, **kw):
        seen.append([o["id"] for o in earlier_observations or []])
        return _hypothesis(observations=[dict(_OBSERVATION)])

    def fake_skeptic(*a, **kw):
        return {"verdict": "weak", "verdict_reason": "r", "observation_checks": [], "coverage": {"material": True, "untouched": [], "note": "c"}, "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": False, "kind": "other", "about": []}], "prior_gaps_check": []}

    monkeypatch.setattr(loop, "get_casting_round", fake_casting)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", fake_skeptic)
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    loop.run_checkpoint_loop(
        client=None, adapter=_ADAPTER, run_config=RunConfig(max_checkpoints=3),
        happy_day_example=_HAPPY_DAY, test_counter=itertools.count(1),
    )
    assert seen == [[], ["C1.O1"], ["C1.O1", "C2.O1"]]



# ---- the testing story (issue #265) -----------------------------------------------------------

def _story(**changes):
    return {"areas": _HYPOTHESIS["areas"], "obstacles": _HYPOTHESIS["obstacles"], **changes}


def _with_area(**changes):
    return _story(areas=[{**_HYPOTHESIS["areas"][0], **changes}])


def test_the_testing_story_is_its_own_call_and_needs_at_least_one_area():
    # #271: inside the hypothesis the answer grew too big and broke too often.
    assert TESTING_STORY_TOOL["input_schema"]["required"] == ["areas", "obstacles"]
    assert "areas" not in HYPOTHESIS_TOOL["input_schema"]["properties"]
    assert validate_testing_story(_story()) == []
    assert any("'areas' must be a non-empty list" in e for e in validate_testing_story(_story(areas=[])))


def test_an_areas_estimates_come_from_fixed_scales_and_it_cites_its_tests():
    errors = validate_testing_story(_with_area(coverage="thoroughly", quality="good", confidence="sure", tests=[]))
    assert any("areas[0].coverage must be one of can_it_work, common_and_critical, deep" in e for e in errors)
    assert any("areas[0].quality must be one of no_problems_seen_yet, concerns, problems_found" in e for e in errors)
    assert any("areas[0].confidence must be one of high, medium, low" in e for e in errors)
    assert any("areas[0].tests must cite the test numbers behind it" in e for e in errors)
    assert validate_testing_story(_with_area(not_tested="")) == []      # nothing left is fine


def test_the_story_says_what_coverage_is_of_how_a_problem_would_show_and_what_got_in_the_way():
    # #271: after Bolton's three strands and Bach's dashboard.
    errors = validate_testing_story(_with_area(coverage_of="", oracle=""))
    assert "areas[0].coverage_of must not be empty" in errors and "areas[0].oracle must not be empty" in errors
    assert "missing required field 'obstacles'" in validate_testing_story({"areas": _HYPOTHESIS["areas"]})
    assert validate_testing_story(_story(obstacles=[])) == []     # nothing in the way is fine
    assert "obstacles[0].obstacle must not be empty" in validate_testing_story(
        _story(obstacles=[{"obstacle": "", "would_help": ""}]))


def test_the_skeptic_is_told_to_debrief_the_testing_story():
    from engine.tools import SKEPTIC_SYSTEM_PROMPT
    for phrase in ("tells its testing story", '"how do you know?"', "Distrust a clean story",
                   "Coverage is only ever of something", "'previous_story'"):
        assert phrase in SKEPTIC_SYSTEM_PROMPT, phrase


def test_the_skeptic_receives_the_story_and_the_previous_one():
    # #271: the story was left off the Skeptic's evidence, so it was asked to question
    # something it never saw.
    import json
    from engine import loop
    from engine.config import RunConfig
    sent = {}

    def fake_call(client, **kw):
        sent.update(json.loads(kw["user_message"]))
        return {"verdict": "strong_enough", "verdict_reason": "r", "observation_checks": [], "gaps": [],
                "coverage": {"material": False, "untouched": [], "note": "n"}, "prior_gaps_check": []}

    original = loop.call_tool_with_retry
    loop.call_tool_with_retry = fake_call
    try:
        loop.get_skeptic_review(None, RunConfig(), _HYPOTHESIS, previous_story=[{"area": "earlier"}])
    finally:
        loop.call_tool_with_retry = original
    assert sent["areas"] == _HYPOTHESIS["areas"] and sent["obstacles"] == _HYPOTHESIS["obstacles"]
    assert sent["previous_story"] == [{"area": "earlier"}]



def test_the_loop_asks_for_the_story_and_merges_it_into_the_hypothesis(monkeypatch):
    # #271: the story comes from its own call, and the Skeptic, the report and the
    # summary find it on the hypothesis as before.
    import itertools
    from engine import loop
    from engine.config import RunConfig
    seen = {}
    monkeypatch.setattr(loop, "get_casting_round", lambda *a, **k: {"give_up": True, "reasoning": "r", "candidate_tests": []})
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", lambda *a, **k: {
        "summary": "s", "behaviors": [], "observations": [], "untested": [], "prior_gaps": []})
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": _HYPOTHESIS["areas"], "obstacles": []})

    def skeptic(client, run_config, hypothesis, *a, **k):
        seen["areas"] = hypothesis.get("areas")
        return {"verdict": "strong_enough", "verdict_reason": "r", "observation_checks": [], "gaps": [],
                "coverage": {"material": False, "untouched": [], "note": "n"}, "prior_gaps_check": []}
    monkeypatch.setattr(loop, "get_skeptic_review", skeptic)
    adapter = type("A", (), {"casting_tool_schema": {}, "redact_history_for_model": None})()
    _, checkpoints, _ = loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=1), {}, itertools.count(1))
    assert seen["areas"] == _HYPOTHESIS["areas"] and checkpoints[0]["hypothesis"]["areas"] == _HYPOTHESIS["areas"]
