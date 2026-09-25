"""Where the fighting is, from one frame grab, so the driver can answer it instead of guess.

`battle.py` plays blind. It cycles three slots on a fixed clock and drops cards down two
lanes in a fixed 2:1 ratio, and it would send exactly the same gestures at an empty arena
as at a giant walking into its king tower. That is the whole of what "not intelligent"
means here, and it is what this module is for: one measurement per look, saying **which
quadrant of the arena is busy**.

Deliberately a change test rather than a content test. It compares two grabs of the same
grid and reports the fraction of cells that moved, per quadrant - it does not know what a
troop looks like, and nothing here has to be updated when the game reskins a card. Two
consequences worth stating because they are the reason the geometry below can be sloppy
at the edges:

  * **Static scenery is free.** The arena box runs nearly the full width of the window
    and takes in the decorative trees and rocks, because they were measured to be the
    same green as the playfield and cannot be trimmed away by colour. It does not matter:
    scenery that never moves contributes no change, so including it costs a few cells of
    resolution and nothing else.
  * **It cannot tell whose troops those are.** A change test sees movement, not
    allegiance. Activity in our own half is *usually* an enemy push, but it is also our
    own troops walking up the lane we just deployed into - so `Threat.trustworthy` is
    False for a short window after our own deploy in that lane, and the caller is
    expected to honour it.

**The two frames of a pair must be taken at the same point in the driver's loop**, and
this is not a nicety. `arena_preview.py` drew the boxes onto a real frame and the picture
showed why: the selected card's name ("3/4 Musketeer") is painted across the middle of
the arena, the tower HP bars sit inside it, and both come and go with what the driver
itself is doing. Compared across phases they read as activity - the two frames one second
apart that `battle.py` happens to have on disk score 25% and 27% in our own half on a
board where nothing was attacking us. Compared at the same phase they are identical and
cost nothing. So the driver holds one look per attempt and compares it to the *previous
attempt's* look: a whole cadence of real movement, with the interface frozen.

**The geometry is measured, not estimated**, off `out/battle-m1-t120.png` - a real frame
from a real match:

  * the **river at y 0.432**, found by scanning for rows where a quarter of the width is
    water-coloured; it reads 27-29% rather than more because the two bridges and the
    banks interrupt it. This is the line between their half and ours, and the only number
    here a wrong value would quietly corrupt - hence `arena_preview.py`, which draws
    these boxes onto a saved frame so they can be checked by eye.
  * the **card panel's top edge at y 0.809**, found the same way: below it, 100% of the
    width is the panel's flat blue. The arena stops there.

What is *not* settled, and is deliberately not implemented: telling their troops from
ours by colour. Team colours do separate strongly - counted per horizontal band on two
real frames, red-team pixels run 1700-3400 above the river against 85-230 below it - but
both of those frames were captured moments after a drag, when the game paints a **red
no-deploy overlay across the whole of enemy territory**. So the red above the river may
be troops or may be that overlay, and two frames taken mid-drag cannot tell the
difference. Settling it needs a frame grabbed with no card selected. Until then this
module stays with change, which has no such confound.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import changed_cells  # noqa: E402

# The playfield, as fractions of the client area. Top is just under the opponent's name
# banner; bottom is the measured top edge of the card panel. Left and right are generous
# for the reason the module docstring gives - a change test does not pay for scenery.
ARENA = (0.040, 0.085, 0.920, 0.724)
RIVER = 0.432        # measured: the water rows in battle-m1-t120.png
PANEL_TOP = 0.809    # measured: the first row that is 100% card-panel blue

# One grab per look, split in code afterwards. 12x20 is 240 cells: fine enough that a
# single troop moves more than one cell, coarse enough that the whole thing is one
# StretchBlt and a few hundred byte comparisons.
COLS, ROWS = 12, 20

# A quadrant counts as busy at this fraction of its own cells moving. Chosen against real
# frame pairs through `arena_preview.py` and not yet against a live grab, whose HALFTONE
# downsample that preview only approximates - so `Threat` carries the four fractions it
# was decided from, and a log of them can be argued with after the fact.
BUSY = 0.12

# How long our own deploy keeps poisoning the lane it went into. A troop dropped at the
# river takes a second or two to walk out of the cells it landed in, and during that time
# activity in our half is us, not them.
OURS_FOR = 2.5


def river_row(cols: int = COLS, rows: int = ROWS) -> int:
    """The first grid row that is on our side of the water.

    Derived rather than written down: the grid is defined over `ARENA`, so the row index
    of a window-space fraction is a calculation, and a hand-written index would silently
    stop meaning the river the moment the arena box moved.
    """
    _, top, _, height = ARENA
    return round((RIVER - top) / height * rows)


@dataclass(frozen=True)
class Threat:
    """What one look saw, in the four quadrants and as a conclusion.

    `trustworthy` is the honest part. Activity in our own half is only evidence about the
    opponent if we did not just put something there ourselves, and this class refuses to
    launder that away: a caller reading `lane` without reading `trustworthy` gets told
    about its own troops.
    """

    their_left: float
    their_right: float
    our_left: float
    our_right: float
    trustworthy: bool = True

    @property
    def lane(self) -> str | None:
        """Which lane is under attack in our half, or None. Busier wins a tie by margin."""
        left, right = self.our_left >= BUSY, self.our_right >= BUSY
        if left and right:
            return "left" if self.our_left > self.our_right else "right"
        if left:
            return "left"
        if right:
            return "right"
        return None

    @property
    def pressure(self) -> float:
        """How busy our own half is at all, either lane. The number a log should carry."""
        return max(self.our_left, self.our_right)

    def line(self) -> str:
        return (f"theirs L{self.their_left:.0%}/R{self.their_right:.0%} "
                f"ours L{self.our_left:.0%}/R{self.our_right:.0%} -> "
                f"{self.lane or 'quiet'}"
                f"{'' if self.trustworthy else ' (ours, ignored)'}")


def look(controller, verify: bool = False) -> bytes:
    """One grab of the arena grid. `verify=False` by default because this is called in a
    hot loop, where `Controller.grab`'s readability check would reach for a restart."""
    return controller.grab(COLS, ROWS, region=ARENA, verify=verify)


