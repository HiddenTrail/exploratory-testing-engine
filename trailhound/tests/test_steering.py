"""Most of each round goes to new ground, and what can't be shown gets parked (issue
#305). Pure functions, then three checkpoints of the loop with a stubbed model."""

import itertools
import json

from trailhound import loop, outcome, steering
from trailhound.adapters.registry import load_adapter
from trailhound.config import RunConfig


def _cp(n, observations, objected_ids=(), gaps=()):
    """A checkpoint whose Skeptic objected to `objected_ids` through their checks."""
    return {"checkpoint": n,
            "hypothesis": {"observations": [{"id": oid, "continues": cont} for oid, cont in observations]},
            "skeptic_review": {"observation_checks": [{"observation_id": oid, "discriminates_from_rival": False}
                                                      for oid in objected_ids],
                               "gaps": list(gaps)}}


def test_every_adapter_gets_the_follow_up_field_without_declaring_it():
    for name in ("token_purchase", "complex_sut", "clash_royale", "web_gui"):
        schema = load_adapter(name).casting_tool_schema
        items = steering.with_follow_up_field(schema)["input_schema"]["properties"]["candidate_tests"]["items"]
        assert items["properties"]["follows_up"] is steering.FOLLOW_UP_FIELD and "follows_up" not in items["required"]
        assert "follows_up" not in schema["input_schema"]["properties"]["candidate_tests"]["items"]["properties"]


def test_only_a_follow_up_naming_nothing_known_is_sent_back():
    data = {"candidate_tests": [{"follows_up": ""}, {"follows_up": "C1.O1"}, {"follows_up": "C9.G9"}]}
    [error] = steering.follow_up_errors(data, {"C1.O1", "C1.G1"})
    assert error.startswith("candidate_tests[2].follows_up is 'C9.G9'") and "C1.G1, C1.O1" in error
    assert "none, this is the first round" in steering.follow_up_errors(data, set())[0]


def test_a_round_runs_its_new_ground_and_only_so_many_follow_ups():
    tests = [{"n": 1, "follows_up": "C1.O1"}, {"n": 2, "follows_up": "C1.G1"}, {"n": 3, "follows_up": ""},
             {"n": 4, "follows_up": "C1.O1"}, {"n": 5, "follows_up": "C1.O2"}]
    assert steering.follow_up_cap(6) == 2 and steering.follow_up_cap(2) == 1
    kept, dropped = steering.limit(tests, 2, {"C1.O2"})
    assert [t["n"] for t in kept] == [1, 2, 3]
    assert dropped[0]["errors"] == ["over the limit of 2 follow-up test(s) a round"]
    assert "C1.O2, which is parked" in dropped[1]["errors"][0]


def test_repeats_are_counted_from_the_actions_not_from_what_was_declared():
    log = [outcome.attach({"checkpoint": c, "test_number": n}, outcome.Outcome(action_id=a, effect=outcome.NONE))
           for n, (c, a) in enumerate([(1, "a"), (1, "b"), (2, "a"), (2, "c"), (2, "b")], start=1)]
    assert steering.repeats(log, 2) == 2 and steering.repeats(log, 1) == 0


def test_a_claim_objected_to_twice_in_a_row_is_parked_with_its_questions():
    gap = {"id": "C2.G1", "about": ["C2.O1"]}
    mixed = {"id": "C2.G2", "about": ["C2.O1", "C2.O2"]}
    checkpoints = [_cp(1, [("C1.O1", ""), ("C1.O2", "")], objected_ids=["C1.O1", "C1.O2"]),
                   _cp(2, [("C2.O1", "C1.O1"), ("C2.O2", "")], objected_ids=["C2.O1", "C2.O2"], gaps=[gap, mixed])]
    parked = steering.parked_claims(checkpoints)
    assert parked == {"C1.O1": 2}                    # C2.O2 is a new claim, not C1.O2 again
    ids = steering.parked_ids(checkpoints, parked)
    assert ids == {"C1.O1", "C2.O1", "C2.G1"}        # a question also about a live claim stays
    assert [g["id"] for g in steering.without_parked(checkpoints[1]["skeptic_review"], ids)["gaps"]] == ["C2.G2"]
    [told] = steering.for_driver(checkpoints, parked)
    assert told["claim"] == "C2.O1" and told["first_seen_as"] == "C1.O1" and "2 checkpoints in a row" in told["why"]
    assert steering.parked_claims(checkpoints[:1]) == {}


