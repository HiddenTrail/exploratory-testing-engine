"""What is in the hand, what it costs, and whether it can be paid for.

This is a **content** test, unlike `arena.py`, and it is allowed to be one because the
thing it reads does not move: the card panel is a fixed strip of interface with four fixed
boxes in it, and the artwork inside a box is one of eight static pictures.

Three things come out of one capture of the panel:

**Whether a slot can be played at all.** The game answers this itself. A card the player
cannot afford is drawn in **greyscale**, and an empty slot - a card still being dealt - is
flat panel blue with a crown watermark. Mean saturation separates the three states with
enormous margins: measured across 28 labelled slots, greyed cards read **0.06**, live cards
**0.38 to 0.65**, and empty slots **0.97**. So affordability does not have to be inferred
from an elixir count and a cost table; it is read off the card. That matters because the
inferred version is wrong whenever either input is wrong, while this version is the game's
own opinion.

**Which card it is.** A mean-removed 6x6 luminance signature, matched against the exemplars
in `cards.py` by nearest neighbour, and answering `None` above `cards.MATCH_LIMIT`. See
`reference.py` for why luminance, why several exemplars, and how the limit was measured. A
card this cannot name is not a failure to route around - it is reported, and the caller
treats an unnamed card as "playable, purpose unknown", which is exactly what the driver did
before it could read the panel at all.

**How much elixir there is.** The bar under the cards is ten discrete segments and the fill
is exactly linear: at 393x700, sampling row y 0.980 across the bar gave 32 filled samples
of 40 at 8 elixir, 12 at 3 and 8 at 2 - four samples per elixir, no rounding needed. This
is *not* used to decide affordability, because the grey test already answers that better.
It is used to decide whether to **wait**: a Giant at 5 with 4 elixir showing is worth
holding a pass for, and nothing else in the driver can tell the difference between that and
a card that will never be affordable.

Why one capture and a Python downsample
---------------------------------------
`Controller.grab` downsamples through GDI's HALFTONE StretchBlt; `reference.py` builds the
library with `probe.thumbnail_from_bgra`, a block average. The two do not agree closely
enough to build a library with one and match with the other. So the panel is captured once
at native pixels and every box is cut out of that buffer in Python, through the same
function the library was built with. One capture also costs less than five: the band is
about 18% of the window.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "game-screen-probe"))

from probe import thumbnail_from_bgra  # noqa: E402

# The panel band: everything from just above the cards to the bottom of the window. Cut
# once, and every box below is expressed as a fraction of the *window* and converted, so
# the numbers here can be compared directly with the ones in battle.py and arena.py.
PANEL = (0.0, 0.815, 1.0, 0.185)

# Card geometry, measured on out/battle-m1-t000.png at 393x700, where the four cards span
# x 89..155, 163..229, 237..303 and 311..377: centres 0.310, 0.498, 0.686, 0.874 at a pitch
# of 0.188. WIDTH is inside the artwork rather than on the card's border, and HEIGHT stops
# above the pink cost circle - the circle is the one part of a card that changes colour with
# affordability, and a signature that included it would be reading the state twice.
SLOT_FIRST, SLOT_PITCH, SLOT_WIDTH = 0.310, 0.188, 0.140
SLOT_TOP, SLOT_HEIGHT = 0.828, 0.085
SLOT_COLS, SLOT_ROWS = 6, 6

EMPTY_ABOVE = 0.85   # mean saturation at or above which the slot holds no card. Measured
                     # 0.97 on four empty slots against 0.65 for the most colourful card.
GREY_BELOW = 0.20    # and at or below which the card is greyed. Measured 0.06 on ten
                     # greyed cards against 0.38 for the dullest live one. The gap either
                     # side is wide enough that neither number is delicate.

# The elixir bar, measured on the same frame: the pink runs from x 0.276 to 0.964 at row
# y 0.980, ten segments across. Sampled at each segment's *right* edge rather than its
# centre, which under-reads a part-filled segment - the safe direction, since this number
# is only ever used to decide whether waiting would help.
ELIXIR_LEFT, ELIXIR_RIGHT, ELIXIR_ROW = 0.276, 0.964, 0.980
ELIXIR_MAX = 10
ELIXIR_RED = 60      # red channel above which a segment counts as filled. The bar is not
                     # one flat magenta: it is shaded, and along the sampled row red runs
                     # 215 at the left end down to 136 in the middle and back to 152. The
                     # first version of this test wanted red above 150 and so read 3 where
                     # the bar plainly showed 8. The empty track behind the bar is dark
                     # navy - red 2 to 8 - so the gap to aim at is enormous and the
                     # brightness of the magenta is not the thing to measure.


sys.path.insert(0, str(HERE))


def library():
    """`cards.py`, imported on first use rather than at module load.

    Not a style choice: `reference.py` *writes* `cards.py`, and it needs the geometry and
    the signature function from this file to do it. Importing the library at the top would
    make the generator unrunnable whenever its own output was missing - which is precisely
    when it needs to run.
    """
    import cards
    return cards


def slot_box(slot: int) -> tuple[float, float, float, float]:
    """The artwork of one slot, as a fraction of the window. Slots are 1-based."""
    centre = SLOT_FIRST + (slot - 1) * SLOT_PITCH
    return (centre - SLOT_WIDTH / 2, SLOT_TOP, SLOT_WIDTH, SLOT_HEIGHT)


def within(outer: tuple[float, float, float, float],
           inner: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """`inner`, a box in window fractions, re-expressed as a fraction of `outer`.

    Exists so that every box in this file can be written as a fraction of the window - the
    same units as every other measurement in this experiment - while still being cut out of
    a capture of a band rather than out of a capture of the whole window. Doing that
    conversion at each call site is four chances to divide by the wrong number.
    """
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ((ix - ox) / ow, (iy - oy) / oh, iw / ow, ih / oh)


def saturation(cells: bytes) -> float:
    """Mean saturation of a BGRA buffer, 0 for grey and 1 for a pure hue."""
    total = 0.0
    for index in range(0, len(cells), 4):
        blue, green, red = cells[index], cells[index + 1], cells[index + 2]
        high, low = max(blue, green, red), min(blue, green, red)
        total += (high - low) / high if high else 0.0
    return total / (len(cells) // 4)


def signature(cells: bytes) -> tuple[int, ...]:
    """A mean-removed luminance pattern: what the picture looks like, not how bright."""
    luminance = [(cells[i] * 29 + cells[i + 1] * 150 + cells[i + 2] * 77) >> 8
                 for i in range(0, len(cells), 4)]
    mean = sum(luminance) / len(luminance)
    return tuple(round(value - mean) for value in luminance)


def distance(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def name_of(cells: bytes, state: str) -> tuple[str | None, float]:
    """Nearest card in the library, and how far away it was.

    Returns `(None, distance)` past `cards.MATCH_LIMIT`. The distance comes back either
    way so a log can show a near miss - a run whose every card reads unknown at 19 is a
    library that needs one more exemplar, and a run whose every card reads unknown at 60 is
    geometry that has moved. Those need different fixes and the number is what tells them
    apart.

    **Greyed cards are matched only against greyed exemplars**, and colour against colour.
    This is not a refinement, it is the fix for a measured failure. A greyed card carries an
    animated diagonal shine, and a mean-removed luminance signature of a card with a bright
    band across it is mostly that band - so greyed cards resemble *each other* more than they
    resemble their own colour artwork. Scored against one combined library, every single
    exemplar that failed leave-one-out was a greyed one, and each was nearest to a greyed
    card of a different name. Splitting by a state the reader already knows before it matches
    costs nothing and removes the whole confound.

    The cost is that a card with no exemplar in the state it is seen in reads unknown rather
    than guessing across states. That is the same bargain the rest of this module makes: the
    library never has to be right, it has to never be confidently wrong.
    """
    known = library()
    mine = signature(cells)
    best, found = None, float("inf")
    for name, exemplars in known.SIGNATURES.get(state, {}).items():
        for exemplar in exemplars:
            gap = distance(mine, exemplar)
            if gap < found:
                best, found = name, gap
    return (best if found <= known.MATCH_LIMIT else None), found


@dataclass(frozen=True)
class Slot:
    """One card position: what state it is in, and what is in it if anything."""
    slot: int
    state: str                 # "empty" | "grey" | "ready"
    card: str | None = None    # None when unnamed, and when there is nothing to name
    gap: float = 0.0           # distance to the nearest exemplar
    saturation: float = 0.0

    @property
    def playable(self) -> bool:
        return self.state == "ready"

    @property
    def cost(self) -> int | None:
        return library().COST.get(self.card) if self.card else None

    @property
    def role(self) -> str | None:
        return library().ROLE.get(self.card) if self.card else None

    def line(self) -> str:
        if self.state == "empty":
            return f"{self.slot}:-"
        named = self.card or f"?{self.gap:.0f}"
        return f"{self.slot}:{named}{'' if self.playable else '(grey)'}"


@dataclass(frozen=True)
class Hand:
    """The four slots and the elixir, as one reading."""
    slots: tuple[Slot, ...]
    elixir: int

    def ready(self) -> tuple[Slot, ...]:
        return tuple(s for s in self.slots if s.playable)

    def by_role(self, role: str) -> tuple[Slot, ...]:
        return tuple(s for s in self.ready() if s.role == role)

    def unnamed(self) -> tuple[Slot, ...]:
        """Playable cards this could not put a name to. Not an error - see the module
        docstring. Kept separate so the policy can fall back to them last rather than
        treating an unknown card as though it had no role by choice."""
        return tuple(s for s in self.ready() if s.card is None)

    def affordable_soon(self, cost: int) -> bool:
        """Whether `cost` is *exactly* one elixir out of reach right now.

        The only question the elixir count is asked, and the reason it is read at all.

        Both bounds matter and the first version had only the upper one - `elixir + 1 >=
        cost` - which is also true at 10 elixir for a 5-cost card. That combination should
        be impossible, because a greyed card is the game saying it cannot be paid for, so a
        greyed 5 alongside a full bar means one of the two readings is wrong. It is reachable
        anyway: an off-board frame reads whatever happens to be under the boxes. Without the
        lower bound the caller holds for that card, finds it still greyed, holds again, and
        spends the rest of the match waiting for an elixir it already has. With it, a
        self-contradictory reading resolves toward playing something rather than toward
        stalling, which is the safe direction for a driver that cannot re-read its way out.
        """
        return self.elixir < cost <= self.elixir + 1

    def line(self) -> str:
        return f"{self.elixir:2d}e " + " ".join(s.line() for s in self.slots)


def elixir_from(band: bytes, width: int, height: int) -> int:
    """Count filled segments of the elixir bar in a captured panel band.

    Ten samples, one at each segment's right edge, and the count stops at the first empty
    one rather than counting all ten. A bar is filled left to right, so a gap means
    something is being read that is not the bar - and stopping short reports a low number,
    which makes the driver wait, rather than a high one, which would make it try to spend
    elixir it does not have.
    """
    row = int(within(PANEL, (0, ELIXIR_ROW, 1, 0))[1] * height)
    row = min(max(row, 0), height - 1)
    filled = 0
    for segment in range(1, ELIXIR_MAX + 1):
        fx = ELIXIR_LEFT + (ELIXIR_RIGHT - ELIXIR_LEFT) * segment / ELIXIR_MAX
        column = min(int(fx * width), width - 1)
        index = (row * width + column) * 4
        _, green, red = band[index], band[index + 1], band[index + 2]
        if not (red > ELIXIR_RED and red > green):
            break
        filled = segment
    return filled


def read_band(band: bytes, width: int, height: int) -> Hand:
    """Everything, out of one captured panel band. Split from `read` so the whole reader
    can be tested against a saved frame with no window anywhere."""
    slots = []
    for slot in range(1, 5):
        box = within(PANEL, slot_box(slot))
        cells = thumbnail_from_bgra(band, width, height, SLOT_COLS, SLOT_ROWS, box)
        how_saturated = saturation(cells)
        if how_saturated >= EMPTY_ABOVE:
            slots.append(Slot(slot, "empty", saturation=how_saturated))
            continue
        state = "grey" if how_saturated <= GREY_BELOW else "ready"
        name, gap = name_of(cells, state)
        slots.append(Slot(slot, state, card=name, gap=gap, saturation=how_saturated))
    return Hand(tuple(slots), elixir_from(band, width, height))


def read(controller) -> Hand:
    band, width, height = controller.capture(region=PANEL, longest=1400)
    return read_band(band, width, height)