def quadrants(before: bytes, after: bytes, delta: int,
              cols: int = COLS, rows: int = ROWS) -> tuple[float, float, float, float]:
    """Fraction of cells that moved, as (their left, their right, our left, our right).

    Written as one pass over the grid rather than four `changed_cells` calls on four
    sliced buffers, because slicing a row-major grid into columns means rebuilding it -
    and this runs every look.
    """
    split_row = river_row(cols, rows)
    half = cols // 2
    counts = [0, 0, 0, 0]
    totals = [0, 0, 0, 0]
    for row in range(rows):
        for col in range(cols):
            index = (row * cols + col) * 4
            which = (0 if row < split_row else 2) + (0 if col < half else 1)
            totals[which] += 1
            if changed_cells(before[index:index + 4], after[index:index + 4], delta):
                counts[which] += 1
    return tuple(c / t if t else 0.0 for c, t in zip(counts, totals))


def read(before: bytes, after: bytes, delta: int, trustworthy: bool = True) -> Threat:
    return Threat(*quadrants(before, after, delta), trustworthy=trustworthy)


class Watch:
    """Holds the previous look, so a caller gets a `Threat` from one grab per attempt.

    The whole of the phase-locking rule from the module docstring lives here: `see` is
    meant to be called once per pass of the driver's loop, at the same point in it, and it
    compares against the last time it was called. The first call has nothing to compare
    with and says so - `None`, not a `Threat` full of zeroes that reads like a quiet board.
    """

    def __init__(self, delta: int, ours_for: float = OURS_FOR):
        self.delta = delta
        self.ours_for = ours_for
        self.previous: bytes | None = None
        self.deployed: dict[str, float] = {}
        self.looks = 0

    def deployed_into(self, lane: str, when: float) -> None:
        """Record that we put something in a lane, which taints it for `ours_for`."""
        self.deployed[lane] = when

    def see(self, controller, when: float) -> Threat | None:
        self.looks += 1
        current = look(controller)
        previous, self.previous = self.previous, current
        if previous is None:
            return None
        threat = read(previous, current, self.delta)
        if threat.lane and when - self.deployed.get(threat.lane, -1e9) < self.ours_for:
            return Threat(threat.their_left, threat.their_right,
                          threat.our_left, threat.our_right, trustworthy=False)
        return threat


def slots_for(lane: str, lanes: dict[int, float]) -> tuple[int, ...]:
    """Which card slots can legally reach a lane, given `battle.LANES`.

    A fact about the denylist, not a preference: slot 1 can only go left and slots 3 and 4
    can only go right, because slot 2's every path and slot 1's rightward path cross the
    Battle button's box. It is what makes defending either lane possible at all - there is
    at least one legal slot per side - and it is looked up rather than hardcoded so that
    the two files cannot drift apart.
    """
    want = min(lanes.values()) if lane == "left" else max(lanes.values())
    return tuple(slot for slot, x in sorted(lanes.items()) if x == want)
