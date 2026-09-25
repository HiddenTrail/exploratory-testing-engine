"""Which of the four princess towers are still standing.

This is what the strategy needs first: "destroy one castle, then attack from that side".
Knowing a tower is gone changes where a card should be dropped, and nothing else in the
driver can tell.

What is measured, and the two detectors that did not work
--------------------------------------------------------
A tower's HP bar sits at a fixed spot above it. The instinct is to look for the bar's
colour - magenta for theirs, blue for ours - but **the coloured part shrinks as the tower
takes damage**, so a tower on 100 of 1400 shows almost none of it. Measured on
out/battle-m1-t120.png, their surviving left tower at 100 HP read 2% magenta against 15% for
a full one, while their destroyed right tower read 0%. A threshold there separates hurt from
healthy, not alive from dead.

The second instinct is the gold crown badge at the left end of each bar, which does not
shrink. That fails for a different reason: when a tower falls, the game paints the ground it
opened up in a **warm orange** no-deploy tint, and orange passes any reasonable test for
gold. That detector reported the *most* gold on the frames with the *fewest* towers.

What works is neither half on its own but the bar as a whole. A bar is a horizontal band
that is either filled or empty track, and the empty track is near-black; grass and orange
tint are neither. So the test is **filled or dark**, and the fraction of the box that is one
or the other. Measured across seven board frames: every destroyed tower read 0% or 1%, and
every standing one read 11% to 42%. `PRESENT` sits in that gap, which is wide.

This only means anything on the board
-------------------------------------
The result screen reads 87% to 94% and an off-board frame reads whatever happens to be
there. The reading is not self-validating - four dead towers is a real state late in a
match, so "all four gone" cannot be used to detect being off the board. The caller already
knows whether a match is running, from the card panel, and `read` must only be called when
it does.
"""
from __future__ import annotations

from dataclasses import dataclass

# The four HP bar boxes, measured on out/battle-m1-t000.png at 393x700, where their bars
# span x 70..130 and 270..330 at y 96..107, and ours sit at the mirrored depth. The box is
# the bar's own extent and no more: widening it to catch the crown badge would pull in
# grass, and every reading would drift toward the same middling number.
BARS = {
    "their-left":  (0.185, 0.138, 0.145, 0.016),
    "their-right": (0.695, 0.138, 0.145, 0.016),
    "our-left":    (0.185, 0.620, 0.145, 0.016),
    "our-right":   (0.695, 0.620, 0.145, 0.016),
}

# The band captured to read all four, chosen to cover both rows in one grab rather than
# four. It is a thin slice of a window, so it costs a small fraction of a full capture.
BAND = (0.180, 0.130, 0.665, 0.510)

PRESENT = 0.06   # fraction of a box that must be bar for the tower to be standing.
                 # Measured: dead 0-1%, standing 11-42%.
DARK = 95        # brightest channel below which a pixel is the bar's empty track
FILL = 60        # channel separation above which a pixel is a bar's filled colour


def is_bar(blue: int, green: int, red: int, theirs: bool) -> bool:
    """Whether one pixel belongs to an HP bar: its filled colour, or its empty track.

    Both halves are needed and neither is sufficient. Filled alone misses a nearly-dead
    tower; track alone cannot tell a full bar from no bar, because a full bar shows no
    track and neither does bare ground.
    """
    if max(blue, green, red) < DARK:
        return True
    if theirs:
        return red > 150 and blue > 110 and green < 130 and red - green > FILL
    return blue > 150 and red < 130 and blue - red > FILL


@dataclass(frozen=True)
class Towers:
    """Which of the four are standing, and what that means for where to attack."""
    their_left: bool
    their_right: bool
    our_left: bool
    our_right: bool

    @property
    def open_lane(self) -> str | None:
        """The lane where one of their towers has already fallen, if exactly one has.

        `None` when both stand - there is nothing to prefer yet - and `None` again when
        both are gone, because then the king tower is the only target and the choice of
        lane no longer follows from tower state. Saying "left" in that case would be
        inventing a reason.
        """
        if self.their_left == self.their_right:
            return None
        return "right" if self.their_left else "left"

    @property
    def exposed_lane(self) -> str | None:
        """The lane of ours whose tower has fallen: where their pushes will come.

        Same shape of answer as `open_lane` and for the same reason. Used to break ties
        when a defence could go either way, not to override a lane actually seen moving.
        """
        if self.our_left == self.our_right:
            return None
        return "left" if not self.our_left else "right"

    @property
    def crowns_for(self) -> int:
        return (not self.their_left) + (not self.their_right)

    @property
    def crowns_against(self) -> int:
        return (not self.our_left) + (not self.our_right)

    def line(self) -> str:
        def mark(alive: bool) -> str:
            return "O" if alive else "x"
        return (f"theirs {mark(self.their_left)}{mark(self.their_right)} "
                f"ours {mark(self.our_left)}{mark(self.our_right)} "
                f"{self.crowns_for}-{self.crowns_against}")


def fraction(band: bytes, width: int, height: int,
             box: tuple[float, float, float, float], theirs: bool) -> float:
    """Fraction of `box` - given as a fraction of `BAND` - that looks like an HP bar."""
    fx, fy, fw, fh = box
    left, top = int(fx * width), int(fy * height)
    right, bottom = int((fx + fw) * width), int((fy + fh) * height)
    hits = seen = 0
    for y in range(max(0, top), min(bottom + 1, height)):
        for x in range(max(0, left), min(right + 1, width)):
            index = (y * width + x) * 4
            seen += 1
            hits += is_bar(band[index], band[index + 1], band[index + 2], theirs)
    return hits / seen if seen else 0.0


def read_band(band: bytes, width: int, height: int) -> Towers:
    """The four towers out of one captured band. Split from `read` so the whole detector
    can be checked against a saved frame with no window anywhere."""
    import hand  # for `within`; imported here to keep this module's imports to the point

    standing = {}
    for name, box in BARS.items():
        inner = hand.within(BAND, box)
        standing[name] = fraction(band, width, height, inner,
                                  theirs=name.startswith("their")) >= PRESENT
    return Towers(their_left=standing["their-left"], their_right=standing["their-right"],
                  our_left=standing["our-left"], our_right=standing["our-right"])


def read(controller) -> Towers:
    band, width, height = controller.capture(region=BAND, longest=1400)
    return read_band(band, width, height)
