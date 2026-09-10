"""The preflight's wiring, tested with no window, no game and no Win32 API.

That this is testable at all is a deliberate property of `preflight.py`: every Win32 import in
it is function-local, so a test can put a stub module under the name it will reach for. The
alternative - importing `controller` at the top - would have made this file Windows-only and
these checks something nobody runs, which for the *safety* ordering below would be a poor
trade. Whether the denylist is verified before any frame is scored is not a Windows question.

What is actually being checked is order and refusal, not arithmetic - the arithmetic is
`test_checks.py`'s. Three of these are worth more than the rest:

- `test_no_frame_is_ever_grabbed_with_verification` - a verified grab of a hidden window is a
  driving call that ends in `_restart` closing the client. Play Games parks its window hidden,
  so this is the ordinary path here, and a liveness check has already killed a client this way.
- `test_the_guards_are_checked_before_any_frame_is_scored` - an empty denylist is the failure
  that looks exactly like success, so it must be impossible to get as far as plausible output.
- `test_a_refusal_says_nothing_was_tapped` - the operator's first question on any refusal.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
import preflight  # noqa: E402
from engine.adapters.clash_royale import actions as cr_actions  # noqa: E402
from engine.adapters.clash_royale import reference  # noqa: E402
from engine.adapters.clash_royale import session as cr_session  # noqa: E402


class FakeTarget:
    def __init__(self, boxes: int = 6):
        self.window_title = "Clash Royale - SomeAccount"
        self.denylist = [(0.0, 0.0, 0.1, 0.1)] * boxes
        self.cell_delta = 10
        self.screen_match = 0.94
        self.startup_quiet = 3.0


class FakeController:
    """A window that exists, is the right size, and records every grab made against it."""

    def __init__(self, size=(787, 1400), boxes: int = 6):
        self.hwnd = 4242
        self.pid = 99
        self.target = FakeTarget(boxes)
        self._size = size
        self.grabs: list[dict] = []

    @property
    def rect(self):
        return (0, 0, self._size[0], self._size[1])

    def grab(self, cols: int, rows: int, region=(0.0, 0.0, 1.0, 1.0), verify: bool = True):
        self.grabs.append({"verify": verify})
        return b"\x00" * (cols * rows * 4)


class FakeObservation:
    def __init__(self, screen: str, agreement: float, carried: bool):
        self.screen, self.agreement, self.carried = screen, agreement, carried


@pytest.fixture
def wired(monkeypatch):
    """Stub modules under the names `preflight` reaches for, and hand back the knobs.

    Returned as a mutable namespace so each test changes one thing - the window is missing, the
    drift is huge, the client is on the wrong screen - and leaves the rest of the machine
    healthy. A test that has to construct a whole plausible machine to change one fact ends up
    asserting about the construction.
    """
    state = types.SimpleNamespace(
        controller=FakeController(),
        window_lost=None,
        deltas=[4, 0, 0, 0, 0, 4],
        observation=FakeObservation(reference.MAIN_SCREEN, 0.981, True),
        observe_raises=None,
        guard_raises=None,
        calibration={"screen_match": 0.974, "cell_delta": 10},
        guard_called_after_frames=None,
    )

    class WindowLost(RuntimeError):
        pass

    controller_mod = types.ModuleType("controller")
    controller_mod.WindowLost = WindowLost
    controller_mod.READY_COLS = 64
    controller_mod.READY_ROWS = 36

    def changed_cells(before, after, delta):
        grabs = len(state.controller.grabs)
        return state.deltas[min(grabs - 2, len(state.deltas) - 1)]

    controller_mod.changed_cells = changed_cells
    controller_mod.readable_output = lambda: None
    controller_mod.set_dpi_aware = lambda: None

    attach_mod = types.ModuleType("attach")

    def attach(game, verbose=True):
        if state.window_lost:
            raise WindowLost(state.window_lost)
        return state.controller

    attach_mod.attach = attach
    attach_mod.apply_calibration = lambda controller, game, *a: dict(state.calibration)

    for name, module in (("controller", controller_mod), ("attach", attach_mod)):
        monkeypatch.setitem(sys.modules, name, module)

    def guard(target):
        state.guard_called_after_frames = len(state.controller.grabs)
        if state.guard_raises:
            raise cr_actions.Unsafe(state.guard_raises)
        return "denylist verified"

    monkeypatch.setattr(cr_actions, "preflight", guard)
    monkeypatch.setattr(reference, "check_reference", lambda: "reference verified")

    class FakeSession:
        def __init__(self, controller):
            self.controller = controller

        def observe(self, settle: float = 0.0):
            if state.observe_raises:
                raise cr_actions.Unsafe(state.observe_raises)
            return state.observation

    monkeypatch.setattr(cr_session, "Session", FakeSession)
    monkeypatch.setattr(preflight.time, "sleep", lambda seconds: None)
    return state


# --- the window -------------------------------------------------------------------------

def test_a_missing_window_names_the_adopted_window_case(wired):
    """"No window is open" reads as "the game is closed", and the operator opens another one.

    The real cause is often a stranger window carrying the game's name, which `attach` printed
    and which has scrolled past. So the refusal repeats it.
    """
    wired.window_lost = "no Play Games window named 'Clash Royale' is open."
    with pytest.raises(checks.Refuse) as refused:
        preflight.run(verbose=False)
    message = str(refused.value)
    assert "editor showing a file about this game" in message
    assert "Nothing was tapped." in message


def test_a_dpi_scaled_client_is_refused_with_the_cause(wired):
    """393x700 where the client is really 787x1400: every coordinate lands at half the offset."""
    wired.controller = FakeController(size=(120, 200))
    with pytest.raises(checks.Refuse) as refused:
        preflight.run(verbose=False)
    message = str(refused.value)
    assert "per-monitor DPI awareness" in message
    assert "nothing would error" in message


def test_a_healthy_window_is_measured_and_reported(wired):
    report = preflight.run(verbose=False)
    assert report.client == (787, 1400)
    assert report.hwnd == 4242
    assert any("787x1400" in line for line in report.lines)


# --- the safety layers ------------------------------------------------------------------

def test_the_guards_are_checked_before_any_frame_is_scored(wired):
    """An empty denylist is the failure that looks exactly like success.

    Every check downstream of one reports "allowed", so the run has to be unable to reach
    plausible-looking output with one loaded. Checking it after the drift measurement would
    still refuse - but only after producing six readings and a derived threshold, which is
    precisely the output somebody would screenshot.
    """
    preflight.run(verbose=False)
    assert wired.guard_called_after_frames == 0


def test_an_unsafe_guard_report_refuses_the_run(wired):
    wired.guard_raises = "REFUSING to run: empty coordinate denylist"
    with pytest.raises(checks.Refuse) as refused:
        preflight.run(verbose=False)
    assert "empty coordinate denylist" in str(refused.value)


def test_the_reference_pass_is_named_in_the_output(wired):
    """A fingerprint has a date on it, and the run has to say which one."""
    report = preflight.run(verbose=False)
    assert any(reference.SOURCE["pass"] in line for line in report.lines)
    assert report.to_json()["reference_pass"] == reference.SOURCE["pass"]


# --- watching without touching ----------------------------------------------------------

def test_no_frame_is_ever_grabbed_with_verification(wired):
    """The most expensive lesson in this project, as an assertion.

    A verified grab of a non-foreground window sends `ensure_readable` looking for a fix; the
    fix is `_restart`; `_restart` closes the client before finding out it has no executable to
    reopen it with. Play Games parks its window hidden, so this is the ordinary path to killing
    the client being measured, not an unlikely one.
    """
    preflight.run(verbose=False)
    assert wired.controller.grabs, "no frames were grabbed at all"
    assert all(frame["verify"] is False for frame in wired.controller.grabs)


def test_enough_samples_are_taken_to_see_the_animation_cycle(wired):
    """Two samples of a lobby read zero twice in three tries, and cut an unusable threshold."""
    report = preflight.run(verbose=False)
    assert len(report.drift.samples) == preflight.DRIFT_SAMPLES
    assert preflight.DRIFT_SAMPLES >= 6


def test_a_still_window_is_reported_not_refused(wired):
    """A live lobby held at 1 cell of 576 for ninety seconds. Refusing on that closes a client."""
    wired.deltas = [0, 0, 0, 0, 0, 0]
    report = preflight.run(verbose=False)
    assert report.ok
    assert "cannot tell a live screen from a frozen one" in report.lines[-3] or \
        any("cannot tell a live screen" in line for line in report.lines)


def test_the_threshold_is_derived_from_this_session(wired):
    """Not read from the file. The file was measured against a lobby that no longer exists.

    471 of 2304 is not invented: it is the busiest frame `_wait_settled` actually measured
    against the real client on 2026-09-08, back when the drift sample was still taken on the
    coarser identity grid and so read this same animation as comfortably within tolerance.
    """
    wired.deltas = [471] * 6
    report = preflight.run(verbose=False)
    assert report.threshold.value < 0.94
    assert report.threshold.looser_than_calibrated
    assert "animates more now" in report.threshold.why


# --- where the client is ----------------------------------------------------------------

def test_starting_somewhere_else_is_refused(wired):
    wired.observation = FakeObservation("sc04", 0.962, True)
    with pytest.raises(checks.Refuse) as refused:
        preflight.run(verbose=False)
    assert "Nothing was tapped." in str(refused.value)


def test_a_live_battle_board_refuses_before_anything_starts(wired):
    """The elixir tripwire. A pass whose scope is the meta-game must not begin over a match."""
    wired.observe_raises = "ABORTING: the elixir bar reads 42% pink"
    with pytest.raises(checks.Refuse) as refused:
        preflight.run(verbose=False)
    assert "elixir bar" in str(refused.value)
    assert "by hand" in str(refused.value)


def test_matching_nothing_warns_and_the_run_continues(wired):
    wired.observation = FakeObservation("unknown-1", 0.62, False)
    report = preflight.run(verbose=False)
    assert report.ok
    assert report.baseline.verdict == "warn"
    assert any(line.startswith("WARNING:") for line in report.lines)


def test_a_refusal_says_nothing_was_tapped(wired):
    """Whatever went wrong, this is the operator's first question."""
    for setup in ({"window_lost": "gone"},
                  {"guard_raises": "empty denylist"},
                  {"observe_raises": "ABORTING: a board"},
                  {"observation": FakeObservation("sc04", 0.96, True)}):
        for key, value in setup.items():
            setattr(wired, key, value)
        with pytest.raises(checks.Refuse) as refused:
            preflight.run(verbose=False)
        assert "apped" in str(refused.value), f"{setup} gave no reassurance: {refused.value}"
        for key in setup:
            setattr(wired, key, None if key != "observation" else
                    FakeObservation(reference.MAIN_SCREEN, 0.98, True))


# --- what gets carried forward ----------------------------------------------------------

def test_the_threshold_argument_survives_into_the_wiki_note(wired):
    """A threshold whose reasoning is left in a terminal scrollback cannot be checked later."""
    report = preflight.run(verbose=False)
    note = report.wiki_note()
    assert "It was not a default" in note
    assert reference.SOURCE["pass"] in note
    assert "idle drift" in note


def test_a_warned_run_carries_the_warning_into_the_wiki(wired):
    wired.observation = FakeObservation("unknown-1", 0.62, False)
    note = preflight.run(verbose=False).wiki_note()
    assert "Read with caution" in note


def test_the_report_serialises_to_something_a_run_can_keep(wired):
    """Sample count pinned explicitly rather than left at the default: what this checks is the
    shape of the serialised report, not how many seconds `DRIFT_SAMPLES` happens to be today."""
    payload = preflight.run(verbose=False, samples=6).to_json()
    assert payload["client"] == [787, 1400]
    assert payload["drift"]["samples"] == [4, 0, 0, 0, 0, 4]
    assert payload["threshold"]["why"]
    assert payload["baseline"]["verdict"] == "ok"
