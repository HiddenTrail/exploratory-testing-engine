"""`map_animation`'s two tiers: a fast one that catches a sub-second cycle and a slow one
that catches what the fast tier's window is too short to see happen even once.

A synthetic controller stands in for the game: it hands back a scripted sequence of
frames, one per `grab()` call, so a cell can be made to change at an exact point in the
sequence rather than at a time that would make the test itself slow or flaky. `time.sleep`
is patched to a no-op for the same reason - what is under test is which tier attributes a
change to which cell, not real timing.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from controller import Target  # noqa: E402
from recon import GRID_COLS, GRID_ROWS, Recon, Screen  # noqa: E402

STILL = (40, 40, 40)
MOVED = (200, 60, 60)


def frame(changed: set[tuple[int, int]] = frozenset(), moved=MOVED) -> bytes:
    """One BGRA grab: every cell `STILL` except the ones in `changed`."""
    out = bytearray()
    for y in range(GRID_ROWS):
        for x in range(GRID_COLS):
            b, g, r = moved if (x, y) in changed else STILL
            out += bytes((b, g, r, 255))
    return bytes(out)


class SequenceController:
    """Hands back one scripted frame per `grab()` call, in order."""

    def __init__(self, frames: list[bytes]) -> None:
        self.target = Target(name="Fake", exe="")
        self.notes: list[str] = []
        self._frames = list(frames)
        self._calls = 0

    def note(self, message: str) -> None:
        self.notes.append(message)

    def say(self, message: str) -> None:
        pass

    def grab(self, cols: int, rows: int, region=(0.0, 0.0, 1.0, 1.0), verify=True) -> bytes:
        assert (cols, rows) == (GRID_COLS, GRID_ROWS)
        this_call = self._frames[min(self._calls, len(self._frames) - 1)]
        self._calls += 1
        return this_call


FAST_CELL = (2, 2)   # changes between the fast tier's 1st and 2nd frame
SLOW_CELL = (10, 6)  # unchanged throughout the fast tier; changes inside the slow tier


def build_frames() -> list[bytes]:
    """6 fast-tier frames, then 6 slow-tier frames - `map_animation`'s own call order.

    A cell has to differ between two frames *inside* a tier to be attributed to it -
    `map_animation` never compares a tier's frames against anything outside the tier -
    so `FAST_CELL` moves on the fast tier's own first-to-second frame, and `SLOW_CELL`
    stays still for the fast tier and the slow tier's own first half, then moves for its
    second half."""
    fast = [frame(set())] + [frame({FAST_CELL})] * 5
    slow = [frame({FAST_CELL})] * 3 + [frame({FAST_CELL, SLOW_CELL})] * 3
    return fast + slow


@pytest.fixture
def recon(tmp_path: Path, monkeypatch) -> Recon:
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    controller = SequenceController(build_frames())
    session = Recon(controller, tmp_path)
    session.images.mkdir(parents=True, exist_ok=True)
    return session


def cell_index(x: int, y: int) -> int:
    return y * GRID_COLS + x


def test_a_cell_that_only_moves_inside_the_fast_tier_is_fast(recon):
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    recon.map_animation(screen)
    assert cell_index(*FAST_CELL) in screen.animated_fast
    assert cell_index(*FAST_CELL) in screen.animated


def test_a_cell_that_only_moves_inside_the_slow_tier_is_not_fast(recon):
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    recon.map_animation(screen)
    assert cell_index(*SLOW_CELL) in screen.animated
    assert cell_index(*SLOW_CELL) not in screen.animated_fast


def test_animated_is_the_union_not_a_replacement(recon):
    """Every other place in this file that subtracts `screen.animated` to ignore
    self-motion has to keep ignoring slow motion too - `animated_fast` is additional
    classification, not a narrower `animated`."""
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    recon.map_animation(screen)
    assert screen.animated == screen.animated_fast | {cell_index(*SLOW_CELL)}


def test_a_cell_that_never_moves_is_in_neither(recon):
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    recon.map_animation(screen)
    assert cell_index(0, 0) not in screen.animated
    assert cell_index(0, 0) not in screen.animated_fast


def test_twelve_grabs_are_taken_six_per_tier(recon):
    """6 frames across 1s, then 6 more across 3s - not one long tier, not a different
    split. Wrong here is invisible in the boxes above (a merged tier still finds the
    right cells) and only shows up as sampling the wrong span."""
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    recon.map_animation(screen)
    assert recon.controller._calls == 12
