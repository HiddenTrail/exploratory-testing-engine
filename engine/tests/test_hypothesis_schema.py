"""The Driver's structured hypothesis (issue #41): the validator's rules for the
three observation kinds, ids and prior gaps, the word limits, and the ids the
engine stamps on. No LLM calls."""

import copy

from engine.tools import (
    HYPOTHESIS_TOOL,
    stamp_gap_ids,
    stamp_observation_ids,
    validate_hypothesis_response,
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


def test_a_bug_must_say_which_fact_it_violates():
    errors = validate_hypothesis_response(_with_observation(violates=""))
    assert any("'violates' must say which known fact" in e for e in errors)


def test_a_bug_must_reproduce_consistently():
    for reproduced in ("once", "inconsistent"):
        errors = validate_hypothesis_response(_with_observation(reproduced=reproduced))
        assert any("must reproduce consistently" in e for e in errors), reproduced


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


def test_gap_ids_are_stamped_and_plain_string_gaps_become_objects():
    review = {"gaps": ["first gap", {"gap": "second gap", "blocks_verdict": True}]}
    stamp_gap_ids(3, review)
    assert review["gaps"] == [
        {"gap": "first gap", "id": "C3.G1"},
        {"gap": "second gap", "blocks_verdict": True, "id": "C3.G2"},
    ]


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
        return {"verdict": "weak", "gaps": ["g"], "coverage_breadth": {"material": False, "note": "c"},
                "anomaly_checks": [], "recommended_next_tests": ["t"], "prior_critique_addressed": "n/a"}

    monkeypatch.setattr(loop, "get_casting_round", fake_casting)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", fake_hypothesis)
    monkeypatch.setattr(loop, "get_skeptic_review", fake_skeptic)
    loop.run_checkpoint_loop(
        client=None, adapter=_ADAPTER, run_config=RunConfig(max_checkpoints=3),
        happy_day_example=_HAPPY_DAY, test_counter=itertools.count(1),
    )
    assert seen == [[], ["C1.O1"], ["C1.O1", "C2.O1"]]
