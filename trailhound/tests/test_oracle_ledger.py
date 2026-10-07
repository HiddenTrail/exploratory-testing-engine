"""The Driver tests from the oracle, and every idea and every error gets an answer
(issue #312). Pure functions, then a checkpoint of the loop with a stubbed model."""

import itertools
import json

from trailhound import ledger, loop, outcome, steering
from trailhound.adapters.web_gui.adapter import problems_of
from trailhound.config import RunConfig
from trailhound.run_summary import summarize
from trailhound.tools import reconcile_kinds, validate_hypothesis_response

BASKET_400 = "request: PUT /api/BasketItems/# -> 400"


def test_a_tests_trusted_errors_become_tokens_the_same_problem_always_the_same():
    result = {"verdict": "sent", "signals": {
        "console_errors": ["Failed to load resource: the server responded with a status of 400 (Bad Request)",
                           "ERROR TypeError: Cannot read properties of undefined (reading 'x')\n    at y (z.js:1)"],
        "failed_requests": ["PUT http://127.0.0.1:3000/api/BasketItems/13 -> 400",
                            "GET http://127.0.0.1:3000/rest/basket/6?id=2 -> 0"]},
        "signals_weak": {"failed_requests": ["GET https://cdn.example/x.css -> 0"]}}
    assert problems_of(result) == [
        "console: Failed to load resource: the server responded with a status of 400 (Bad Request)",
        "console: ERROR TypeError: Cannot read properties of undefined (reading 'x')",
        BASKET_400, "request: GET /rest/basket/# -> 0"]
    assert problems_of({**result, "verdict": "not_actuated"}) == []
    assert problems_of({**result, "blocked_off_site": ["https://x"]}) == []


def _log(*tests):
    """casting_log entries: (test number, checkpoint, oracle id, problems)."""
    return [outcome.attach({"test_number": n, "checkpoint": c, "oracle_claim_id": idea},
                           outcome.Outcome(action_id=f"a{n}", effect=outcome.NONE, problems=list(problems)))
            for n, c, idea, problems in tests]


def test_the_ledger_knows_what_each_checkpoint_owes():
    log = _log((1, 1, "oracle:a", [BASKET_400]), (2, 1, "", ["console: E"]), (3, 2, "oracle:b", [BASKET_400]))
    problems = ledger.problems_by_test(log)
    assert problems == {1: [BASKET_400], 2: ["console: E"], 3: [BASKET_400]}
    assert ledger.ideas_checked(log, 1) == {"oracle:a": [1]} and ledger.ideas_checked(log, 2) == {"oracle:b": [3]}
    earlier = [{"hypothesis": {"observations": [{"tests": [2]}], "dismissed_errors": []}}]
    assert ledger.open_errors(problems, ledger.accounted(earlier, problems)) == {BASKET_400: [1, 3]}


def test_every_idea_and_every_error_needs_an_answer():
    kwargs = {"ideas_to_answer": ("oracle:a",), "errors_to_account": {BASKET_400: [1], "console: E": [2]},
              "test_problems": {1: [BASKET_400], 2: ["console: E"]}}
    nothing = {"summary": "s", "behaviors": [], "observations": [], "untested": [], "prior_gaps": []}
    errors = validate_hypothesis_response(nothing, **kwargs)
    assert "'ideas' doesn't answer oracle:a" in errors[0]
    assert errors[1].startswith("2 recorded error(s) have no answer") and "(tests 1)" in errors[1]
    answered = {**nothing,
                "ideas": [{"id": "oracle:a", "verdict": "broke", "tests": [1]}],
                "observations": [{"kind": "bug", "continues": "", "claim": "PUT /api/BasketItems -> 400", "tests": [1],
                                  "violates": "own requests succeed", "reproduced": "once", "mechanism": "m",
                                  "rival": "r", "rival_ruled_out": False, "why": "w", "severity": "medium"}],
                "dismissed_errors": [{"error": "console: E", "reason": "the same 400, as the console reports it"}]}
    assert validate_hypothesis_response(answered, **kwargs) == []
    wrong = {**answered, "ideas": [{"id": "oracle:z", "verdict": "maybe", "tests": [1]}]}
    assert any("oracle:z" in e for e in validate_hypothesis_response(wrong, **kwargs))
    assert any("verdict must be one of" in e for e in validate_hypothesis_response(wrong, **kwargs))


def test_a_test_with_an_error_isnt_normal_behaviour():
    hypothesis = {"behaviors": [{"claim": "the basket works", "tests": [1]}]}
    [error] = ledger.errors(hypothesis, test_problems={1: [BASKET_400]})
    assert error.startswith(f'behaviors[0] cites test 1, which recorded "{BASKET_400}"')


def test_a_bug_on_a_reproduced_error_stays_a_bug():
    # 2026-10-06: the basket's 400 in tests 17 and 19 was lowered because of the Driver's
    # own rival explanation, which wasn't ruled out.
    review = {"observation_checks": [{"observation_id": "C3.O1", "kind": "anomaly"},
                                     {"observation_id": "C3.O2", "kind": "anomaly"}]}
    hypothesis = {"observations": [{"id": "C3.O1", "kind": "bug", "tests": [17, 19]},
                                   {"id": "C3.O2", "kind": "bug", "tests": [20]}]}
    reconcile_kinds(hypothesis, review, {17: [BASKET_400], 19: [BASKET_400], 20: [BASKET_400]})
    kept, lowered = hypothesis["observations"]
    assert kept["kind"] == "bug" and "more than one test recorded" in kept["kept_as_bug_because"]
    assert lowered["kind"] == "anomaly" and lowered["driver_kind"] == "bug"    # one test isn't reproduction


