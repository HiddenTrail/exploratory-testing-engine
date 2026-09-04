"""Do `hand` and `towers` read a saved frame the way a person reads it?

The other two test files check decisions. This one checks perception, and it is the only
place in the experiment where the expected values were read **off the picture by eye** rather
than derived from anything the code does. That distinction is the whole value of the file: a
reader test whose expectations came from running the reader passes forever and detects
nothing.

The labels below were read from 2x crops of the panel band and the tower bars. The Minions /
Arrows / empty / greyed-Giant row in `battle-m1-t120` is the clearest of them - card art, two
pink 3s, a grey 5, a crown watermark where the third card should be, and a bar labelled 3
with a fourth segment part-filled that the reader is expected to *not* count.

Skipping rather than failing
---------------------------
`out/` is gitignored: the frames are screenshots of a real account's client and they are
several megabytes. So every test here skips when its frame is missing, and the suite stays
green on a fresh clone. That is a real gap - it means CI cannot catch a regression in the
readers - and the mitigation is that the readers are pure functions of a buffer, so anyone
with a client can regenerate the frames by running one match.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "game-screen-probe"))

import hand as hand_module  # noqa: E402
import towers as towers_module  # noqa: E402
from probe import read_png  # noqa: E402

OUT = HERE / "out"


def band(frame: str, box: tuple[float, float, float, float]):
    """One region of a saved frame, at native pixels, in the layout a capture would give.

    The readers take `(bgra, width, height)` and do not care where it came from, which is
    what makes them testable at all - `read_band` exists precisely so that neither of them
    needs a window to be checked.
    """
    path = OUT / f"{frame}.png"
    if not path.exists():
        pytest.skip(f"{path.name} is gitignored - run a match to regenerate it")
    pixels, width, height = read_png(str(path))
    fx, fy, fw, fh = box
    left, top = int(fx * width), int(fy * height)
    right, bottom = int((fx + fw) * width), int((fy + fh) * height)
    out = bytearray()
    for y in range(top, bottom):
        out += pixels[(y * width + left) * 4:(y * width + right) * 4]
    return bytes(out), right - left, bottom - top


def hand_in(frame: str):
    return hand_module.read_band(*band(frame, hand_module.PANEL))


def towers_in(frame: str):
    return towers_module.read_band(*band(frame, towers_module.BAND))


# --- the hand ----------------------------------------------------------------

def test_the_clearest_panel_reads_exactly_as_it_looks():
    """Minions, Arrows, an empty slot, a greyed Giant, and three elixir. Every one of the
    three states the panel can be in appears once in this row, which is why it is the frame
    the geometry was measured on."""
    read = hand_in("battle-m1-t120")
    assert [s.card for s in read.slots] == ["minions", "arrows", None, "giant"]
    assert [s.state for s in read.slots] == ["ready", "ready", "empty", "grey"]
    assert read.elixir == 3


def test_a_part_filled_elixir_segment_is_not_counted():
    """The bar in that frame is labelled 3 with the fourth segment visibly part-filled, and
    the reader is sampled at each segment's right edge so it reads 3. Under-reading is the
    safe direction: the number is only ever used to decide whether *waiting* would help, so
    reading low makes the driver wait and reading high makes it try to spend elixir it does
    not have."""
    assert hand_in("battle-m1-t120").elixir == 3
    assert hand_in("battle-m1-t000").elixir == 8


def test_an_opening_hand_reads_four_named_cards_and_no_grey():
    """The frame the card library was cut from. Nothing greyed, nothing empty, all four
    named - which is the only state where a failure to name a card cannot be blamed on
    greying or on a slot mid-deal."""
    read = hand_in("battle-m1-t000")
    assert all(s.state == "ready" for s in read.slots)
    assert all(s.card for s in read.slots), [s.line() for s in read.slots]


def test_a_greyed_card_is_still_recognised_as_the_card_it_is():
    """The property the whole holding behaviour rests on. `signature` is mean-removed
    luminance, so a card drawn in greyscale still matches its colour exemplar - a driver
    that could only name affordable cards could not plan one pass ahead."""
    read = hand_in("battle-m1-t060")
    greyed = [s for s in read.slots if s.state == "grey"]
    assert len(greyed) == 3
    assert [s.card for s in greyed] == ["knight", "giant", "arrows"]


def test_the_three_states_are_separated_by_the_margins_they_were_measured_with():
    """Not a re-assertion of the thresholds but of the gaps around them: greyed cards near
    zero saturation, live cards in the middle, empty slots near one. If a client update
    restyled the panel these numbers would drift long before any card stopped being named,
    so this is the test that fails first."""
    seen = {"grey": [], "ready": [], "empty": []}
    for frame in ("battle-m1-t000", "battle-m1-t060", "battle-m1-t120"):
        for slot in hand_in(frame).slots:
            seen[slot.state].append(slot.saturation)
    assert max(seen["grey"]) < hand_module.GREY_BELOW
    assert min(seen["ready"]) > hand_module.GREY_BELOW
    assert max(seen["ready"]) < hand_module.EMPTY_ABOVE
    assert min(seen["empty"]) > hand_module.EMPTY_ABOVE


def test_a_frame_that_is_not_a_board_names_nothing():
    """An off-board frame is the honest negative: the boxes land on interface that is not
    cards, and every one of them comes back unnamed rather than as the nearest card in the
    library. This is what `MATCH_LIMIT` is for, and a limit set too loose would show up
    here as a confident reading of a menu."""
    read = hand_in("battle-no-board")
    assert all(s.card is None for s in read.slots), [s.line() for s in read.slots]
    assert min(s.gap for s in read.slots) > 15, "and not by a narrow margin"


# --- the towers --------------------------------------------------------------

def test_a_fresh_board_reads_all_four_towers_standing():
    read = towers_in("battle-m1-t000")
    assert (read.crowns_for, read.crowns_against) == (0, 0)
    assert read.open_lane is None and read.exposed_lane is None


def test_a_tower_on_almost_no_health_still_reads_as_standing():
    """The reason the detector is "filled or dark" rather than "filled". In this frame their
    left tower is on about 100 of 1400 and shows 2% of its bar's colour against 15% for a
    full one - a colour threshold there separates hurt from healthy. Their right tower is
    gone in the same frame, so both halves of the distinction are on one picture."""
    read = towers_in("battle-m1-t120")
    assert read.their_left is True
    assert read.their_right is False
    assert read.open_lane == "right"


def test_the_ground_a_fallen_tower_opens_is_not_mistaken_for_the_tower():
    """The detector that failed: the game tints the newly-deployable ground warm orange, and
    orange passes any reasonable test for the gold crown badge. That version reported the
    most gold on the frames with the fewest towers, so this asserts the direction - a frame
    with fewer towers must read fewer towers."""
    early = towers_in("battle-m1-t000").crowns_for
    late = towers_in("battle-m1-end").crowns_for
    assert early < late == 2


def test_our_own_towers_are_read_by_their_own_colour():
    """Ours are blue and theirs magenta, and `is_bar` is asked which it is looking at rather
    than accepting either. A single colour-blind test would read the wrong half of the board
    as fine whenever the two halves disagreed - which is every interesting frame."""
    read = towers_in("battle-m1-t120")
    assert (read.our_left, read.our_right) == (False, True)
    assert read.exposed_lane == "left"
    assert read.crowns_against == 1


def test_every_board_frame_reads_inside_the_measured_gap():
    """The gap `PRESENT` sits in was measured as dead 0-1% against standing 11-42%. This
    walks every board frame and asserts no box lands between 2% and 10%, i.e. that the
    threshold is still being asked an easy question rather than a close one."""
    for frame in ("battle-m1-t000", "battle-m1-t060", "battle-m1-t120", "battle-t030",
                  "battle-t060", "battle-t121"):
        pixels, width, height = band(frame, towers_module.BAND)
        for name, box in towers_module.BARS.items():
            inner = hand_module.within(towers_module.BAND, box)
            got = towers_module.fraction(pixels, width, height, inner,
                                         theirs=name.startswith("their"))
            assert got <= 0.02 or got >= 0.10, f"{frame} {name} read {got:.0%}, too close"


# --- the two together --------------------------------------------------------

def test_the_two_readers_use_bands_that_do_not_overlap():
    """They are separate captures because they are in different parts of the window, and if
    the bands ever met it would be cheaper to take one. Asserted so that a later edit which
    widens either band has to notice."""
    _, panel_top = hand_module.PANEL[1], hand_module.PANEL[1]
    band_bottom = towers_module.BAND[1] + towers_module.BAND[3]
    assert band_bottom < panel_top, "the tower band ends above the card panel"


def test_a_reading_of_the_same_frame_twice_is_the_same_reading():
    """Neither reader keeps state, and both are called several times a second. Stated as a
    test because both of them import lazily - `hand.library()` and `towers.read_band`'s
    import of `hand` - and a lazy import that mutated anything would show up here."""
    assert hand_in("battle-m1-t120") == hand_in("battle-m1-t120")
    assert towers_in("battle-m1-t120") == towers_in("battle-m1-t120")
