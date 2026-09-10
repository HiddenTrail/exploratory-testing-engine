"""The frontier planner: breadth-first choice of the next action, as a pure function."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawl import choose_frontier, dedup_findings  # noqa: E402
from schema import Evidence  # noqa: E402


def test_none_when_no_untried_actions():
    assert choose_frontier([{"id": "st01", "path": [], "untried": []}]) is None
    assert choose_frontier([]) is None


def test_picks_the_nearest_state_with_something_untried():
    states = [
        {"id": "st03", "path": ["a", "b"], "untried": ["x"]},
        {"id": "st02", "path": ["a"], "untried": ["y"]},   # shorter path -> chosen
        {"id": "st04", "path": ["a", "b", "c"], "untried": ["z"]},
    ]
    assert choose_frontier(states) == ("st02", "y")


def test_ties_break_by_id_for_determinism():
    states = [
        {"id": "st02", "path": [], "untried": ["y"]},
        {"id": "st01", "path": [], "untried": ["x"]},
    ]
    assert choose_frontier(states) == ("st01", "x")


def test_returns_the_first_untried_locator():
    assert choose_frontier([{"id": "st01", "path": [], "untried": ["p", "q"]}]) == ("st01", "p")


def test_skips_states_that_are_exhausted():
    states = [
        {"id": "st01", "path": [], "untried": []},
        {"id": "st02", "path": ["a"], "untried": ["only"]},
    ]
    assert choose_frontier(states) == ("st02", "only")


def test_dedup_findings_collapses_identical_only():
    fs = [
        Evidence(kind="http_error", summary="500 x", state_id="st01"),
        Evidence(kind="http_error", summary="500 x", state_id="st01"),   # exact dup -> dropped
        Evidence(kind="http_error", summary="500 x", state_id="st02"),   # other state -> kept
        Evidence(kind="console_error", summary="500 x", state_id="st01"),  # other kind -> kept
    ]
    out = dedup_findings(fs)
    assert len(out) == 3
