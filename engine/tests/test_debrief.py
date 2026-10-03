"""The checkpoint debrief (issue #266): the Driver answers the Skeptic's questions with
argument and evidence, the Skeptic reconsiders, and all of it is recorded. No model calls."""

import copy
import itertools

from engine import interplay, loop
from engine.config import RunConfig
from engine.report import _debrief_html, _still_open, _verdict_change
from engine.tools import merge_debrief, open_part, validate_debrief_answers, validate_reconsideration

QUESTIONS = [
    {"id": "C1.G1", "kind": "rival_not_tested", "gap": "Is it the limit or the clock?", "next_test": "t",
     "blocks_verdict": True, "about": ["C1.O1"]},
    {"id": "C1.G2", "kind": "overclaimed", "gap": "High severity on one test?", "next_test": "t",
     "blocks_verdict": False, "about": ["C1.O1"]},
    {"id": "C1.G3", "kind": "coverage_overstated", "gap": "Deep coverage of pricing?", "next_test": "t",
     "blocks_verdict": True, "about": []},
    {"id": "C1.G4", "kind": "not_worth_continuing", "gap": "Another paging click?", "next_test": "t",
     "blocks_verdict": False, "about": []},
]
REVIEW = {"verdict": "weak", "verdict_reason": "Rival untested", "gaps": QUESTIONS,
          "observation_checks": [{"observation_id": "C1.O1", "discriminates_from_rival": False, "note": "n"}]}
ANSWERS = {"answers": [
    {"gap_id": "C1.G1", "stance": "defend", "argument": "Tests 3 and 5 differ only in timing", "tests": [3, 5]},
    {"gap_id": "C1.G2", "stance": "concede", "argument": "Lower it to medium until reproduced", "tests": []},
    {"gap_id": "C1.G3", "stance": "change_approach", "argument": "Sweep the tier edges next round", "tests": []},
    {"gap_id": "C1.G4", "stance": "defend", "argument": "It already moved twice", "tests": [7]},
]}
RECONSIDERATION = {
    "judgements": [{"gap_id": "C1.G1", "convinced": "yes", "why": "Timing differs, limit doesn't"},
                   {"gap_id": "C1.G2", "convinced": "partly", "why": "Fair"},
                   {"gap_id": "C1.G3", "convinced": "no", "why": "Still unshown"},
                   {"gap_id": "C1.G4", "convinced": "no", "why": "Test 7 shows the same page"}],
    "revised_checks": [{"observation_id": "C1.O1", "discriminates_from_rival": True, "note": "Now it does"}],
    "verdict": "weak", "verdict_reason": "Pricing coverage still unshown",
}


def test_every_question_gets_one_answer_and_a_defence_cites_its_tests():
    ids = tuple(q["id"] for q in QUESTIONS)
    assert validate_debrief_answers(ANSWERS, gap_ids=ids) == []
    bad = {"answers": [{"gap_id": "C1.G1", "stance": "defend", "argument": "trust me", "tests": []},
                       {"gap_id": "C9.G9", "stance": "shrug", "argument": "x", "tests": list(range(9))}]}
    errors = validate_debrief_answers(bad, gap_ids=ids)
    assert "answers[0] defends, so it must cite the tests that show it" in errors
    assert any("C9.G9" in e and "isn't one of the questions" in e for e in errors)
    assert any("answers[1].stance must be one of defend, concede, change_approach" in e for e in errors)
    assert any("C1.G2" in e for e in errors)                     # unanswered questions are named


def test_the_skeptic_cant_be_satisfied_while_an_objection_remains():
    kwargs = dict(gap_ids=tuple(q["id"] for q in QUESTIONS), blocking_ids=("C1.G1", "C1.G3"),
                  observation_ids=("C1.O1",), failing_checks=("C1.O1",))
    assert validate_reconsideration(RECONSIDERATION, **kwargs) == []
    too_easy = {**RECONSIDERATION, "verdict": "strong_enough"}
    errors = validate_reconsideration(too_easy, **kwargs)
    assert any("C1.G3 didn't convince you" in e for e in errors)
    convinced = copy.deepcopy(too_easy)
    convinced["judgements"][2]["convinced"] = "yes"
    assert validate_reconsideration(convinced, **kwargs) == []
    unrevised = {**convinced, "revised_checks": []}
    assert any("C1.O1's check still says it doesn't discriminate" in e
               for e in validate_reconsideration(unrevised, **kwargs))
    # A blocking question answered with a new approach can't be "yes"-ed into a verdict.
    promised = validate_reconsideration(convinced, **kwargs, defended_ids=("C1.G1",))
    assert any("C1.G3 didn't convince you" in e for e in promised)