def test_a_parked_claim_stays_in_the_conclusion_when_the_driver_drops_it():
    checkpoints = [_cp(1, [("C1.O1", "")], objected_ids=["C1.O1"]),
                   _cp(2, [("C2.O1", "C1.O1")], objected_ids=["C2.O1"]),
                   _cp(3, [("C3.O1", "")])]
    checkpoints[1]["hypothesis"]["observations"][0]["claim"] = "latest wording"
    final = [{"id": "C3.O1", "continues": "", "status": "corroborated"}]
    concluded = steering.keep_parked(final, checkpoints, steering.parked_claims(checkpoints))
    assert [(o["id"], o["status"], o.get("parked")) for o in concluded] == [
        ("C3.O1", "corroborated", None), ("C2.O1", "inconclusive", True)]
    assert concluded[1]["claim"] == "latest wording"


def test_three_checkpoints_cap_the_follow_ups_and_then_park_the_claim(monkeypatch):
    casting_calls = []

    def fake(client, **kw):
        tool = kw["tool_name"]
        if tool == "submit_casting_round":
            casting_calls.append(kw)
            n = len(casting_calls)
            follow = "" if n == 1 else f"C{n - 1}.O1"
            tests = [{"linked_hypothesis": "", "state": f"s{n}{i}", "follows_up": follow if i < 3 else "",
                      "predicted_outcome": "x"} for i in range(4)]
            answer = {"give_up": False, "reasoning": "r", "candidate_tests": tests}
            assert kw["validate_fn"](answer) == []
            return answer
        if tool == "submit_checkpoint_hypothesis":
            n = len(casting_calls)
            return {"summary": "s", "prior_gaps": [], "observations": [
                {"kind": "anomaly", "continues": "" if n == 1 else f"C{n - 1}.O1", "claim": "c", "tests": [1],
                 "violates": "", "reproduced": "once", "rival": "r", "rival_ruled_out": False, "severity": "low"}]}
        if tool == "submit_skeptic_review":
            oid = json.loads(kw["user_message"])["observations"][0]["id"]
            return {"verdict": "weak", "verdict_reason": "v", "coverage": {"material": False}, "prior_gaps_check": [],
                    "observation_checks": [{"observation_id": oid, "discriminates_from_rival": False,
                                            "rival_is_genuine": True, "kind": "anomaly"}],
                    "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": True, "kind": "rival_not_tested",
                              "about": [oid]}]}
        raise AssertionError(tool)
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    adapter = type("A", (), {
        "casting_tool_schema": {"name": "submit_casting_round", "input_schema": {"properties": {
            "candidate_tests": {"type": "array", "items": {"properties": {}, "required": []}}}}},
        "redact_history_for_model": None, "describe_test_for_log": None, "describe_result_for_log": None,
        "casting_system_prompt": staticmethod(lambda budget, first: "cast"),
        "validate_casting_response": staticmethod(lambda data: []),
        "casting_max_tokens": staticmethod(lambda budget: 100), "api_schema_doc": "doc", "onboarding_extra": {},
        "execute_test": staticmethod(lambda test, n: outcome.attach(
            {"test_number": n, "prediction_matched": True}, outcome.Outcome(action_id=test["state"][:2],
                                                                           effect=outcome.NONE))),
    })()
    config = RunConfig(max_checkpoints=3, first_round_test_budget=4, default_test_budget=6, lean=True)
    log, checkpoints, _ = loop.run_checkpoint_loop(None, adapter, config, {}, itertools.count(1))

    assert "first round: leave 'follows_up' empty" in casting_calls[0]["system"]
    assert "At most 2 of this round's tests may follow up" in casting_calls[1]["system"]
    # Checkpoint 2: two follow-ups run, the third is over the limit, the new test runs.
    assert [c["follow_ups"] for c in checkpoints] == [0, 2, 0]
    assert checkpoints[1]["dropped_tests"][0]["errors"] == ["over the limit of 2 follow-up test(s) a round"]
    # Objected to in checkpoints 1 and 2, so parked after checkpoint 2, and the Driver is told.
    assert checkpoints[1]["parked"] == [{"claim": "C1.O1", "checkpoints_in_a_row": 2}]
    assert json.loads(casting_calls[2]["user_message"])["parked"][0]["claim"] == "C2.O1"
    # Checkpoint 3: every follow-up on the parked claim is dropped; only new ground runs.
    assert len([e for e in log if e["checkpoint"] == 3]) == 1
    assert all("parked" in d["errors"][0] for d in checkpoints[2]["dropped_tests"])


def test_the_summary_and_the_report_show_what_was_parked():
    from trailhound.report import _steering_line
    from trailhound.run_summary import summarize
    entry = {"follow_ups": 2, "repeats": 3, "parked": [{"claim": "C1.O1", "checkpoints_in_a_row": 2}]}
    line = _steering_line(entry, 4)
    assert "2 of 4 test(s) followed up earlier questions, 3 repeated an earlier action." in line
    assert "C1.O1 (2 checkpoints in a row)" in line
    assert _steering_line({}, 4) == ""                      # a run from before #305
    assert "**Parked** (the tests couldn't settle them, so they got no more, #305): C1.O1 (2 checkpoints in a row)" \
        in summarize({"checkpoints": [entry]})
