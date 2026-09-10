"""The rules that decide whether a run may start, tested where there is no game.

This is the point of the seam. Every number here was calibrated against a client that has
since updated itself, and the failure mode is not a crash - it is a stale constant that keeps
passing until a live, perfectly readable client is declared dead. So the tests below are
mostly about the *direction* of each rule's error rather than its exact output: what happens
when the client animates more than the file on disk expects, what happens when it animates so
much the derivation goes off the end, and what happens when it does not animate at all.

The last of those is the one worth reading. `test_a_still_screen_is_never_called_dead` exists
because a live lobby measured 1 cell of 576 for ninety seconds while genuinely rendering, and
the check that concluded otherwise closed the client it was watching.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
from engine.adapters.clash_royale import reference  # noqa: E402


def drift(*samples: int, ncells: int = checks.NCELLS) -> checks.DriftReading:
    return checks.DriftReading(samples=samples, ncells=ncells)


# --- the derived threshold --------------------------------------------------------------

def test_the_cut_is_taken_from_the_worst_sample_not_the_mean():
    """The lobby's animation cycle is longer than one sample, so most samples read zero.

    Measured live on a healthy lobby: 5, 0, 0, 0, 0, 5. A mean would report that screen as
    almost perfectly still and then cut a threshold no frame of it survives, which is the exact
    shape of the bug this file exists to prevent.
    """
    reading = drift(5, 0, 0, 0, 0, 5)
    assert reading.worst == 5
    assert checks.screen_match_for(reading, 0.94).value == \
        checks.screen_match_for(drift(5), 0.94).value


def test_more_animation_gives_a_looser_cut():
    tight = checks.screen_match_for(drift(4), 0.94)
    loose = checks.screen_match_for(drift(60), 0.94)
    assert loose.value < tight.value


def test_slack_is_added_past_what_was_actually_seen():
    """A session sees the widest twitch it caught, not the widest one that exists."""
    reading = drift(30)
    expected = 1.0 - (30 + checks.SLACK_CELLS) / checks.NCELLS
    assert checks.screen_match_for(reading, 0.94).measured == round(expected, 3)


def test_a_perfectly_still_screen_is_clamped_at_the_ceiling():
    """Nothing above the ceiling survives one frame of an animating game."""
    threshold = checks.screen_match_for(drift(0), 0.94)
    assert threshold.value == checks.MATCH_CEILING
    assert threshold.clamped == "ceiling"
    assert "no frame of an animating game survives" in threshold.why


def test_a_wildly_animated_screen_is_clamped_at_the_floor():
    """Below the floor a frame need reproduce so little of a screen that anything matches."""
    threshold = checks.screen_match_for(drift(checks.NCELLS - 1), 0.94)
    assert threshold.value == checks.MATCH_FLOOR
    assert threshold.clamped == "floor"
    assert "nothing useful is measurable there" in threshold.why


def test_needing_a_looser_cut_than_the_file_is_reported_not_averaged():
    """That the client changed since calibration is the finding, and blending would hide it."""
    threshold = checks.screen_match_for(drift(132, ncells=2304), calibrated=0.974)
    assert threshold.looser_than_calibrated
    assert threshold.calibrated == 0.974
    assert "animates more now than when that was measured" in threshold.why


def test_a_tighter_cut_than_the_file_says_what_it_costs():
    threshold = checks.screen_match_for(drift(2), calibrated=0.90)
    assert not threshold.looser_than_calibrated
    assert "may be told apart" in threshold.why


def test_every_threshold_carries_its_own_argument():
    """This number ends up in the wiki as the provenance of every screen identity in the run."""
    for worst in (0, 3, 40, 400, checks.NCELLS):
        threshold = checks.screen_match_for(drift(worst), 0.94)
        assert threshold.why.strip()
        assert str(worst) in threshold.why
        assert checks.MATCH_FLOOR <= threshold.value <= checks.MATCH_CEILING


# --- what a still screen means ----------------------------------------------------------

def test_a_still_screen_is_never_called_dead():
    """The rule this module refuses to break.

    A live, logged-in lobby sat at a steady 1 cell of 576 for ninety seconds while genuinely
    rendering - a countdown appeared on the Battle button and the cell count denied it. So a
    reading at or under the noise floor says what it *cannot* rule out, and returns no verdict
    at all. There is deliberately no function here that turns drift into "dead".
    """
    quiet = drift(0, 1, 0, 1)
    assert quiet.worst <= checks.NOISE_CELLS
    assert "cannot tell a live screen from a frozen one" in quiet.line()
    assert not any(name for name in dir(checks) if "dead" in name.lower())


def test_real_movement_is_reported_as_evidence_of_rendering():
    line = drift(0, 44, 12).line()
    assert "genuinely moving and the client is rendering" in line
    assert "44" in line


def test_the_reading_shows_every_sample_not_just_the_worst():
    """A reader has to be able to see the cycle, because the cycle is why the max is used."""
    line = drift(5, 0, 0, 0, 0, 5).line()
    assert "5, 0, 0, 0, 0, 5" in line
    assert "worst 5" in line


def test_agreement_matches_how_a_frame_is_actually_scored():
    assert drift(58, ncells=2304).agreement == pytest.approx(1.0 - 58 / 2304)


# --- the baseline screen ----------------------------------------------------------------

def test_starting_on_the_main_screen_is_fine():
    verdict = checks.baseline_verdict(reference.MAIN_SCREEN, 0.981, "sc01 (main)", carried=True)
    assert verdict.verdict == "ok"
    assert reference.SOURCE["pass"] in verdict.message


def test_starting_on_a_different_known_screen_is_refused():
    """Not a safety problem - a labelling one, which produces findings that are pure artefacts.

    A run takes its first screen as the place it returns to after every discovery. Started on
    a profile screen, `return_to_main` reads as a navigation to somewhere new and the home tab
    reads as a control that does nothing. Both look like findings. Neither is.
    """
    verdict = checks.baseline_verdict("sc04", 0.966, "sc04 (social)", carried=True)
    assert verdict.verdict == "refuse"
    assert "Nothing was tapped." in verdict.message
    assert "by hand" in verdict.message


def test_matching_nothing_warns_rather_than_refusing():
    """The likeliest cause is a stale reference, and refusing would make one game update fatal."""
    verdict = checks.baseline_verdict("", 0.71, "nothing carried", carried=False)
    assert verdict.verdict == "warn"
    assert "gone stale" in verdict.message
    assert str(reference.SCREEN_MATCH) in verdict.message


def test_a_warned_run_says_its_screen_names_are_relative():
    verdict = checks.baseline_verdict("", 0.71, "nothing carried", carried=False)
    assert "relative to whatever this actually is" in verdict.message


# --- retrying a crashed pass ------------------------------------------------------------

def test_a_pass_that_wrote_a_map_is_resumed_not_restarted():
    ok, why = checks.restart_verdict(attempt=1, limit=2, has_map=True)
    assert ok and "resuming" in why and "not re-explored" in why


def test_a_pass_that_wrote_nothing_is_not_retried():
    """A retry would start from zero against a client that just killed a pass."""
    ok, why = checks.restart_verdict(attempt=1, limit=2, has_map=False)
    assert not ok
    assert "nothing to resume from" in why
    assert "a person's job" in why


def test_the_retry_limit_stops_the_loop_and_says_why():
    ok, why = checks.restart_verdict(attempt=3, limit=2, has_map=True)
    assert not ok
    assert "past the limit of 2" in why
    assert "the client or the machine" in why


def test_the_limit_is_checked_before_the_map():
    """Otherwise a pass that keeps writing maps and dying retries forever."""
    ok, _ = checks.restart_verdict(attempt=99, limit=2, has_map=True)
    assert not ok


# --- the grid ---------------------------------------------------------------------------

def test_the_grid_comes_from_the_reference_rather_than_being_restated():
    """Scoring against a different grid is not tuning - it is comparing incomparable numbers."""
    assert checks.GRID == (reference.GRID_COLS, reference.GRID_ROWS)
    assert checks.NCELLS == reference.GRID_COLS * reference.GRID_ROWS


def test_refuse_is_an_exception_so_a_caller_cannot_ignore_it():
    assert issubclass(checks.Refuse, Exception)
