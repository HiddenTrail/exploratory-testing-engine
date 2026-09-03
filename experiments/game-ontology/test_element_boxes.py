"""Where a control actually is: the box a model draws, the pixels that trim it, and what
the harness does when the trim cannot answer.

The claim under test is that a coordinate in the map is a *measurement*. Before this, an
element's `at` was whatever the vetting call read off a screenshot scaled to 1400px, and
the only thing checking it was `is_fraction` - so a point 40px off the control it named,
or the middle of a neighbourhood rather than the middle of a button, was indistinguishable
in the output from a point measured against the window. Now the pixels inside the model's
box decide, and every way that can fail is recorded as a sentence rather than absorbed.
That last part is what most of this file is about: a fallback that reports itself
is a fallback a reader can price, and a silent one turns a systematic model error into a
map that merely looks slightly inaccurate.

`content_box` is pure and gets synthetic patches: a rectangle drawn on a flat field, whose
answer is known exactly, which is the one thing no real game can provide.

Runs under pytest, or standalone with
`python experiments/game-ontology/test_element_boxes.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from controller import (INK_DELTA, Target, background_colour,  # noqa: E402
                        content_box)
from recon import (ELEMENT_DEFAULT, ELEMENT_LOCATES, ELEMENT_PAD,  # noqa: E402
                   ELEMENT_PAD_MAX, ELEMENT_SAMPLES, ELEMENT_SAMPLES_MAX,
                   GRID_COLS, Recon, Screen, Variant, as_box, box_around,
                   box_cells, box_centre, element_kind, pad_box)

BACK = (40, 30, 30)        # BGR. A dark panel, like most of the game this was cut against
PLATE = (200, 180, 120)    # and a button plate on it


def patch(width: int, height: int, *boxes, back=BACK, plate=PLATE) -> bytes:
    """A BGRA buffer of `plate` on `back`. Each box is a half-open pixel rectangle.

    Several, because the interesting shape is not one rectangle: content that reaches every
    edge of the patch while a background still exists to measure against has to be a cross
    or a frame, and a single rectangle that touches all four edges *is* the patch."""
    drawn = [b for b in boxes if b is not None]
    out = bytearray()
    for y in range(height):
        for x in range(width):
            inside = any(b[0] <= x < b[2] and b[1] <= y < b[3] for b in drawn)
            b, g, r = plate if inside else back
            out += bytes((b, g, r, 255))
    return bytes(out)


def cross(width: int, height: int, thickness: int = 5) -> tuple:
    """A `drawing` whose content spans the full width *and* the full height.

    A button flush against a full-width bar of a different colour, in the abstract: real
    edges on neither axis, and a background still present in the corners for
    `background_colour` to find."""
    mid_x, mid_y = width // 2, height // 2
    return (width, height,
            (0, mid_y - thickness, width, mid_y + thickness),
            (mid_x - thickness, 0, mid_x + thickness, height))


class FakeController:
    """A window that renders one synthetic patch, and remembers what was asked of it.

    `capture` ignores the region's *content* and answers with the same drawing every time,
    scaled to the requested sample grid - which is exactly the seam under test: `snap_box`
    is responsible for turning sample coordinates back into fractions of the window, and a
    fake that returned the region already in fractions would test nothing.
    """

    def __init__(self, drawing=None, fingerprint_bytes: bytes | None = None) -> None:
        self.target = Target(name="Fake", exe="")
        self.notes: list[str] = []
        self.captures: list[tuple] = []
        self.sampled: list[int] = []
        self.written: list[Path] = []
        # A portrait phone window, because the shape of the client is an input to how many
        # samples a patch is trimmed at - see `Recon.patch_samples`.
        self.last_good_rect = (0, 0, 1120, 2000)
        # (width, height, *boxes) of what any grab of any region comes back with.
        self.drawing = drawing or (120, 120, (30, 40, 90, 80))
        self.fp = fingerprint_bytes or bytes(GRID_COLS * 18 * 3)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def say(self, message: str) -> None:
        pass

    def grab(self, cols: int, rows: int, region=(0.0, 0.0, 1.0, 1.0), verify=True) -> bytes:
        # `fingerprint` strips the alpha byte, so this has to be BGRA like the real one.
        return bytes(self.fp[(i // 4) * 3 + i % 4] if i % 4 < 3 else 255
                     for i in range(cols * rows * 4))

    def capture(self, region=(0.0, 0.0, 1.0, 1.0), longest: int = 1400):
        self.captures.append(region)
        self.sampled.append(longest)
        width, height = self.drawing[0], self.drawing[1]
        return patch(*self.drawing), width, height

    def write_capture(self, path: Path, frame) -> tuple[int, int]:
        self.written.append(path)
        return frame[1], frame[2]


def trim_patch(hint: tuple) -> tuple:
    """The patch `snap_box` will read for `hint`. Spelled once, because the padding rule has
    two parts - a fraction of the box, capped in fractions of the window - and a test that
    reimplemented only the first half would pass on small boxes and lie about large ones."""
    return pad_box(hint, ELEMENT_PAD, ELEMENT_PAD_MAX)


def session(tmp_path: Path, controller: FakeController) -> Recon:
    recon = Recon(controller, tmp_path)
    recon.images.mkdir(parents=True, exist_ok=True)
    return recon


def screen_with(elements: list[dict], animated: set[int] | None = None,
                fp: bytes = b"") -> tuple[Screen, Variant]:
    screen = Screen(id="sc01", representative=fp, first_seen=0)
    screen.vetting = {"name": "Lobby", "actions": {}, "elements": elements}
    screen.animated = animated or set()
    variant = Variant(id="sc01v1", key="k", fp=fp)
    screen.variants[variant.id] = variant
    return screen, variant


# --- the pure trim ----------------------------------------------------------

def test_a_rectangle_on_a_flat_field_is_found_to_the_pixel():
    found = content_box(patch(100, 80, (20, 15, 60, 55)), 100, 80)
    assert found == (20, 15, 60, 55)


def test_a_flat_patch_reports_no_content_rather_than_a_default():
    """The measurement "there is no control here", which is what tells a box aimed at empty
    panel apart from one aimed at a button. Returning the whole patch instead - the obvious
    "safe" fallback - would make those two cases produce the same rectangle."""
    assert content_box(patch(60, 60, None), 60, 60) is None


def test_content_reaching_every_edge_comes_back_as_the_full_span():
    """Not None, and not trimmed: the caller is the only one who knows how much margin it
    asked for, so it is the only one that can read this as "the thing overflows"."""
    assert content_box(patch(*cross(40, 40)), 40, 40) == (0, 0, 40, 40)


def test_one_stray_pixel_does_not_set_the_bound():
    """`INK_FRACTION` exists for antialiased edges, drop shadows and lone highlights. The
    bound is what a tap gets aimed at, so a single bright pixel two thirds of the way up a
    panel must not become the top of the control."""
    pixels = bytearray(patch(80, 80, (30, 30, 50, 50)))
    for channel, value in enumerate(PLATE):
        pixels[(5 * 80 + 70) * 4 + channel] = value
    assert content_box(bytes(pixels), 80, 80) == (30, 30, 50, 50)


def test_the_background_is_the_ring_not_the_middle():
    """A patch that is mostly button still has to be measured against its panel. Read off
    the middle instead and the trim inverts: it finds the panel and calls it the control."""
    assert background_colour(patch(40, 40, (2, 2, 38, 38)), 40, 40)[:3] == (
        BACK[0] // 16 * 16 + 8, BACK[1] // 16 * 16 + 8, BACK[2] // 16 * 16 + 8)


def test_a_control_within_the_ink_threshold_of_its_panel_is_not_found():
    """Stated as a limit rather than left to be discovered. A control drawn a few levels
    from its own background is invisible to this, `snap_box` says so, and the box stays the
    model's - which is the honest outcome and not a bug to be tuned away with a lower
    threshold, because that threshold is also what keeps gradient noise out."""
    near = (BACK[0] + INK_DELTA - 2, BACK[1], BACK[2])
    assert content_box(patch(60, 60, (10, 10, 50, 50), plate=near), 60, 60) is None


# --- reading a model's rectangle --------------------------------------------

def test_pixels_are_refused_where_fractions_are_expected():
    """The failure this shares with `is_fraction`: one real map holds `at: [697, 190]`,
    pixels of the screenshot the annotator was shown, which as a fraction is a thousand
    windows away. A box has four numbers to get wrong instead of two."""
    assert as_box([697, 190, 120, 40]) is None


def test_a_box_hanging_off_the_edge_is_clamped_and_kept():
    """The commonest way to describe a control *against* an edge, and those are the ones
    worth having - a corner arrow, a bottom navigation bar."""
    assert as_box([-0.05, 0.94, 0.2, 0.1]) == pytest.approx((0.0, 0.94, 0.15, 0.06))


@pytest.mark.parametrize("box", [
    [0.4, 0.4, 0.0, 0.1],        # no width
    [0.4, 0.4, 0.2, 0.001],      # a hairline
    [0.0, 0.0, 1.0, 0.9],        # most of the window: a screen, not an element
    [0.4, 0.4],                  # a point wearing a box's name
    "the battle button",
    None,
])
def test_a_box_that_is_not_one_control_is_refused(box):
    assert as_box(box) is None


def test_padding_grows_a_box_by_its_own_size_and_stays_on_the_window():
    padded = pad_box((0.40, 0.70, 0.20, 0.08), 0.5)
    assert padded == pytest.approx((0.30, 0.66, 0.40, 0.16))
    assert pad_box((0.0, 0.0, 0.2, 0.2), 1.0) == pytest.approx((0.0, 0.0, 0.4, 0.4))


def test_a_point_grows_to_a_box_centred_on_itself():
    box = box_around((0.5, 0.5), ELEMENT_DEFAULT)
    assert box_centre(box) == pytest.approx((0.5, 0.5))
    assert (box[2], box[3]) == pytest.approx(ELEMENT_DEFAULT)


def test_an_unrecognised_kind_becomes_other_rather_than_taking_a_measurement_path():
    """`kind` is read in exactly one place - the choice of how to measure the box - so an
    unknown value must land on the ordinary path and not near-miss its way onto the
    animation one, which would replace a trim with an intersection against a mask."""
    assert element_kind({"kind": "Button"}) == "button"
    assert element_kind({"kind": "animated"}) == "other"
    assert element_kind({}) == "other"


def test_a_box_maps_onto_the_cells_it_covers():
    """Only used to check a claim against a mask, never to build a box."""
    assert box_cells((0.0, 0.0, 1.0 / GRID_COLS, 1.0 / 18)) == {0}
    assert len(box_cells((0.0, 0.0, 1.0, 1.0))) == GRID_COLS * 18


# --- the trim against a window ----------------------------------------------

def test_a_hint_is_trimmed_to_the_plate_inside_it(tmp_path):
    """The whole point. The hint is a loose box; the answer is the plate's own rectangle,
    expressed back in fractions of the window rather than in samples of the patch."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (25, 25, 75, 75))))
    hint = (0.40, 0.70, 0.20, 0.08)
    box, why, kept = recon.snap_box(hint)
    assert why == ""
    padded = trim_patch(hint)
    # A quarter in from each edge of the padded patch, which is what the drawing is.
    assert box == pytest.approx((padded[0] + padded[2] * 0.25, padded[1] + padded[3] * 0.25,
                                 padded[2] * 0.5, padded[3] * 0.5), abs=1e-3)
    assert recon.controller.captures == [pytest.approx(padded)]