def test_only_a_convincing_defence_settles_a_question():
    # #266's benchmark: "yes" to a change of approach had been mapped to settled.
    review = copy.deepcopy(REVIEW)
    all_yes = {**RECONSIDERATION, "judgements": [{**j, "convinced": "yes"} for j in RECONSIDERATION["judgements"]]}
    thread = merge_debrief(review, review["gaps"], ANSWERS, all_yes, {})
    assert [d["outcome"] for d in thread] == ["settled", "conceded", "new_approach", "settled"]
    assert review["gaps"][2]["blocks_verdict"] is True                  # the promised approach still blocks


def test_the_debrief_settles_concedes_or_leaves_questions_open_and_is_recorded():
    review = copy.deepcopy(REVIEW)
    evidence = {3: {"test_number": 3, "result": "a"}, 5: {"test_number": 5, "result": "b"}, 7: {"test_number": 7}}
    thread = merge_debrief(review, review["gaps"], ANSWERS, RECONSIDERATION, evidence)
    assert [d["outcome"] for d in thread] == ["settled", "conceded", "new_approach", "open"]
    assert thread[0]["evidence"] == {"3": evidence[3], "5": evidence[5]}           # only what was cited
    assert thread[0]["blocked"] and review["gaps"][0]["blocks_verdict"] is False   # settled stops blocking
    assert review["gaps"][0]["blocked_before_debrief"] is True
    assert review["gaps"][2]["blocks_verdict"] is True                             # still open, still blocks
    check = review["observation_checks"][0]
    assert (check["discriminates_from_rival"], check["first_discriminates_from_rival"]) == (True, False)
    assert (review["first_verdict"], review["verdict"]) == ("weak", "weak")
    assert [g["id"] for g in open_part(review)["gaps"]] == ["C1.G3", "C1.G4"]       # settled and conceded drop out


def test_the_skeptic_judges_the_tests_as_the_driver_saw_them():
    adapter = type("A", (), {"redact_history_for_model": staticmethod(
        lambda log: [{"test_number": e["test_number"], "seen": "redacted"} for e in log])})()
    log = [{"test_number": n, "secret": "x"} for n in (1, 3, 5)]
    assert loop.cited_evidence(adapter, log, ANSWERS) == {3: {"test_number": 3, "seen": "redacted"},
                                                         5: {"test_number": 5, "seen": "redacted"}}


def _run_with_debrief(monkeypatch, reconsider, checkpoints=2):
    seen_prior = []
    monkeypatch.setattr(loop, "get_casting_round", lambda *a, **k: {"give_up": True, "reasoning": "r", "candidate_tests": []})

    def hypothesis(client, adapter, run_config, happy_day_example, history, prior_skeptic_review=None, **k):
        seen_prior.append(prior_skeptic_review)
        return {"summary": "s", "behaviors": [], "untested": [], "prior_gaps": [],
                "observations": [{"id": "", "kind": "finding", "claim": "c", "tests": [1], "continues": ""}]}
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", hypothesis)
    monkeypatch.setattr(loop, "get_testing_story", lambda *a, **k: {"areas": [], "obstacles": []})
    monkeypatch.setattr(loop, "get_skeptic_review", lambda *a, **k: copy.deepcopy(
        {**REVIEW, "gaps": [{k2: v for k2, v in q.items() if k2 != "id"} for q in QUESTIONS[:2]],
         "observation_checks": [{"observation_id": "C1.O1", "kind": "finding", "discriminates_from_rival": False,
                                 "note": "n"}]}))
    monkeypatch.setattr(loop, "get_debrief_answers", lambda *a, **k: {"answers": ANSWERS["answers"][:2]})
    monkeypatch.setattr(loop, "get_reconsideration", reconsider)
    adapter = type("A", (), {"casting_tool_schema": {}, "redact_history_for_model": None})()
    _, cps, reason = loop.run_checkpoint_loop(None, adapter, RunConfig(max_checkpoints=checkpoints), {}, itertools.count(1))
    return cps, reason, seen_prior


