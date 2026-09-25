"""The Skeptic's structured review (issue #41): the verdict has to follow from the
objections raised, every observation gets exactly one check, prior gaps are
answered by id, and a disputed kind is lowered to the more cautious one. No LLM
calls."""

import copy

from engine.tools import SKEPTIC_TOOL, reconcile_kinds, validate_skeptic_response

_OBSERVATIONS = [{"id": "C1.O1", "kind": "bug"}, {"id": "C1.O2", "kind": "finding"}]

_CHECK = {"observation_id": "C1.O1", "discriminates_from_rival": True, "rival_is_genuine": True,
          "kind": "bug", "note": "Two clients would tell the rival apart."}

_STRONG = {
    "verdict": "strong_enough",
    "verdict_reason": "The race is shown against its rival and coverage is broad enough.",
    "observation_checks": [_CHECK, {**_CHECK, "observation_id": "C1.O2", "kind": "finding"}],
    "coverage": {"material": False, "untouched": ["Window reset timing"], "note": "A corner, not most of the API."},
    "gaps": [{"gap": "Window reset untested", "next_test": "Exhaust, wait 60s, send one", "blocks_verdict": False, "about": []}],
    "prior_gaps_check": [],
}


def _review(**changes):
    data = copy.deepcopy(_STRONG)
    data.update(changes)
    return data


def _errors(data, **kw):
    kw.setdefault("observations", _OBSERVATIONS)
    return validate_skeptic_response(data, **kw)


def test_a_complete_strong_enough_review_passes():
    assert _errors(_review()) == []


def test_every_top_level_field_is_required():
    for key in SKEPTIC_TOOL["input_schema"]["required"]:
        data = _review()
        del data[key]
        assert f"missing required field '{key}'" in _errors(data)


def test_weak_needs_at_least_one_objection():
    errors = _errors(_review(verdict="weak"))
    assert any("'weak' but no objection was raised" in e for e in errors)


def test_each_kind_of_objection_makes_weak_valid():
    not_discriminating = _review(verdict="weak", observation_checks=[
        {**_CHECK, "discriminates_from_rival": False}, {**_CHECK, "observation_id": "C1.O2", "kind": "finding"}])
    material = _review(verdict="weak", coverage={"material": True, "untouched": [], "note": "Most paths untested."})
    blocking = _review(verdict="weak", gaps=[{**_STRONG["gaps"][0], "blocks_verdict": True}])
    rejected_prior = _review(verdict="weak", prior_gaps_check=[{"gap_id": "C0.G1", "accepted": False, "note": "Vague."}])
    for data, kw in ((not_discriminating, {}), (material, {}), (blocking, {}), (rejected_prior, {"open_gap_ids": ("C0.G1",)})):
        assert _errors(data, **kw) == []


def test_strong_enough_with_an_objection_is_rejected():
    data = _review(coverage={"material": True, "untouched": [], "note": "Most paths untested."})
    assert any("'strong_enough' but 1 objection(s)" in e for e in _errors(data))


def test_every_observation_needs_exactly_one_check():
    missing = _review(observation_checks=[_CHECK])
    assert any("no entry for C1.O2" in e for e in _errors(missing))

    twice = _review(observation_checks=[_CHECK, _CHECK, {**_CHECK, "observation_id": "C1.O2", "kind": "finding"}])
    assert any("more than one entry for C1.O1" in e for e in _errors(twice))

    unknown = _review(observation_checks=_STRONG["observation_checks"] + [{**_CHECK, "observation_id": "C9.O9"}])
    assert any("'C9.O9', which isn't in the hypothesis" in e for e in _errors(unknown))


def test_a_gap_can_only_be_about_observations_in_the_hypothesis():
    data = _review(gaps=[{**_STRONG["gaps"][0], "about": ["C9.O9"]}])
    assert any("about names C9.O9" in e for e in _errors(data))


def test_every_prior_gap_is_checked_once():
    errors = _errors(_review(), open_gap_ids=("C0.G1",))
    assert any("'prior_gaps_check' has no entry for C0.G1" in e for e in errors)


def test_a_slightly_long_reason_passes_but_a_paragraph_does_not():
    assert _errors(_review(verdict_reason="word " * 33)) == []
    assert any("far too long" in e for e in _errors(_review(verdict_reason="word " * 61)))


def test_the_skeptic_can_lower_a_kind_and_the_driver_s_is_kept():
    hypothesis = {"observations": [{"id": "C1.O1", "kind": "bug"}, {"id": "C1.O2", "kind": "anomaly"}]}
    review = {"observation_checks": [
        {"observation_id": "C1.O1", "kind": "anomaly"},
        {"observation_id": "C1.O2", "kind": "anomaly"},
    ]}
    reconcile_kinds(hypothesis, review)
    assert hypothesis["observations"][0] == {"id": "C1.O1", "kind": "anomaly", "driver_kind": "bug"}
    assert hypothesis["observations"][1] == {"id": "C1.O2", "kind": "anomaly"}


def test_the_skeptic_cannot_raise_a_kind():
    hypothesis = {"observations": [{"id": "C1.O1", "kind": "finding"}]}
    reconcile_kinds(hypothesis, {"observation_checks": [{"observation_id": "C1.O1", "kind": "bug"}]})
    assert hypothesis["observations"][0] == {"id": "C1.O1", "kind": "finding"}
