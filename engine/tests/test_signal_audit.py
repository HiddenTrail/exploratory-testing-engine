"""The signal audit's analysis (#146): what it calls a weak spot, from recorded acts."""

from engine.adapters.web_gui.signal_audit import analyse, pick_pairs
from engine.adapters.web_gui import reference as ref_mod
from engine.tests.test_web_gui_adapter import _ontology


def _run(signals, weak=None, screen="known_screen", reached=True, verdict="sent"):
    return {"state": "st01", "control": "button:A", "reached_target_state": reached, "verdict": verdict,
            "screen_was": screen, "signals": {"settled_before": True, "settled_after": True, **signals},
            "signals_weak": weak or {}, "covered_by": None, "wall": 1.0}


def test_a_trusted_signal_that_comes_and_goes_is_a_weak_spot():
    runs = [_run({"controls_removed": ["link:slide 1"]}), _run({}), _run({"controls_removed": ["link:slide 1"]})]
    report = analyse(runs, {}, "http://x")
    assert report["flaky_trusted"] == ["st01 :: button:A | controls_removed: link:slide 1 | in 2 of 3"]


def test_a_flipping_screen_class_and_the_reasons_for_weak_signals_are_reported():
    runs = [_run({}, screen="new_screen"),
            _run({}, weak={"failed_requests": ["GET https://ads.example/p -> 0"]}),
            _run({}, weak={"console_errors": ["boom"]}, verdict="not_actuated")]
    report = analyse(runs, {}, "http://x")
    assert report["flaky_screen"] == ["st01 :: button:A | {'new_screen': 1, 'known_screen': 2}"]
    assert report["weak"] == {"third-party | failed_requests: GET https://ads.example/p -> 0": 1,
                              "not sent | console_errors: boom": 1}


def test_noise_that_differs_between_sessions_is_reported():
    noise = {"st01": [{"controls": ["a"]}, {"controls": ["a", "b"]}], "st02": [{"controls": []}, {"controls": []}]}
    assert list(analyse([], noise, "http://x")["noise_unstable"]) == ["st01"]


def test_pairs_are_spread_across_states():
    pairs = pick_pairs(ref_mod.Reference(_ontology()), 2)
    assert {state for state, _ in pairs} == {"st01", "st02"}
