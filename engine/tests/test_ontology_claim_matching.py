"""Regression test for the ontology layer's claim-matching gap (see the former
"Known gap" section of docs/ontology-todo.md): layer 4
(engine.ontology.oracle_creator) used to match a Driver's test result back to
an oracle claim by exact string equality on the claim's free text - text the
Driver's own paraphrased linked_hypothesis was never guaranteed to match, even
when it was clearly testing the same claim, so a real Driver run's results
never actually reprioritized anything. Fixed by giving every domain claim a
stable id and matching on that id instead of on prose."""

from engine.ontology import feedback, oracle_creator


def test_domain_claim_ids_are_stable_and_unique():
    claims = oracle_creator.load_domain_claims("token_purchase")
    assert claims, "expected token_purchase's oracle_library.json to have claims"
    ids = [c["id"] for c in claims]
    assert len(ids) == len(set(ids))
    assert ids == [c["id"] for c in oracle_creator.load_domain_claims("token_purchase")]


def test_score_grounded_claim_matches_by_id_even_if_the_result_paraphrases_the_claim():
    claim = {"id": "claim:data:01", "claim": "Original claim wording.", "rationale": "r"}
    # Simulates the Driver's own free-text linked_hypothesis: worded
    # differently from the oracle's claim text, tied back only by id.
    context = {"test_results": [{"claim_id": "claim:data:01", "verified": False, "timestamp": "2026-08-26"}]}
    score, status = oracle_creator.score_grounded_claim(claim, context)
    assert status == "refuted"
    assert score == oracle_creator.GROUNDED_BASE_SCORE + oracle_creator.REFUTED_BONUS


def test_score_grounded_claim_stays_untested_for_a_different_claim_id():
    claim = {"id": "claim:data:01", "claim": "x", "rationale": "r"}
    context = {"test_results": [{"claim_id": "claim:data:02", "verified": True, "timestamp": "t"}]}
    score, status = oracle_creator.score_grounded_claim(claim, context)
    assert status == "untested"


def test_feedback_only_keeps_results_tied_to_an_oracle_claim_id():
    output = {
        "casting_log": [
            {"linked_hypothesis": "some theory", "oracle_claim_id": "claim:data:01", "prediction_matched": True},
            {"linked_hypothesis": "", "oracle_claim_id": "", "prediction_matched": True},  # pure edge-case probe
            {"linked_hypothesis": "an unlinked theory", "prediction_matched": False},  # not tied to any oracle claim
        ],
    }
    results, dropped = feedback.extract_results(output, {"claim:data:01"})
    assert dropped == []
    assert len(results) == 1
    assert results[0]["claim_id"] == "claim:data:01"
    assert results[0]["verified"] is True


def test_feedback_merge_overwrites_by_claim_id_not_by_text():
    context = {"test_results": [{"claim_id": "claim:data:01", "verified": False, "timestamp": "day1"}]}
    new_results = [{"claim_id": "claim:data:01", "verified": True, "timestamp": "day2"}]
    merged = feedback.merge_results(context, new_results)
    assert merged["test_results"] == [{"claim_id": "claim:data:01", "verified": True, "timestamp": "day2"}]


def test_end_to_end_ranking_actually_shifts_once_feedback_is_merged_in():
    """The exact scenario docs/ontology-todo.md documented as broken: a real
    Driver result should now actually change a claim's score on the next
    oracle_creator run, instead of the ranking staying frozen."""
    target = oracle_creator.load_domain_claims("token_purchase")[0]

    baseline_score, baseline_status = oracle_creator.score_grounded_claim(target, {"test_results": []})
    assert baseline_status == "untested"

    output = {"casting_log": [{"oracle_claim_id": target["id"], "prediction_matched": False}]}
    context = feedback.merge_results(
        {"test_results": [], "jira_entries": [], "risk_assessments": []},
        feedback.extract_results(output, feedback.known_ids("token_purchase"))[0],
    )

    new_score, new_status = oracle_creator.score_grounded_claim(target, context)
    assert new_status == "refuted"
    assert new_score > baseline_score


def test_feedback_drops_ids_that_arent_ranked_ideas():
    # Issue #107: with the oracle off, the Driver cited ids it made from gap ids.
    real = oracle_creator.load_domain_claims("token_purchase")[0]["id"]
    output = {"casting_log": [
        {"oracle_claim_id": real, "prediction_matched": True},
        {"oracle_claim_id": "claim:data:C1.G1", "prediction_matched": False},
        {"oracle_claim_id": "heuristic:boundary_edges", "prediction_matched": True},
    ]}
    results, dropped = feedback.extract_results(output, feedback.known_ids("token_purchase"))
    assert [r["claim_id"] for r in results] == [real, "heuristic:boundary_edges"]
    assert dropped == ["claim:data:C1.G1"]


def test_feedback_records_discovered_screens_and_counts_reaches_across_runs():
    # Issue #157: screens beyond the map go into the context, 'seen once' until reached again.
    record = {"id": "d1", "signature": "/new|button:x|", "url": "http://x/new", "title": "New",
              "from_state": "st01", "via": "button:A", "path": [{"name": "A"}],
              "elements": [{"key": "button:x", "committing": False}], "controls_offered": 1}
    output = {"casting_log": [{"test_number": 4, "result": {"discovered": record}}, {"test_number": 5, "result": {}}]}
    found = feedback.extract_discoveries(output)
    assert [(d["id"], d["test_number"]) for d in found] == [("d1", 4)]
    context = feedback.merge_discoveries({}, found, run="run-1")
    assert context["discoveries"][0]["status"] == "seen once"
    context = feedback.merge_discoveries(context, found, run="run-2")
    d = context["discoveries"][0]
    assert (d["times_reached"], d["runs"], d["status"], d["first_seen"], d["last_seen"]) == (
        2, ["run-1", "run-2"], "reproduced", "run-1", "run-2")