def test_the_trim_reads_a_patch_with_margin_or_it_has_no_background(tmp_path):
    """Stated as its own test because it is the non-obvious part of the design: the patch
    is deliberately bigger than the box, since `content_box` takes the background off the
    patch's outer ring. Cut to the box exactly and the ring is the control, so the trim
    measures the control against itself and finds nothing."""
    recon = session(tmp_path, FakeController())
    hint = (0.40, 0.70, 0.20, 0.08)
    recon.snap_box(hint)
    grabbed = recon.controller.captures[0]
    assert grabbed[2] > hint[2] and grabbed[3] > hint[3]


def test_a_wide_slot_is_sampled_finely_enough_to_have_rows(tmp_path):
    """The bug this pins: `capture` scales to a longest side, so a text slot 30x wider than
    it is tall arrives four pixels tall, and a trim of four rows cannot say where the top
    of the text is. Asked for as an area instead, the short side stays measurable."""
    recon = session(tmp_path, FakeController())
    _, _, client_w, client_h = recon.controller.last_good_rect
    slot = trim_patch((0.06, 0.44, 0.88, 0.018))
    longest = recon.patch_samples(slot)
    tall = longest * (slot[3] * client_h) / (slot[2] * client_w)
    assert tall >= 3
    assert longest <= ELEMENT_SAMPLES_MAX
    # And the ordinary case is left alone: a button is near enough square in pixels that
    # the plain budget already gives it both axes, and paying more would be paying for
    # precision below one finger.
    assert recon.patch_samples(pad_box((0.30, 0.70, 0.40, 0.09), ELEMENT_PAD)) \
        == ELEMENT_SAMPLES


