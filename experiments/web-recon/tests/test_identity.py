"""State identity, validated against the recorded EcoEstate corpus and synthetic cases.

The corpus is the Stage 0 spike made repeatable: the same view at different map zooms,
and loading-vs-error, must all collapse to one state (no over-split), while genuinely
different control sets or routes must not.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from identity import appearance, control_keys, same_state, signature  # noqa: E402
from perceive import Observation  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "fixtures"
ECO = ["eco-initial", "eco-loaded", "eco-zoom1", "eco-zoom2", "eco-loaded-revisit"]


def load(name):
    return Observation.load(FIX / f"{name}.json")


def test_all_ecoestate_frames_are_one_state():
    sigs = {name: signature(load(name)) for name in ECO}
    assert len(set(sigs.values())) == 1, f"over-split: {sigs}"


def test_zoom_does_not_mint_a_new_state():
    # The browser analog of the scroll-surface fix: pan/zoom is the same place.
    assert same_state(load("eco-loaded"), load("eco-zoom2"))


def test_loading_and_error_are_variants_not_states():
    initial, loaded = load("eco-initial"), load("eco-loaded")
    assert same_state(initial, loaded)          # same view (same controls, same route)
    assert appearance(initial) != appearance(loaded)  # different appearance (text differs)


def test_revisit_is_stable():
    assert same_state(load("eco-loaded"), load("eco-loaded-revisit"))


def test_control_skeleton_excludes_the_generic_container():
    # The Leaflet map's giant "generic" node (name = the whole page's text) must not
    # be in the skeleton, or every text change would look like a new state.
    keys = control_keys(load("eco-loaded"))
    assert keys and all(not k.startswith("generic:") for k in keys)


def test_different_controls_are_different_states():
    a = {"url": "http://x/", "text": "", "elements": [{"role": "button", "name": "Buy"}]}
    b = {"url": "http://x/", "text": "", "elements": [{"role": "button", "name": "Sell"}]}
    assert signature(a) != signature(b)


def test_route_distinguishes_states():
    a = {"url": "http://x/one", "text": "", "elements": []}
    b = {"url": "http://x/two", "text": "", "elements": []}
    assert signature(a) != signature(b)


def test_query_string_is_not_a_new_state():
    # A year/filter in the query is a variant of one view, not a different view.
    a = {"url": "http://x/map?year=2024", "text": "", "elements": [{"role": "button", "name": "Zoom in"}]}
    b = {"url": "http://x/map?year=2023", "text": "", "elements": [{"role": "button", "name": "Zoom in"}]}
    assert same_state(a, b)
