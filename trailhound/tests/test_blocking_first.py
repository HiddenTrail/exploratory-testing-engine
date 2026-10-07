"""A round answers the questions that block the verdict before it opens new claims
(issue #340). No model calls."""

from trailhound import steering


def _review(*gaps):
    return {"skeptic_review": {"gaps": [{"id": gid, "blocks_verdict": blocks, "about": ["C1.O1"]}
                                        for gid, blocks in gaps]}}


def _test(follows="", rules_out="", idea=""):
    return {"follows_up": follows, "rules_out_if": rules_out, "oracle_claim_id": idea}


def test_the_blocking_questions_are_the_last_reviews():
    assert steering.blocking_ids(_review(("C2.G1", True), ("C2.G2", False), ("C2.G3", True))) == ("C2.G1", "C2.G3")
    assert steering.blocking_ids(None) == ()


def test_one_test_per_blocking_question_up_to_half_the_round():
    assert steering.blocking_needed(("a",), 6) == 1
    assert steering.blocking_needed(("a", "b", "c", "d", "e"), 6) == 3
    assert steering.blocking_needed(("a", "b"), 1) == 1
    assert steering.blocking_needed((), 6) == 0


def test_a_round_that_leaves_blocking_questions_open_is_sent_back():
    blocking = ("C2.G1", "C2.G3")
    [error] = steering.blocking_errors({"candidate_tests": [_test(idea="oracle:a"), _test(follows="C2.G1",
                                                                                         rules_out="r")]},
                                       blocking, 6)
    assert error.startswith("2 question(s) from the last review block the verdict, and this round answers 1. "
                            "Answer at least 2 of them first")
    assert error.endswith("Not answered yet: C2.G3.")
    answered = {"candidate_tests": [_test(follows="C2.G1", rules_out="r"), _test(follows="C2.G3", rules_out="r")]}
    assert steering.blocking_errors(answered, blocking, 6) == []
    assert steering.blocking_errors({"candidate_tests": []}, (), 6) == []           # nothing blocks: no rule


def test_a_test_answering_a_blocking_question_says_what_would_rule_the_rival_out():
    [error] = steering.blocking_errors({"candidate_tests": [_test(follows="C2.G1")]}, ("C2.G1",), 6)
    assert error.startswith("candidate_tests[0] answers C2.G1, which blocks the verdict: say in 'rules_out_if'")


def test_giving_up_isnt_held_to_the_count():
    assert steering.blocking_errors({"give_up": True, "candidate_tests": []}, ("C2.G1",), 6) == []


def test_a_blocking_questions_first_test_doesnt_count_against_the_follow_up_cap():
    tests = [_test(follows="C2.G1", rules_out="r"), _test(follows="C2.G1", rules_out="r"),
             _test(follows="C1.O1"), _test(follows="C1.O2"), _test(idea="oracle:a")]
    kept, dropped = steering.limit(tests, cap=2, parked_ids=set(), blocking=("C2.G1",))
    # The first answer to C2.G1 is outside the cap; the second counts, so C1.O2 is over it.
    assert kept == tests[:3] + tests[4:]
    assert dropped == [{"test": tests[3], "errors": ["over the limit of 2 follow-up test(s) a round"]}]
    # A parked claim's question gets nothing, blocking or not.
    kept, dropped = steering.limit([_test(follows="C2.G1", rules_out="r")], 2, {"C2.G1"}, blocking=("C2.G1",))
    assert kept == [] and "parked" in dropped[0]["errors"][0]


def test_the_driver_is_told_which_questions_come_first_and_gets_the_field():
    note = steering.casting_note(2, False, None, ("C2.G1", "C2.G3"), 2)
    assert note.startswith("\n\nFirst, the questions that block the verdict: C2.G1, C2.G3. At least 2 test(s) must "
                           "answer them")
    assert "First, the questions" not in steering.casting_note(2, False)
    tool = steering.with_follow_up_field({"input_schema": {"properties": {"candidate_tests": {"items": {
        "properties": {}}}}}})
    assert "rules_out_if" in tool["input_schema"]["properties"]["candidate_tests"]["items"]["properties"]