def test_the_patch_is_measured_in_pixels_not_in_fractions(tmp_path):
    """A region that is square in fractions is 1:1.8 in pixels on this window, and it is
    the pixels that decide whether a side is thin. Reading the fractions instead would call
    a wide slot square whenever the window's own shape happened to cancel it out."""
    recon = session(tmp_path, FakeController())
    square_in_fractions = (0.1, 0.1, 0.5, 0.5)
    assert recon.patch_samples(square_in_fractions) == ELEMENT_SAMPLES
    # Square in *pixels* on a 1120x2000 client: 0.5 of the width is 0.28 of the height.
    assert recon.patch_samples((0.1, 0.1, 0.5, 0.28)) == ELEMENT_SAMPLES


def test_a_flat_patch_keeps_the_hint_and_says_so(tmp_path):
    recon = session(tmp_path, FakeController(drawing=(80, 80, None)))
    hint = (0.40, 0.70, 0.20, 0.08)
    box, why, kept = recon.snap_box(hint)
    assert box == hint
    assert "nothing inside it differs" in why


def test_an_axis_with_no_measurable_edge_keeps_the_hint_on_that_axis_only(tmp_path):
    """A button on a full-width bar of the same colour: its top and bottom are real edges
    and its sides are not. Taking the vertical trim is most of the value, and widening the
    box to the padded patch on the axis that failed would leave it measurably worse than
    the hint it replaced."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (0, 30, 100, 70))))
    hint = (0.40, 0.70, 0.20, 0.08)
    box, why, kept = recon.snap_box(hint)
    assert why == ""
    assert (box[0], box[2]) == pytest.approx((hint[0], hint[2]))
    padded = trim_patch(hint)
    assert box[3] == pytest.approx(padded[3] * 0.4, abs=1e-3)


def test_content_at_every_edge_is_reported_rather_than_taken(tmp_path):
    """Both axes failing means the thing overflows the margin entirely, so nothing here
    measured where it ends and the result is the hint plus a sentence - not the hint
    silently returned, which reads in the map as a successful measurement."""
    recon = session(tmp_path, FakeController(drawing=cross(60, 60)))
    box, why, kept = recon.snap_box((0.40, 0.70, 0.20, 0.08))
    assert box == (0.40, 0.70, 0.20, 0.08)
    assert "reach every edge" in why


def test_one_side_running_off_the_patch_keeps_that_edge_and_measures_the_rest(tmp_path):
    """The case the per-edge rule exists for: a button in a column of identical buttons, whose
    neighbour is inside the margin. Content flush against the top of the patch continues past
    it, so the top is unmeasurable and the description stands there - while the other three
    edges are real and get taken. Handled per axis instead, this box would have kept the
    hint's whole height and thrown away a measured bottom edge; handled per box, it would
    have kept the hint entirely."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (20, 0, 80, 60))))
    hint = (0.40, 0.70, 0.20, 0.08)
    box, why, kept = recon.snap_box(hint)
    assert why == ""
    assert kept == ("top",)
    padded = trim_patch(hint)
    assert box[1] == pytest.approx(hint[1])            # the side that ran off
    assert box == pytest.approx((padded[0] + padded[2] * 0.20, hint[1],
                                 padded[2] * 0.60,
                                 padded[1] + padded[3] * 0.60 - hint[1]), abs=1e-3)


