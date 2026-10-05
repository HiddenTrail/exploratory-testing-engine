"""The checkpoint report is conclusion first (issue #41): the summary, the
Skeptic's reason, one line per observation and per gap are visible, and the long
detail and the tests are folded away. No LLM calls."""

import html as html_module
import re

from engine.report import _render_checkpoint

_ENTRY = {
    "checkpoint": 2,
    "hypothesis": {
        "summary": "SUMMARY-TEXT",
        "behaviors": [{"claim": "BEHAVIOR-TEXT", "tests": [2]}],
        "observations": [{
            "id": "C2.O1", "kind": "anomaly", "driver_kind": "bug", "lowered_because": "LOWERED-REASON", "severity": "high", "claim": "CLAIM-TEXT",
            "tests": [1, 4], "violates": "VIOLATES-TEXT", "reproduced": "consistent",
            "mechanism": "MECHANISM-TEXT", "rival": "RIVAL-TEXT", "rival_ruled_out": False, "why": "WHY-TEXT",
        }],
        "untested": [{"area": "UNTESTED-TEXT"}],
        "prior_gaps": [{"gap_id": "C1.G1", "status": "tested", "tests": [3], "reason": ""},
                       {"gap_id": "C1.G2", "status": "not_attempted", "tests": [], "reason": "REASON-TEXT"}],
    },
    "skeptic_review": {
        "verdict": "weak", "verdict_reason": "VERDICT-REASON",
        "observation_checks": [{"observation_id": "C2.O1", "discriminates_from_rival": False,
                                "rival_is_genuine": True, "kind": "anomaly", "note": "CHECK-NOTE"}],
        "coverage": {"material": False, "untouched": ["UNTOUCHED-TEXT"], "note": "COVERAGE-NOTE"},
        "gaps": [{"id": "C2.G1", "gap": "GAP-TEXT", "next_test": "NEXT-TEST", "blocks_verdict": True, "about": ["C2.O1"]}],
        "prior_gaps_check": [{"gap_id": "C1.G1", "accepted": True, "note": "ACCEPTED-NOTE"},
                             {"gap_id": "C1.G2", "accepted": False, "note": "REJECTED-NOTE"}],
    },
    "test_coverage": {"tests_run": 4, "fields": [{"field": "COVERED-FIELD", "values_tried": ["TRIED-VALUE"],
                                                  "never_tried": ["NEVER-VALUE"]}]},
}


def _render():
    rounds = {1: [{"round_reasoning": "ROUND-REASONING"}]}
    html = _render_checkpoint(2, _ENTRY, rounds, lambda entry: "<p>TEST-ENTRY</p>")
    visible = re.sub(r"<details.*?</details>", " ", html, flags=re.S)
    return html_module.unescape(html), html_module.unescape(visible)


def test_the_conclusion_is_visible():
    _, visible = _render()
    for text in ("SUMMARY-TEXT", "VERDICT-REASON", "C2.O1", "CLAIM-TEXT", "doesn't discriminate",
                 "lowered because LOWERED-REASON", "C2.G1", "GAP-TEXT", "NEXT-TEST", "blocks verdict"):
        assert text in visible, text
    assert "Prior gaps: 1 tested, 1 not attempted. The Skeptic accepted 1 of 2 answers." in visible


def test_the_detail_and_the_tests_are_folded():
    html, visible = _render()
    for text in ("BEHAVIOR-TEXT", "MECHANISM-TEXT", "RIVAL-TEXT", "WHY-TEXT", "CHECK-NOTE", "UNTESTED-TEXT",
                 "COVERAGE-NOTE", "UNTOUCHED-TEXT", "COVERED-FIELD", "TRIED-VALUE", "NEVER-VALUE", "REASON-TEXT", "REJECTED-NOTE", "ROUND-REASONING", "TEST-ENTRY"):
        assert text in html, text
        assert text not in visible, text


def test_a_checkpoint_without_a_conclusion_still_shows_its_tests():
    html = _render_checkpoint(3, None, {1: [{"round_reasoning": "r"}]}, lambda entry: "<p>TEST-ENTRY</p>")
    assert "Checkpoint 3" in html and "TEST-ENTRY" in html


def test_the_report_shows_the_testing_story_and_where_it_stands():
    # Issue #265: per checkpoint in its details, and the last one as its own section.
    from engine.report import _areas_table, _render_standing_section
    area = {"area": "Paging", "approach": "GUI clicks", "tested": "barely", "not_tested": "Last page",
            "tests": [3], "quality": "neutral", "confidence": "low", "why": "One click"}
    table = _areas_table([area])
    assert "Paging" in table and "not tested: Last page" in table and ">neutral · low<" in table   # a run before #271
    assert "Where it stands" in _render_standing_section([{"hypothesis": {"areas": [area]}}])
    assert _render_standing_section([{"hypothesis": {}}]) == ""



def test_the_story_says_what_coverage_is_of_how_problems_would_show_and_what_got_in_the_way():
    # #271: Bolton's three strands and Bach's dashboard; the story leads the report.
    from engine.report import _areas_table, _render_standing_section
    area = {"area": "Paging", "approach": "GUI clicks", "coverage": "can_it_work", "coverage_of": "next and previous",
            "oracle": "the same items twice", "not_tested": "Last page", "tests": [3],
            "quality": "concerns", "confidence": "low", "why": "One click"}
    table = _areas_table([area])
    assert ">L1" in table and "of next and previous" in table
    assert "a problem would show as: the same items twice" in table and ">Concerns · low<" in table
    section = _render_standing_section([{"hypothesis": {"areas": [area], "obstacles": [
        {"obstacle": "The page has no item ids", "would_help": "Stable ids"}]}}])
    assert "What got in the way of testing" in section and "What would help: Stable ids" in section
