"""How well the Driver answered the Skeptic (engine/interplay.py, issue #257). No model calls."""

from engine import interplay
from engine.report import _render_interplay_section


def _cp(n, observations, gaps, checks=(), answers=(), judged=(), verdict="weak"):
    return {"checkpoint": n,
            "hypothesis": {"observations": [{"id": i, "continues": c} for i, c in observations],
                           "prior_gaps": [{"gap_id": g, "status": s} for g, s in answers]},
            "skeptic_review": {"verdict": verdict,
                               "gaps": [{"id": i, "blocks_verdict": b, "about": list(a)} for i, b, a in gaps],
                               "observation_checks": [{"observation_id": i, "discriminates_from_rival": d}
                                                      for i, d in checks],
                               "prior_gaps_check": [{"gap_id": g, "accepted": a} for g, a in judged]}}


# Milestone run 3's shape: "Next page" (C1.O2 -> C2.O2 -> C3.O2) objected to every checkpoint,
# and its blocking gap marked not attempted twice.
RUN_3 = [
    _cp(1, [("C1.O1", ""), ("C1.O2", "")], [("C1.G1", True, ["C1.O1"]), ("C1.G2", True, ["C1.O2"]), ("C1.G3", False, [])],
        checks=[("C1.O1", False), ("C1.O2", False)]),
    _cp(2, [("C2.O1", "C1.O1"), ("C2.O2", "C1.O2")], [("C2.G1", True, ["C2.O2"])],
        checks=[("C2.O1", True), ("C2.O2", False)],
        answers=[("C1.G1", "tested"), ("C1.G2", "not_attempted"), ("C1.G3", "not_attempted")],
        judged=[("C1.G1", True), ("C1.G2", False), ("C1.G3", False)]),
    _cp(3, [("C3.O2", "C2.O2")], [("C3.G1", True, ["C3.O2"])], checks=[("C3.O2", False)],
        answers=[("C2.G1", "not_attempted")], judged=[("C2.G1", False)]),
]


def test_a_claim_objected_to_every_checkpoint_is_followed_through_continues():
    run = interplay.measure(RUN_3)["run"]
    assert run["stubborn_objections"] == [["C1.O2", 3]]
    assert [r["objections_again"] for r in interplay.measure(RUN_3)["checkpoints"]] == [0, 1, 1]


def test_only_blocking_gaps_left_unattempted_count_as_such():
    rows = interplay.measure(RUN_3)["checkpoints"]
    # C1.G3 wasn't blocking, so leaving it isn't counted; C1.G2 and C2.G1 were.
    assert [r["blocking_not_attempted"] for r in rows] == [0, 1, 1]
    assert rows[1]["answered"] == {"tested": 1, "untestable": 0, "resolved": 0, "not_attempted": 2}
    assert (rows[1]["answers_accepted"], rows[1]["answers_judged"]) == (1, 3)


def test_the_run_says_when_the_skeptic_was_satisfied_or_that_it_never_was():
    assert interplay.measure(RUN_3)["run"]["satisfied_at"] is None
    satisfied = RUN_3[:2] + [_cp(3, [], [], verdict="strong_enough")]
    assert interplay.measure(satisfied)["run"]["satisfied_at"] == 3
    assert interplay.measure([]) == {}


def test_the_summary_names_the_numbers_that_matter():
    lines = interplay.summary_lines(interplay.measure(RUN_3))
    assert lines == [
        "The Skeptic raised 5 gap(s), 4 blocking, and was never satisfied in 3 checkpoint(s).",
        "The Driver tested 1 of the 4 earlier gap(s) it answered; the Skeptic accepted 1 of 4 answers.",
        "2 blocking gap(s) weren't even attempted.",
        "Objections that kept coming back: C1.O2 (3 checkpoints in a row).",
    ]


def test_a_checkpoint_cut_short_counts_as_empty_not_a_crash():
    assert interplay.measure([{}, {}])["run"]["gaps"] == 0


def test_the_report_shows_the_section_for_any_run_with_checkpoints():
    html = _render_interplay_section(RUN_3)
    assert "How the Driver answered the Skeptic" in html and "C1.O2 (3 checkpoints in a row)" in html
    assert "<td>none</td>" in html                       # checkpoint 1 had no earlier gaps to answer
    assert _render_interplay_section([]) == ""