def test_a_trim_that_finds_a_detail_inside_the_element_is_refused(tmp_path):
    """A panel whose border is within `INK_DELTA` of the screen behind it, with one bright
    mark on it: the only measurable thing in the patch is the mark, and its rectangle is a
    truthful measurement of the wrong object. Centred, so the drift guard cannot catch it -
    the size is the only tell, which is why there are two guards and not one."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (40, 44, 60, 56))))
    hint = (0.30, 0.30, 0.30, 0.30)
    box, why, kept = recon.snap_box(hint)
    assert box == hint
    assert "inside it rather than the thing itself" in why


def test_a_trim_that_locks_on_to_a_neighbour_is_refused(tmp_path):
    """A tall plate down one side of the patch and clear of every edge of it - the panel the
    button sits on, in the abstract. The trim succeeded, but on something the description was
    not about. A coarse rectangle around the right control beats a tight one around the wrong
    one, so the hint wins and the report says why. Big enough to clear `ELEMENT_SHRINK` and
    inside every edge on purpose: this one has to be caught by how far the answer moved, not
    by its size or by which edges it touched, both of which have their own guard."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (1, 2, 30, 98))))
    hint = (0.40, 0.70, 0.08, 0.06)
    box, why, kept = recon.snap_box(hint)
    assert box == hint
    assert kept == ()
    assert "away" in why


