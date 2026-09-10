"""The frontier planner: breadth-first choice of the next action, as a pure function."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawl import Crawler, choose_frontier, dedup_findings, gesture_actions  # noqa: E402
from schema import Evidence  # noqa: E402


class _FakeLocator:
    def __init__(self, count, href=""):
        self._count, self._href = count, href

    def count(self):
        return self._count

    def get_attribute(self, name, timeout=None):
        return self._href


class _FakePage:
    """Resolves get_by_role against a fixed table of (role, name) -> (count, href)."""
    def __init__(self, table):
        self._table = table

    def get_by_role(self, role, name, exact=False):
        count, href = self._table.get((role, name), (0, ""))
        return _FakeLocator(count, href)


def _crawler(page, proposer=None):
    return Crawler(page, collector=None, start_url="http://app.example/", proposer=proposer)


def test_gesture_probes_are_synthetic_and_complete():
    acts = gesture_actions()
    kinds = {a["act_kind"] for a in acts}
    assert kinds == {"hover", "wheel_down", "wheel_up", "zoom_in", "zoom_out", "drag"}
    assert all(a["role"] == "gesture" and a["locator"].startswith("__gesture__:") for a in acts)


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


def test_real_controls_are_chosen_before_gesture_probes():
    # A state whose next untried is a gesture is deprioritised behind one with a real
    # control still to try, even if the gesture state is nearer - real coverage first.
    states = [
        {"id": "st01", "path": [], "untried": ["__gesture__:hover"]},   # nearer, but a gesture
        {"id": "st02", "path": ["a"], "untried": ["#realbutton"]},      # farther, a real control
    ]
    assert choose_frontier(states) == ("st02", "#realbutton")


def test_gesture_only_frontier_is_still_chosen_when_nothing_else_remains():
    states = [{"id": "st01", "path": [], "untried": ["__gesture__:zoom_in"]}]
    assert choose_frontier(states) == ("st01", "__gesture__:zoom_in")


def test_resolve_candidate_requires_a_unique_match():
    page = _FakePage({
        ("button", "Menu"): (1, ""),
        ("button", "Two"): (2, ""),   # ambiguous -> dropped
        ("link", "Home"): (1, "/home"),
    })
    c = _crawler(page)
    assert c._resolve_candidate({"role": "button", "name": "Menu"})["locator"] == 'role=button[name="Menu"]'
    assert c._resolve_candidate({"role": "button", "name": "Two"}) is None      # not unique
    assert c._resolve_candidate({"role": "button", "name": "Gone"}) is None     # no match
    assert c._resolve_candidate({"role": "slider", "name": "Menu"}) is None     # not locatable
    assert c._resolve_candidate({"role": "button", "name": 'a"b'}) is None      # quote in name
    assert c._resolve_candidate({"role": "link", "name": "Home"})["href"] == "/home"


def test_llm_candidates_are_resolved_gated_and_marked():
    page = _FakePage({
        ("button", "Menu"): (1, ""),                             # good -> kept
        ("link", "Search"): (1, ""),                             # duplicates an existing -> skipped
        ("link", "Google"): (1, "https://google.com/"),          # off-site -> gate refuses
        ("button", "Delete account"): (1, ""),                   # mutating verb -> gate refuses
    })
    proposals = [
        {"role": "button", "name": "Menu", "why": "icon-only"},
        {"role": "link", "name": "Search", "why": "already known"},
        {"role": "link", "name": "Google", "why": "off-site"},
        {"role": "button", "name": "Delete account", "why": "destructive"},
        {"role": "button", "name": "Ghost", "why": "hallucinated"},   # no match -> dropped
    ]
    c = _crawler(page, proposer=lambda obs: proposals)
    existing = [{"role": "link", "name": "Search"}]                   # the DOM already found this
    out = c._llm_candidate_actions(obs=None, existing=existing)
    assert [(a["role"], a["name"]) for a in out] == [("button", "Menu")]
    assert out[0]["origin"] == "llm" and out[0]["act_kind"] == "click"


def test_mutation_actions_are_vetted_and_carry_a_distinct_identity():
    c = Crawler(page=None, collector=None, start_url="http://app.example/", mutate=True)
    elements = [
        {"role": "textbox", "name": "Search postcodes", "type": "text", "locator": "#q", "href": ""},
        {"role": "button", "name": "Delete", "type": "submit", "locator": "#del", "href": ""},  # refused
    ]
    out = c._mutation_actions(elements)
    assert len(out) == 1
    a = out[0]
    assert a["act_kind"] == "submit_search" and a["origin"] == "mutation"
    # distinct identity (coexists with the read-only fill of the same field) + real selector
    assert a["locator"] == "__mutate__:submit_search:#q" and a["act_target"] == "#q"


def test_dedup_findings_collapses_identical_only():
    fs = [
        Evidence(kind="http_error", summary="500 x", state_id="st01"),
        Evidence(kind="http_error", summary="500 x", state_id="st01"),   # exact dup -> dropped
        Evidence(kind="http_error", summary="500 x", state_id="st02"),   # other state -> kept
        Evidence(kind="console_error", summary="500 x", state_id="st01"),  # other kind -> kept
    ]
    out = dedup_findings(fs)
    assert len(out) == 3
