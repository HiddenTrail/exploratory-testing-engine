"""`scroll_shift`: recognising that one frame is another with its content translated.

A scrollable surface is one place, but every scroll offset is a different picture, so
the identity test would mint a fresh screen per offset. `scroll_shift` reads the shape a
scroll leaves - pinned chrome, the rest translated by k cells, fresh content at the
leading edge - so that over-split can be avoided upstream. These build synthetic
fingerprints (3-byte BGR cells, the form `fingerprint` returns) so the geometry can be
checked with no client attached.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller import Target  # noqa: E402
from recon import (  # noqa: E402
    GRID_COLS, GRID_ROWS, Action, Recon, Screen, Variant, scroll_shift, variant_key,
)

DELTA = 10
CHROME = -1  # a row/column content id that stays put: the fixed bars a feed scrolls under


def cell(content_id: int, other: int) -> bytes:
    """A pseudo-random BGR cell, keyed on (content_id, position-on-the-other-axis).

    Hash-based rather than linear so that two different content ids look genuinely
    unrelated - a linear scheme lets a shift partially align rows that should not,
    which models a real screen badly and would mask false positives.
    """
    return hashlib.blake2s(f"{content_id}:{other}".encode(), digest_size=3).digest()


def rows_frame(row_ids: list[int]) -> bytes:
    """A frame whose content varies down the page: one content id per row."""
    out = bytearray()
    for row_id in row_ids:
        for col in range(GRID_COLS):
            out += cell(row_id, col)
    return bytes(out)


def cols_frame(col_ids: list[int]) -> bytes:
    """A frame whose content varies across the page: one content id per column."""
    out = bytearray()
    for row in range(GRID_ROWS):
        for col_id in col_ids:
            out += cell(col_id, row)
    return bytes(out)


def vertical_viewport(surface: list[int], offset: int) -> bytes:
    """The window onto a tall surface at `offset`, with row 0 fixed as chrome."""
    return rows_frame([CHROME] + [surface[offset + r] for r in range(1, GRID_ROWS)])


def horizontal_viewport(surface: list[int], offset: int) -> bytes:
    """The window onto a wide surface at `offset`, with column 0 fixed as chrome."""
    return cols_frame([CHROME] + [surface[offset + c] for c in range(1, GRID_COLS)])


def test_detects_vertical_scroll_and_its_magnitude():
    surface = list(range(100))  # every row distinct, so a shift is unambiguous
    before = vertical_viewport(surface, offset=10)
    after = vertical_viewport(surface, offset=7)  # content moves down by 3 rows

    shift = scroll_shift(before, after, DELTA)
    assert shift is not None
    assert shift.axis == "vertical"
    assert shift.magnitude == 3
    assert shift.direction == "down"
    assert shift.align < 15  # aligned overlap is near-identical (one chrome-boundary row aside)
    assert shift.revealed > 0  # fresh rows arrived at the leading edge


def test_detects_upward_scroll():
    surface = list(range(100))
    before = vertical_viewport(surface, offset=7)
    after = vertical_viewport(surface, offset=10)  # content moves up by 3
    shift = scroll_shift(before, after, DELTA)
    assert shift is not None
    assert shift.axis == "vertical"
    assert shift.magnitude == -3
    assert shift.direction == "up"


def test_detects_horizontal_scroll():
    surface = list(range(100))
    before = horizontal_viewport(surface, offset=10)
    after = horizontal_viewport(surface, offset=7)  # content moves right by 3
    shift = scroll_shift(before, after, DELTA)
    assert shift is not None
    assert shift.axis == "horizontal"
    assert shift.magnitude == 3
    assert shift.direction == "right"


def test_pinned_chrome_is_reported():
    surface = list(range(100))
    before = vertical_viewport(surface, offset=10)
    after = vertical_viewport(surface, offset=7)
    shift = scroll_shift(before, after, DELTA)
    # Row 0 (32 cells) is the fixed chrome and never moved.
    assert shift.pinned >= GRID_COLS


def test_unrelated_frames_are_not_a_scroll():
    a = rows_frame(list(range(GRID_ROWS)))
    b = rows_frame([100 + r for r in range(GRID_ROWS)])  # disjoint content, no shift aligns
    assert scroll_shift(a, b, DELTA) is None


def test_small_variant_is_not_a_scroll():
    base = list(range(GRID_ROWS))
    before = rows_frame(base)
    after = bytearray(before)
    # Change a single cell far below the moving-slab floor.
    after[0] = (after[0] + 200) % 256
    assert scroll_shift(before, bytes(after), DELTA) is None


def test_end_of_feed_reveals_nothing_and_is_not_a_scroll():
    # A scroll that hit the bottom: the frame did not change at all.
    surface = list(range(100))
    frame = vertical_viewport(surface, offset=10)
    assert scroll_shift(frame, frame, DELTA) is None


def test_wrong_sized_frame_returns_none():
    surface = list(range(100))
    ok = vertical_viewport(surface, offset=10)
    assert scroll_shift(ok, ok[:-3], DELTA) is None


# --- integration: _record must not mint a screen per scroll offset -----------

class FakeController:
    """Enough of a controller for `_record`, which never grabs in the scrolled path."""

    def __init__(self) -> None:
        self.target = Target(name="Fake", exe="")
        self.saved: list = []

    def save_png(self, path) -> None:
        # The scrolled branch captures the offset frame; a no-op stub is enough here.
        self.saved.append(path)


def _screen_showing(fp: bytes) -> Screen:
    variant = Variant(id="v1", key=variant_key(fp), fp=fp)
    screen = Screen(id="sc01", representative=fp, first_seen=0)
    screen.variants[variant.key] = variant
    return screen


def test_record_treats_translated_scroll_as_the_same_surface(tmp_path):
    surface = list(range(100))
    before = vertical_viewport(surface, offset=10)
    after = vertical_viewport(surface, offset=7)  # content moved down 3 rows

    session = Recon(FakeController(), tmp_path)
    screen = _screen_showing(before)
    session.screens[screen.id] = screen
    session.standing = screen.id

    transition, is_new = session._record(
        screen, Action("scroll", at=(0.5, 0.5), notches=-3), before, after, settle_ms=120)

    assert transition.kind == "scrolled"
    assert transition.dest == screen.id          # did NOT mint a new screen
    assert transition.shift_axis == "vertical"
    assert transition.shift_magnitude == 3
    assert is_new is False
    assert len(session.screens) == 1             # the over-split is prevented
    assert screen.scroll_axes == {"vertical"}
    assert screen.scroll_steps == 1
    assert session.standing == screen.id         # stayed on the same surface


def test_record_scroll_that_moved_nothing_is_not_a_surface(tmp_path):
    surface = list(range(100))
    frame = vertical_viewport(surface, offset=10)

    session = Recon(FakeController(), tmp_path)
    screen = _screen_showing(frame)
    session.screens[screen.id] = screen
    session.standing = screen.id

    transition, _ = session._record(
        screen, Action("scroll", at=(0.5, 0.5), notches=-3), frame, frame, settle_ms=100)

    assert transition.kind == "none"
    assert screen.scroll_steps == 0
