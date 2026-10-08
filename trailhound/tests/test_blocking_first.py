"""A round answers the questions that block the verdict before it opens new claims
(issue #340). No model calls."""

import itertools
import json

from trailhound import loop, outcome, steering
from trailhound.config import RunConfig
from trailhound.tools import salvage_casting


def _review(*gaps):
    return {"skeptic_review": {"gaps": [{"id": gid, "blocks_verdict": blocks, "about": ["C1.O1"], **extra}
                                        for gid, blocks, extra in gaps]}}


def _test(follows="", rules_out="", idea=""):
    return {"follows_up": follows, "rules_out_if": rules_out, "oracle_claim_id": idea}


def test_the_blocking_questions_are_the_last_reviews_open_ones_about_a_claim():
    review = _review(("C2.G1", True, {}), ("C2.G2", False, {}), ("C2.G3", True, {}),
                     ("C2.G4", True, {"outcome": "conceded"}), ("C2.G5", True, {"outcome": "settled"}),
                     ("C2.G6", True, {"kind": "not_worth_continuing"}), ("C2.G7", True, {"about": []}))
    assert steering.blocking_ids(review) == ("C2.G1", "C2.G3")
    assert steering.blocking_ids(None) == ()


def test_one_test_per_blocking_question_up_to_half_the_round():
    assert steering.blocking_needed(("a",), 6) == 1
    assert steering.blocking_needed(("a", "b", "c", "d", "e"), 6) == 3
    assert steering.blocking_needed(("a", "b"), 1) == 1
    assert steering.blocking_needed((), 6) == 0


def test_too_few_answers_are_sent_back_once_only():
    blocking = ("C2.G1", "C2.G3")
    round_ = {"candidate_tests": [_test(idea="oracle:a"), _test(follows="C2.G1", rules_out="r")]}
    [error] = steering.blocking_shortfall(round_, blocking, 6)
    assert error.startswith("2 question(s) from the last review block the verdict, and this round answers 1. "
                            "Answer at least 2 of them")
    assert "Not answered yet: C2.G3." in error and error.endswith("this is asked once.")
    check = steering.once(lambda data: steering.blocking_shortfall(data, blocking, 6))
    assert check(round_) == [error] and check(round_) == []        # the second time it's accepted
    answered = {"candidate_tests": [_test(follows="C2.G1", rules_out="r"), _test(follows="C2.G3", rules_out="r")]}
    assert steering.blocking_shortfall(answered, blocking, 6) == []
    assert steering.blocking_shortfall({"give_up": True, "candidate_tests": []}, blocking, 6) == []


def test_a_test_answering_one_says_what_would_settle_it_and_odd_values_dont_crash():
    [error] = steering.rules_out_errors({"candidate_tests": [_test(follows="C2.G1")]}, ("C2.G1",))
    assert error.startswith("candidate_tests[0] answers C2.G1, which comes first because it blocks the verdict: say "
                            "in 'rules_out_if'")
    # Found in review: a list here crashed the validation instead of being sent back.
    odd = {"candidate_tests": [{"follows_up": ["C2.G1", "C2.G3"]}, {"follows_up": "C2.G1", "rules_out_if": ["x"]}]}
    assert len(steering.rules_out_errors(odd, ("C2.G1",))) == 1
    assert steering.blocking_answered(steering._tests(odd), ("C2.G1",)) == ["C2.G1"]
    assert steering.follow_up_errors(odd, {"C2.G1"})[0].startswith("candidate_tests[0].follows_up must be a string")


def test_the_last_attempt_salvage_still_keeps_a_round_that_answers_them():
    # Found in review: with the count in the per-test check, salvage dropped every test.
    blocking = ("C1.G1", "C1.G2")
    per_test = lambda data: (["bad state"] if any(t.get("state") == "bad" for t in data["candidate_tests"]) else []) \
        + steering.rules_out_errors(data, blocking)
    answer = {"give_up": False, "reasoning": "r", "candidate_tests": [
        {**_test(follows="C1.G1", rules_out="r")}, {**_test(follows="C1.G2", rules_out="r")},
        {**_test(idea="oracle:a")}, {**_test(idea="oracle:b"), "state": "bad"}]}
    kept = salvage_casting(per_test)(answer)
    assert len(kept["candidate_tests"]) == 3 and kept["dropped_tests"][0]["errors"] == ["bad state"]