def test_a_window_that_cannot_be_read_keeps_the_hint(tmp_path):
    """`snap_box` is called on a live window mid-pass. A capture that raises must cost the
    accuracy of one rectangle and not the pass that was measuring it."""
    controller = FakeController()

    def broken(*args, **kwargs):
        raise OSError("the window went away")

    controller.capture = broken            # type: ignore[method-assign]
    recon = session(tmp_path, controller)
    box, why, kept = recon.snap_box((0.40, 0.70, 0.20, 0.08))
    assert box == (0.40, 0.70, 0.20, 0.08)
    assert "could not read the pixels" in why


# --- placing a screen's elements --------------------------------------------

def test_every_element_gets_a_rectangle_a_point_and_a_picture(tmp_path):
    recon = session(tmp_path, FakeController(drawing=(100, 100, (25, 25, 75, 75))))
    screen, variant = screen_with([{"label": "Battle", "what": "starts a match",
                                    "kind": "button", "box": [0.40, 0.70, 0.20, 0.08]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "trimmed"
    assert as_box(element["box"]) is not None
    # The point is the box's centre and nothing else, so what the map records and what a
    # click is sent to cannot drift apart.
    assert tuple(element["at"]) == pytest.approx(box_centre(as_box(element["box"])), abs=1e-3)
    assert element["image"] == "images/sc01-el01.png"
    assert recon.controller.written == [tmp_path / "images" / "sc01-el01.png"]


def test_an_element_with_only_a_point_is_grown_and_then_trimmed(tmp_path):
    """The common first-pass case, and the one that used to be the end of the story: a
    point was all there was, and it was clicked. Now it seeds a default box, the pixels cut
    that box to the control, and the point moves to the middle of the result."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (25, 25, 75, 75))))
    screen, variant = screen_with([{"label": "Shop", "what": "a tab", "at": [0.5, 0.5]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "trimmed"
    assert (element["box"][2], element["box"][3]) < ELEMENT_DEFAULT


def test_an_element_the_pixels_cannot_place_is_kept_as_described(tmp_path):
    recon = session(tmp_path, FakeController(drawing=(80, 80, None)))
    screen, variant = screen_with([{"label": "Gold", "what": "a counter",
                                    "box": [0.45, 0.02, 0.12, 0.03]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "described"
    assert element["box"] == [0.45, 0.02, 0.12, 0.03]
    # Beside the box, not in the failure list. An element the trim cannot reach is still a
    # usable description, so the reason travels with it into the report line and the crop
    # rather than into "what went wrong".
    assert "differs from the background" in element["placed_why"]
    assert not recon.controller.notes


def test_an_element_with_neither_a_box_nor_a_point_is_named_in_the_notes(tmp_path):
    """The y=1.33 case, which is what this reporting exists for: five of 99 elements on a
    real pass came back off the bottom of the window, all of them one screen's bottom
    navigation, and the harness dropped the lot without a word."""
    recon = session(tmp_path, FakeController())
    screen, variant = screen_with([{"label": "Clan", "what": "a tab", "at": [0.64, 1.33]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "nowhere"
    assert "box" not in element
    assert any("cannot place 'Clan'" in n for n in recon.controller.notes)


def test_a_point_outside_its_own_box_is_kept_beside_it(tmp_path):
    """Two claims from one call disagreeing is a thing a reader should be able to see, and
    it is also the check on whether asking for a box was worth it at all."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (25, 25, 75, 75))))
    screen, variant = screen_with([{"label": "Battle", "what": "a button",
                                    "box": [0.40, 0.70, 0.20, 0.08], "at": [0.1, 0.1]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["described_at"] == [0.1, 0.1]
    assert tuple(element["at"]) != (0.1, 0.1)


def test_a_moving_region_is_placed_from_the_cells_measured_to_move(tmp_path):
    """Not trimmed. Trimming one frame of moving content crops it to whatever that frame
    happened to contain, and the extent is already measured - `Screen.animated` is every
    cell that moved with nothing in flight."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (0, 0, 4, 4))))
    animated = box_cells((0.30, 0.20, 0.20, 0.15))
    screen, variant = screen_with([{"label": "the river", "what": "running water",
                                    "kind": "animation", "box": [0.30, 0.20, 0.20, 0.15]}],
                                  animated=animated)
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "measured movement"
    # The drawing would have trimmed this to a 4x4 corner had the animation path not been
    # taken, so the box surviving at roughly its described size is the assertion.
    assert element["box"][2] > 0.1 and element["box"][3] > 0.1
    # One capture, and it is the crop of the box itself. The trim path grabs a *padded*
    # patch first, so this is the reading that says no trim was attempted.
    assert recon.controller.captures == [pytest.approx((0.30, 0.20, 0.20, 0.15))]


def test_an_animation_where_nothing_moved_is_a_disagreement_worth_saying(tmp_path):
    recon = session(tmp_path, FakeController())
    screen, variant = screen_with([{"label": "a banner", "what": "it pulses",
                                    "kind": "animation", "box": [0.3, 0.2, 0.2, 0.1]}])
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "described"
    assert "no cell of it moved" in element["placed_why"]


def test_an_animation_measured_somewhere_else_keeps_its_hint_and_says_where(tmp_path):
    recon = session(tmp_path, FakeController())
    screen, variant = screen_with([{"label": "a banner", "what": "it pulses",
                                    "kind": "animation", "box": [0.05, 0.05, 0.1, 0.1]}],
                                 animated=box_cells((0.70, 0.70, 0.15, 0.15)))
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert element["located"] == "described"
    assert "measured to move are elsewhere" in element["placed_why"]


def test_nothing_is_measured_against_a_frame_that_has_moved_on(tmp_path):
    """The one way this fails in a real pass: the vetting call takes seconds, and the screen
    can be somewhere else by the time the rectangles are read. A box measured off the next
    screen would be wrong in the one way nothing downstream could detect, so the screen gets
    nothing written to it at all."""
    controller = FakeController(fingerprint_bytes=bytes([200] * (GRID_COLS * 18 * 3)))
    recon = session(tmp_path, controller)
    screen, variant = screen_with([{"label": "Battle", "what": "a button",
                                    "box": [0.40, 0.70, 0.20, 0.08]}],
                                 fp=bytes(GRID_COLS * 18 * 3))
    recon.locate_elements(screen, variant)
    element = screen.vetting["elements"][0]
    assert "located" not in element
    assert element["box"] == [0.40, 0.70, 0.20, 0.08]
    assert any("has moved" in n and "would be wrong" in n for n in controller.notes)


def test_a_reason_is_dropped_when_a_later_occurrence_manages_to_measure(tmp_path):
    """`preview_elements.py` and a retry both clear `located` to measure again. A reason
    left behind from the attempt that failed would then sit in the report beside a box that
    *was* measured, which is the one direction this reporting must not be wrong in."""
    controller = FakeController(drawing=(100, 100, (25, 25, 75, 75)))
    recon = session(tmp_path, controller)
    screen, variant = screen_with([{"label": "Shop", "what": "a tab",
                                    "box": [0.30, 0.30, 0.30, 0.30]}])
    element = screen.vetting["elements"][0]
    element["placed_why"] = "left over from an earlier attempt"
    recon.locate_elements(screen, variant)
    assert element["located"].startswith("trimmed")
    assert "placed_why" not in element


def test_cells_already_known_to_move_do_not_block_a_measurement(tmp_path):
    """The other half of that guard, and the half a static fake game cannot show. A live
    screen is never bit-identical to its stored appearance: a coin counter ticks, a chest
    timer counts down, water runs. Measured on Clash Royale, an idle main screen sat 21 of
    576 cells from its own stored frame against a tolerance of 15 - so counting every changed
    cell means refusing to measure anything, forever, on a screen whose buttons have not
    moved a pixel. Only cells with no known explanation count."""
    fp = bytearray(GRID_COLS * 18 * 3)
    for cell in range(100):                    # a hundred cells differ from the stored frame
        fp[cell * 3:cell * 3 + 3] = bytes([200, 200, 200])
    controller = FakeController(drawing=(100, 100, (25, 25, 75, 75)),
                                fingerprint_bytes=bytes(fp))
    recon = session(tmp_path, controller)
    screen, variant = screen_with([{"label": "Battle", "what": "a button",
                                    "box": [0.40, 0.70, 0.20, 0.08]}],
                                  animated=set(range(5)),
                                  fp=bytes(GRID_COLS * 18 * 3))
    screen.volatile = set(range(5, 95))        # ... and 95 of them are already accounted for
    recon.locate_elements(screen, variant)
    assert screen.vetting["elements"][0]["located"] == "trimmed"
    assert not any("has moved" in note for note in controller.notes)


def test_a_screen_is_only_measured_so_many_times_per_pass(tmp_path):
    """Bounded like `ESCALATION_ASKS`, and in memory for the same reason: a screen that was
    somewhere else both times is a fact about two moments, so a later pass tries again."""
    controller = FakeController(fingerprint_bytes=bytes([200] * (GRID_COLS * 18 * 3)))
    recon = session(tmp_path, controller)
    screen, variant = screen_with([{"label": "Battle", "what": "a button",
                                    "box": [0.40, 0.70, 0.20, 0.08]}],
                                 fp=bytes(GRID_COLS * 18 * 3))
    for _ in range(ELEMENT_LOCATES + 3):
        recon.locate_elements(screen, variant)
    assert recon.locates["sc01"] == ELEMENT_LOCATES


def test_an_element_already_placed_is_not_measured_again(tmp_path):
    """`locate_elements` runs on every step of a vetted screen, and a crop costs a capture
    and a PNG encode. Only the unplaced ones are work."""
    recon = session(tmp_path, FakeController(drawing=(100, 100, (25, 25, 75, 75))))
    screen, variant = screen_with([{"label": "Battle", "what": "a button",
                                    "box": [0.40, 0.70, 0.20, 0.08]}])
    recon.locate_elements(screen, variant)
    recon.locate_elements(screen, variant)
    assert len(recon.controller.written) == 1
    assert recon.locates["sc01"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