def test_most_of_a_round_follows_the_oracle():
    tests = [{"n": 1, "oracle_claim_id": "oracle:a"}, {"n": 2}, {"n": 3}, {"n": 4, "follows_up": "C1.O1"}, {"n": 5}]
    kept, dropped = steering.limit(tests, cap=2, parked_ids=set(), free=2)
    assert [t["n"] for t in kept] == [1, 2, 3, 4]
    assert dropped[0]["errors"] == ["over the limit of 2 test(s) a round that check no oracle idea"]
    assert len(steering.limit(tests, 2, set())[0]) == 5                    # a run without an oracle: no limit
    assert steering.free_cap(10) == 3 and steering.free_cap(2) == 1
    [error] = steering.oracle_id_errors({"candidate_tests": [{"oracle_claim_id": "C1.G2"}, {"oracle_claim_id": ""}]},
                                        {"oracle:a"})
    assert "isn't an idea in 'oracle_ranked'" in error
    assert "At most 3 test(s) may check something no idea covers" in steering.casting_note(2, True, 3)
    assert "oracle_ranked" not in steering.casting_note(2, True)


def test_the_driver_is_told_what_is_left_of_the_oracle():
    ranked = [{"id": "oracle:a"}, {"id": "oracle:b"}, {"id": "oracle:c"}]
    log = [{"oracle_claim_id": "oracle:a"}]
    checkpoints = [{"hypothesis": {"ideas": [{"id": "oracle:a", "verdict": "broke", "tests": [1]}]}}]
    assert steering.oracle_progress(ranked, log, checkpoints) == {
        "not_checked_yet": ["oracle:b", "oracle:c"], "answered": [{"id": "oracle:a", "verdict": "broke"}]}


def test_the_summary_says_how_the_oracle_was_used_and_whether_every_error_was_answered():
    output = {"onboarding_extra": {"oracle_ranked": [{"id": "oracle:a"}, {"id": "oracle:b"}]},
              "casting_log": _log((1, 1, "oracle:a", [BASKET_400])),
              "checkpoints": [{"hypothesis": {"ideas": [{"id": "oracle:a", "verdict": "broke", "tests": [1]}],
                                              "observations": [{"id": "C1.O1", "tests": [1]}],
                                              "dismissed_errors": []}}]}
    text = summarize(output)
    assert "**The oracle:** 1 of 2 ideas checked: 0 held, 1 broke, 0 couldn't tell." in text
    assert "**Errors the tests recorded:** 1, every one answered (0 dismissed with a reason)." in text


def test_a_checkpoint_hands_the_driver_its_ideas_and_errors_to_answer(monkeypatch):
    calls = []

    def fake(client, **kw):
        calls.append(kw)
        if kw["tool_name"] == "submit_casting_round":
            answer = {"give_up": False, "reasoning": "r", "candidate_tests": [
                {"linked_hypothesis": "", "oracle_claim_id": "oracle:a", "predicted_outcome": "x"}]}
            assert kw["validate_fn"](answer) == []
            assert kw["validate_fn"]({**answer, "candidate_tests": [{"oracle_claim_id": "made-up"}]})
            return answer
        if kw["tool_name"] == "submit_checkpoint_hypothesis":
            evidence = json.loads(kw["user_message"])
            assert evidence["ideas_to_answer"] == [{"id": "oracle:a", "claim": "Prices add up", "tests": [1]}]
            assert evidence["errors_to_account_for"] == [{"error": BASKET_400, "tests": [1]}]
            answer = {"summary": "s", "prior_gaps": [], "observations": [], "ideas": [], "dismissed_errors": []}
            assert any("doesn't answer oracle:a" in e for e in kw["validate_fn"](answer))
            return {**answer, "ideas": [{"id": "oracle:a", "verdict": "broke", "tests": [1]}],
                    "dismissed_errors": [{"error": BASKET_400, "reason": "known"}]}
        return {"verdict": "strong_enough", "verdict_reason": "v", "coverage": {"material": False},
                "observation_checks": [], "gaps": [], "prior_gaps_check": []}
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    adapter = type("A", (), {
        "casting_tool_schema": {"name": "submit_casting_round"}, "redact_history_for_model": None,
        "describe_test_for_log": None, "describe_result_for_log": None,
        "casting_system_prompt": staticmethod(lambda budget, first: "cast"),
        "validate_casting_response": staticmethod(lambda data: []),
        "casting_max_tokens": staticmethod(lambda budget: 100), "api_schema_doc": "doc",
        "onboarding_extra": {"oracle_ranked": [{"id": "oracle:a", "claim": "Prices add up"}]},
        "execute_test": staticmethod(lambda test, n: outcome.attach(
            {"test_number": n, "prediction_matched": True},
            outcome.Outcome(action_id="a", effect=outcome.NONE, problems=[BASKET_400]))),
    })()
    _, checkpoints, reason = loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=1, lean=True), {},
                                                     itertools.count(1))
    assert "Most tests should check an idea from 'oracle_ranked'" in calls[0]["system"]
    assert checkpoints[0]["hypothesis"]["ideas"][0]["verdict"] == "broke"