def test_the_loop_asks_once_then_runs_the_round_and_records_what_it_answered(monkeypatch, capsys):
    calls = []

    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            calls.append(kw)
            n = len(calls)
            tests = [{"linked_hypothesis": "", "state": f"s{n}{i}", "predicted_outcome": "x"} for i in range(3)]
            answer = {"give_up": False, "reasoning": "r", "candidate_tests": tests}
            if n == 2:
                # The Driver ignores the rule twice: sent back once, then the round is taken.
                assert kw["validate_fn"](answer)[0].startswith("1 question(s) from the last review block")
                assert kw["validate_fn"](answer) == []
                answer["candidate_tests"][0].update(follows_up="C1.G1", rules_out_if="the rival would show y")
            return answer
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
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
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
    log, checkpoints, _ = loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=2, lean=True), {},
                                                   itertools.count(1))
    assert json.loads(calls[1]["user_message"])["answer_first"].startswith(
        "First, the questions that block the verdict: C1.G1.")
    assert "oracle_ranked" not in calls[1]["system"]                                # no oracle in this run
    # #376: the system prompt stays the same from round to round, so later rounds read the cache.
    assert "C1.G1" not in calls[1]["system"]
    assert checkpoints[1]["blocking"] == {"questions": ["C1.G1"], "needed": 1, "answered": ["C1.G1"]}
    answering = next(e for e in log if e["checkpoint"] == 2 and e.get("follows_up"))
    assert answering["follows_up"] == "C1.G1" and answering["rules_out_if"] == "the rival would show y"
    assert "blocking: needed 1 of C1.G1; answered C1.G1" in capsys.readouterr().out


def test_a_blocking_questions_first_test_doesnt_count_against_the_follow_up_cap():
    tests = [_test(follows="C2.G1", rules_out="r"), _test(follows="C2.G1", rules_out="r"),
             _test(follows="C1.O1"), _test(follows="C1.O2"), _test(idea="oracle:a")]
    kept, dropped = steering.limit(tests, cap=2, parked_ids=set(), blocking=("C2.G1",))
    # The first answer to C2.G1 is outside the cap; the second counts, so C1.O2 is over it.
    assert kept == tests[:3] + tests[4:]
    assert dropped == [{"test": tests[3], "errors": ["over the limit of 2 follow-up test(s) a round"]}]
    kept, dropped = steering.limit([_test(follows="C2.G1", rules_out="r")], 2, {"C2.G1"}, blocking=("C2.G1",))
    assert kept == [] and "parked" in dropped[0]["errors"][0]


def test_the_driver_is_told_which_questions_come_first_and_gets_the_field():
    note = steering.answer_first(("C2.G1", "C2.G3"), 2)
    assert note.startswith("First, the questions that block the verdict: C2.G1, C2.G3. At least 2 test(s) must "
                           "answer them, one per question, starting from each question's next_test")
    assert note.endswith("The first test on each, up to 2, doesn't count against the follow-up limit.")
    assert steering.answer_first((), 0) == ""
    rules = steering.casting_note(2, False, 3)
    assert "When your evidence has 'answer_first', do that first" in rules
    assert "Apart from any tests 'answer_first' asks for, most tests should check an idea" in rules
    tool = steering.with_follow_up_field({"input_schema": {"properties": {"candidate_tests": {"items": {
        "properties": {}}}}}})
    assert "rules_out_if" in tool["input_schema"]["properties"]["candidate_tests"]["items"]["properties"]

def test_the_casting_system_prompt_is_the_same_in_every_later_round(monkeypatch):
    # #376: with the blocking questions in the system prompt, every round wrote the cache
    # again (0 read in every casting call of runs/exp341/A1, about $0.20 a lean run).
    calls = []

    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            calls.append(kw)
            tests = [{"linked_hypothesis": "", "state": f"s{len(calls)}{i}", "predicted_outcome": "x"} for i in range(2)]
            answer = {"give_up": False, "reasoning": "r", "candidate_tests": tests}
            first = json.loads(kw["user_message"]).get("answer_first")
            if first:
                gid = first.split(": ")[1].split(".")[0] + "." + first.split(": ")[1].split(".")[1]
                answer["candidate_tests"][0].update(follows_up=gid, rules_out_if="r")
            return answer
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
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    adapter = type("A", (), {
        "casting_tool_schema": {"name": "submit_casting_round", "input_schema": {"properties": {
            "candidate_tests": {"type": "array", "items": {"properties": {}, "required": []}}}}},
        "redact_history_for_model": None, "describe_test_for_log": None, "describe_result_for_log": None,
        "casting_system_prompt": staticmethod(lambda budget, first: f"cast {budget} {first}"),
        "validate_casting_response": staticmethod(lambda data: []),
        "casting_max_tokens": staticmethod(lambda budget: 100), "api_schema_doc": "doc", "onboarding_extra": {},
        "execute_test": staticmethod(lambda test, n: outcome.attach(
            {"test_number": n, "prediction_matched": True}, outcome.Outcome(action_id=test["state"], effect=outcome.NONE))),
    })()
    loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=3, lean=True), {}, itertools.count(1))
    later = [json.loads(c["user_message"])["answer_first"] for c in calls[1:]]
    assert later[0].startswith("First, the questions that block the verdict: C1.G1")
    assert later[1].startswith("First, the questions that block the verdict: C2.G1")
    assert calls[1]["system"] == calls[2]["system"]                  # byte for byte
