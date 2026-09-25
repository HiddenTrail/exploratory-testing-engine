"""The run's final output (issue #41): the engine, not a model, decides each
observation's status, and the bug-report call writes exactly one report per bug.
No LLM calls."""

from engine.tools import final_observations, validate_bug_reports

_HYPOTHESIS = {"observations": [
    {"id": "C2.O1", "kind": "bug", "claim": "race", "severity": "high"},
    {"id": "C2.O2", "kind": "anomaly", "claim": "priority", "severity": "medium"},
    {"id": "C2.O3", "kind": "finding", "claim": "odd value", "severity": "low"},
]}


def _review(**changes):
    review = {
        "observation_checks": [
            {"observation_id": "C2.O1", "discriminates_from_rival": True, "note": "two clients ruled it out"},
            {"observation_id": "C2.O2", "discriminates_from_rival": False, "note": "priority exemption not ruled out"},
            {"observation_id": "C2.O3", "discriminates_from_rival": True, "note": "fine"},
        ],
        "gaps": [],
    }
    review.update(changes)
    return review


def _statuses(review):
    return {o["id"]: o["status"] for o in final_observations(_HYPOTHESIS, review)}


def test_corroborated_needs_discriminating_evidence():
    assert _statuses(_review()) == {"C2.O1": "corroborated", "C2.O2": "inconclusive", "C2.O3": "corroborated"}


def test_a_blocking_gap_about_an_observation_makes_it_inconclusive():
    gaps = [{"gap": "g", "blocks_verdict": True, "about": ["C2.O1"]},
            {"gap": "h", "blocks_verdict": False, "about": ["C2.O3"]}]
    assert _statuses(_review(gaps=gaps)) == {"C2.O1": "inconclusive", "C2.O2": "inconclusive", "C2.O3": "corroborated"}


def test_the_skeptic_s_note_travels_with_the_observation():
    concluded = final_observations(_HYPOTHESIS, _review())
    assert concluded[1]["skeptic_note"] == "priority exemption not ruled out"
    assert concluded[1]["kind"] == "anomaly"


_REPORT = {
    "observation_id": "C2.O1", "title": "Concurrent requests exceed the limit",
    "description": "Twenty concurrent requests for one client are all accepted.",
    "steps_to_reproduce": ["Send 20 concurrent POST /submit with client_id=a"],
    "expected_behavior": "5 accepted, 15 rate limited", "actual_behavior": "20 accepted",
    "caveats": "Not tried across two server processes.",
}


def test_one_report_per_bug_passes():
    assert validate_bug_reports({"bugs": [_REPORT]}, bug_ids=("C2.O1",)) == []


def test_a_missing_or_extra_report_is_rejected():
    assert any("no entry for C2.O4" in e
               for e in validate_bug_reports({"bugs": [_REPORT]}, bug_ids=("C2.O1", "C2.O4")))
    extra = {**_REPORT, "observation_id": "C2.O2"}
    assert any("'C2.O2', which isn't a bug in the evidence" in e
               for e in validate_bug_reports({"bugs": [_REPORT, extra]}, bug_ids=("C2.O1",)))


def test_a_report_needs_steps_and_short_fields():
    no_steps = {**_REPORT, "steps_to_reproduce": []}
    assert any("steps_to_reproduce must be a non-empty list" in e
               for e in validate_bug_reports({"bugs": [no_steps]}, bug_ids=("C2.O1",)))
    long_title = {**_REPORT, "title": "word " * 31}
    assert any("title is far too long" in e
               for e in validate_bug_reports({"bugs": [long_title]}, bug_ids=("C2.O1",)))
