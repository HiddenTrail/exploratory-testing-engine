"""What the Driver promises in the debrief, the next round answers first (issue #352). No
model calls."""

import itertools
import json

from trailhound import loop, outcome, steering
from trailhound.config import RunConfig
from trailhound.report import _steering_line


def _thread(gid, outcome_, argument="next round I'll open the basket in a new tab"):
    return {"gap_id": gid, "outcome": outcome_, "answer": {"stance": "x", "argument": argument, "tests": []}}


def test_a_promise_is_a_change_of_approach_still_open_in_the_review():
    review = {"skeptic_review": {"gaps": [{"id": "C1.G1"}, {"id": "C1.G2"}, {"id": "C1.G4"}]}}
    debrief = [_thread("C1.G1", "new_approach"), _thread("C1.G2", "conceded"), _thread("C1.G3", "new_approach"),
               _thread("C1.G4", "open")]
    # C1.G3 isn't in the review any more (its claim is parked): no promise to keep.
    assert steering.promises(review, debrief) == [{"id": "C1.G1", "promise": "next round I'll open the basket in a new tab"}]
    # Found in review: the Skeptic said drop it, so it isn't forced first.
    dropped = [{**_thread("C1.G1", "new_approach"), "kind": "not_worth_continuing"}]
    assert steering.promises(review, dropped) == []
    assert steering.promises(review, None) == [] and steering.promises(None, debrief) == []


def test_the_driver_is_told_what_it_promised_comes_first():
    note = steering.answer_first(("C2.G1", "C2.G4"), 2, promised=("C2.G4",))
    assert note.startswith("First, the questions that block the verdict: C2.G1, and what you promised in the "
                           "debrief: C2.G4 (your words are in 'promises'). At least 2 test(s) must answer them, one "
                           "per question, starting from each question's next_test or your promise")
    only = steering.answer_first(("C2.G4",), 1, promised=("C2.G4",))
    assert only.startswith("First, what you promised in the debrief: C2.G4")
    [error] = steering.blocking_shortfall({"candidate_tests": []}, ("C2.G4",), 6, promised=("C2.G4",))
    assert error.startswith("1 question(s) from the last review come first (they block the verdict, or you promised "
                            "them in the debrief), and this round answers 0.")


def test_the_loop_holds_the_next_round_to_the_promise_and_records_it(monkeypatch, capsys):
    calls, gaps = [], {}

    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            calls.append(kw)
            n = len(calls)
            tests = [{"linked_hypothesis": "", "state": f"s{n}{i}", "predicted_outcome": "x"} for i in range(3)]
            answer = {"give_up": False, "reasoning": "r", "candidate_tests": tests}
            if n == 2:
                assert kw["validate_fn"](answer)[0].startswith("1 question(s) from the last review come first")
                answer["candidate_tests"][0].update(follows_up=gaps["promised"], rules_out_if="the basket would be empty")
            return answer
        if tool == "submit_checkpoint_hypothesis":
            return {"summary": "s", "prior_gaps": [], "observations": [
                {"kind": "anomaly", "continues": "", "claim": "c", "tests": [1], "violates": "", "reproduced": "once",
                 "rival": "r", "rival_ruled_out": False, "severity": "low"}]}
        if tool == "submit_debrief_answers":
            gid = json.loads(kw["user_message"])["skeptic_questions"][0]["id"]
            gaps.setdefault("promised", gid)
            gaps["last"] = gid
            return {"answers": [{"gap_id": gid, "stance": "change_approach", "tests": [],
                                 "argument": "next round I'll open the basket in a new tab"}]}
        if tool == "submit_reconsideration":
            gid = gaps["last"]
            return {"judgements": [{"gap_id": gid, "convinced": "partly", "why": "w"}], "revised_checks": [],
                    "verdict": "weak", "verdict_reason": "v"}
        oid = json.loads(kw["user_message"])["observations"][0]["id"]
        # Not blocking: before #352 nothing held the Driver to it.
        return {"verdict": "weak", "verdict_reason": "v", "coverage": {"material": False}, "prior_gaps_check": [],
                "observation_checks": [{"observation_id": oid, "discriminates_from_rival": False,
                                        "rival_is_genuine": True, "kind": "anomaly"}],
                "gaps": [{"gap": "never tried a new tab", "next_test": "t", "blocks_verdict": False,
                          "kind": "rival_not_tested", "about": [oid]}]}
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    monkeypatch.setattr(loop, "cited_evidence", lambda adapter, log, answers: {})
    adapter = type("A", (), {
        "casting_tool_schema": {"name": "submit_casting_round", "input_schema": {"properties": {
            "candidate_tests": {"type": "array", "items": {"properties": {}, "required": []}}}}},
        "redact_history_for_model": None, "describe_test_for_log": None, "describe_result_for_log": None,
        "casting_system_prompt": staticmethod(lambda budget, first: "cast"),
        "validate_casting_response": staticmethod(lambda data: []),
        "casting_max_tokens": staticmethod(lambda budget: 100), "api_schema_doc": "doc", "onboarding_extra": {},
        "execute_test": staticmethod(lambda test, n: outcome.attach(
            {"test_number": n, "prediction_matched": True}, outcome.Outcome(action_id=test["state"], effect=outcome.NONE))),
    })()
    log, checkpoints, _ = loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=2, lean=True,
                                                                            lean_with=frozenset({"debrief"})),
                                                   {}, itertools.count(1))
    promised = gaps["promised"]
    assert json.loads(calls[1]["user_message"])["answer_first"].startswith(
        f"First, what you promised in the debrief: {promised}")
    assert json.loads(calls[1]["user_message"])["promises"] == [
        {"id": promised, "promise": "next round I'll open the basket in a new tab"}]
    assert checkpoints[1]["promises"] == [{"id": promised, "promise": "next round I'll open the basket in a new tab",
                                           "kept": True}]
    assert checkpoints[1]["blocking"] == {"questions": [promised], "needed": 1, "answered": [promised]}
    assert f"debrief promises: kept {promised}; not kept none" in capsys.readouterr().out
    assert "Promised in the last debrief: kept " + promised + "." in _steering_line(checkpoints[1], 3)


def test_promises_and_blocking_questions_skip_the_follow_up_limit_only_up_to_half_the_round():
    # Found in review: with F1's 9 promises, every follow-up skipped the limit and the
    # oracle got nothing.
    first = tuple(f"C1.G{n}" for n in range(1, 8))
    tests = [{"follows_up": g, "rules_out_if": "r"} for g in first] + [{"oracle_claim_id": "oracle:a"}]
    kept, dropped = steering.limit(tests, cap=2, parked_ids=set(), blocking=first,
                                   exempt=steering.blocking_needed(first, 6))
    assert [t.get("follows_up") for t in kept] == ["C1.G1", "C1.G2", "C1.G3", "C1.G4", "C1.G5", None]
    assert len(dropped) == 2 and dropped[0]["errors"] == ["over the limit of 2 follow-up test(s) a round"]


def test_a_promised_test_says_what_would_settle_it():
    [error] = steering.rules_out_errors({"candidate_tests": [{"follows_up": "C1.G4"}]}, ("C1.G4",), ("C1.G4",))
    assert error.startswith("candidate_tests[0] answers C1.G4, which comes first because you promised it in the debrief")


def test_the_report_says_which_promises_werent_kept():
    entry = {"follow_ups": 1, "repeats": 0, "promises": [{"id": "C1.G1", "kept": True}, {"id": "C1.G4", "kept": False}]}
    assert "Promised in the last debrief: kept C1.G1; not kept C1.G4." in _steering_line(entry, 6)