def test_a_convinced_skeptic_ends_the_run_and_the_thread_is_on_the_checkpoint(monkeypatch):
    convinced = lambda *a, **k: {"judgements": [{"gap_id": "C1.G1", "convinced": "yes", "why": "w"},
                                                {"gap_id": "C1.G2", "convinced": "yes", "why": "w"}],
                                 "revised_checks": [], "verdict": "strong_enough", "verdict_reason": "Convinced"}
    cps, reason, _ = _run_with_debrief(monkeypatch, convinced)
    assert reason == "skeptic_satisfied" and len(cps) == 1
    assert cps[0]["skeptic_review"]["first_verdict"] == "weak"
    assert [d["outcome"] for d in cps[0]["debrief"]] == ["settled", "conceded"]


def test_the_next_checkpoint_answers_only_what_the_debrief_left_open(monkeypatch):
    unconvinced = lambda *a, **k: {"judgements": [{"gap_id": "C1.G1", "convinced": "no", "why": "w"},
                                                  {"gap_id": "C1.G2", "convinced": "partly", "why": "w"}],
                                   "revised_checks": [], "verdict": "weak", "verdict_reason": "Not yet"}
    cps, reason, seen_prior = _run_with_debrief(monkeypatch, unconvinced)
    assert len(cps) == 2
    assert [g["id"] for g in seen_prior[1]["gaps"]] == ["C1.G1"]      # C1.G2 was conceded


def test_a_rejected_attempt_is_kept_in_the_usage_log():
    # #266: the report can show why an answer took several tries.
    from types import SimpleNamespace
    from engine.client import call_tool_with_retry
    replies = iter([{"wrong": 1}, {"answers": []}])
    usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=next(replies), id="x", name="t")], stop_reason="tool_use",
        usage=usage)))
    sink = []
    call_tool_with_retry(client, model="m", system="s", tools=[{"name": "t", "input_schema": {}}], tool_name="t",
                         user_message="u", validate_fn=lambda d: [] if "answers" in d else ["'answers' missing"],
                         max_tokens=10, usage_sink=sink)
    assert sink[0]["rejected"] == ["'answers' missing"] and "rejected" not in sink[1]


def test_the_measures_count_the_debrief():
    review = copy.deepcopy(REVIEW)
    thread = merge_debrief(review, review["gaps"], ANSWERS, RECONSIDERATION, {})
    measured = interplay.measure([{"hypothesis": {}, "skeptic_review": review, "debrief": thread}])
    assert measured["run"]["debrief"] == {"questions": 4, "defended": 2, "conceded": 1, "changed_approach": 1,
                                          "convinced": 1, "partly": 1, "open_after": 2}
    assert measured["run"]["still_open"] == ["C1.G3", "C1.G4"]
    lines = interplay.summary_lines(measured)
    assert ("In the debriefs the Driver defended 2, conceded 1 and changed approach on 1 of 4 question(s); "
            "the Skeptic was convinced by 1 and partly by 1.") in lines
    assert "Still open at the end: C1.G3, C1.G4." in lines


def test_the_report_shows_the_debrief_thread_and_what_is_still_open():
    review = copy.deepcopy(REVIEW)
    thread = merge_debrief(review, review["gaps"], ANSWERS, {**RECONSIDERATION, "verdict": "weak"}, {3: {}})
    html = _debrief_html(thread)
    assert "Debrief (4 question(s))" in html and "Tests 3 and 5 differ only in timing" in html
    assert "convinced: yes" in html and ">settled<" in html and ">new approach<" in html
    assert "(what those tests recorded was attached)" in html
    open_html = _still_open(thread)
    assert "Questions still open" in open_html and "C1.G3" in open_html and "C1.G1" not in open_html
    changed = {"verdict": "strong_enough", "first_verdict": "weak", "first_verdict_reason": "Rival untested"}
    assert "before the debrief: weak" in _verdict_change(changed)
    assert _verdict_change({"verdict": "weak"}) == "" and _debrief_html([]) == ""
