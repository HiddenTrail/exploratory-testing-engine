"""A recon session: drive an unknown game for a while, and write down what its
screens are, what the inputs do to them, and which pixels were never trustworthy.

The unit of knowledge here is a **transition**, not an image. That follows from what
the output is supposed to read like - "this settings entry sits in a list on the
front page, and clicking it takes you to a screen of settings" is three claims about
edges and one about a node. A pile of labelled screenshots cannot express it,
because the interesting part is what connects them. So the session builds a labelled
multigraph: nodes are screens, edges are (screen, action) -> screen, and every edge
records which input modality produced it.

Two granularities, because one is never right:

- a **screen** is a place ("the main menu"), matched loosely over the cells that
  hold still;
- a **variant** is an exact appearance ("the main menu with the third row lit").

Collapsing them loses the finding that matters most: pressing `down` changes the
variant and not the screen, while pressing `enter` changes the screen. That *is*
"what does the keyboard do here", and it falls out of the two-level split for free
instead of needing a rule per game.

Which cells hold still is learned, not configured. On every revisit the cells that
differ from a screen's first sighting are marked volatile and dropped from its
identity test, so a scoreboard, an animated background or a whole game board stops
breaking recognition - and the accumulated volatile mask is itself an output, since
it says where a screen's dynamic content lives without anyone having measured a
rectangle by hand.

Safety, in three layers, because exploration is destructive by default and a session
that ends early has taken its whole remaining budget with it:

1. `target.py`'s coordinate denylist, enforced inside `Controller.click`.
2. Modality gating. Cursor moves and arrow keys are safe by construction and need
   no permission. `enter`, `space`, `esc` and any click are *committing* actions and
   need a verdict first, because those are what confirm a dialog nobody has read.
3. The vetting pass: a new screen is read before the explorer may commit to
   anything on it. This is the only layer that can protect a keyboard-driven menu,
   where the dangerous action is `enter` on a row whose position is not knowable in
   advance and no coordinate rule can help.

With `--no-model` there is no third layer, so committing actions stay locked and the
session maps only what cursor moves and arrow keys reveal. That is a real result and
a deliberately honest floor - it is what this machinery can discover with no
intelligence in the loop at all - but it will not get far into a game.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import islice, zip_longest
from pathlib import Path
from shutil import copyfile

import target as targets
from calibrate import MATCH_FLOOR, SLACK_CELLS
from controller import (Controller, WindowLost, content_box, log, readable_output,
                        set_dpi_aware, is_fraction)

# 32x18 keeps the 16:9 aspect, so cells are square and a cell index maps back to a
# screen position without correction. 576 cells is coarse enough that a whole
# fingerprint costs one thumbnail grab, and fine enough that a menu row occupies
# several cells rather than blurring into its background.
GRID_COLS, GRID_ROWS = 32, 18
NCELLS = GRID_COLS * GRID_ROWS

# How far a cell's mean must move to count as changed, and how much of a screen's
# stable area must agree for two frames to be the same screen, both live on the
# Target: they are per-game measurements, and a global default is how one game's
# calibration silently becomes another's. `Target.cell_delta` and
# `Target.screen_match` document how to re-cut them from a session's own report.
#
# Compared on raw means rather than quantized buckets on purpose: bucketing puts a
# hard edge inside the value range, and a cell sitting on one flips identity from
# frame to frame for no reason anyone can see.

# Above this fraction of *raw* cells shared with a screen's first sighting, two frames
# are so nearly identical that a naming disagreement between them is the model's
# wording rather than a different place, and geometry keeps the call. Below it, the
# naming is allowed to split the screen - see `Recon.split_screen`.
SPLIT_CEILING = 0.99

# A screen matched on fewer stable cells than this has had its identity eaten by its
# own volatile mask and would start absorbing unrelated screens. Recorded rather
# than silently tolerated: "almost all of this screen is dynamic" is a finding.
MIN_STABLE_CELLS = 40

MAX_VARIANTS = 12        # stored per screen; the rest are counted, never dropped silently
VET_VARIANTS = 6         # appearances of one screen the model will rule on; the budget that
                         # stops a screen whose look changes constantly from spending the
                         # session on vetting calls about the same three buttons
ARBITRATION_CALLS = 4    # extra calls a screen may spend on appearances far from its first
                         # sighting, past that budget. Those are the ones only the volatile
                         # mask let in, so they are where two places get merged into one -
                         # and once the budget is gone, nothing else ever notices
NAV_REPEAT = 12          # hard cap on presses of one navigation key on one screen
NAV_STALE = 3            # consecutive presses revealing nothing new before moving on
NAV_BUDGET = 40          # navigation presses of *any* key on one screen, ever. The per-key
                         # caps above are enforced through `screen.tried`, and the frontier
                         # route deliberately bypasses that set - so without one number over
                         # the whole thing, an arrow key retired for doing nothing comes
                         # straight back as the move to the next appearance. 40 is above what
                         # four keys at their per-key caps can legitimately spend
ANIMATION_SAMPLES = 3    # frames taken with no input, to see what a screen does unprompted
ANIMATION_GAP = 0.3      # seconds between them; long enough for a slow loop to advance
PULSE_LIMIT = NCELLS // 8  # cells an *appearance* may move on its own and still be believed.
                         # Past this the reading is not "it shimmers" but "the game moved on
                         # while it was being sampled", and excusing that many cells would let
                         # one appearance match whatever came next
HOVER_COLS, HOVER_ROWS = 8, 5
HOVER_PATIENCE = 14      # probes with no reaction at all before a screen is called hover-inert.
                         # Sound only because of the order below: 14 of 40 points is a third of
                         # the grid, so what makes the bail a statement about the screen rather
                         # than about the first third of it is that the prefix reaches every
                         # quadrant - at least three probes in each
HOVER_RESCUE_PROBES = 18  # extra shifted probes after an inert first pass. This catches
                          # text-sized controls that sit between coarse cell centres.
HOVER_STRIDE = 7         # spreads the probe order *within* a quadrant, so a prefix is not a row
HOVER_SETTLE = 0.5       # cursor held this long before the frame is read. The floor on every
                         # probe, so it is what decides whether forty of them are affordable.
                         # Measured: at 0.5s, seven of eight reactive points on a real menu
                         # have moved at least two cells - against two of eight at 0.3s
HOVER_GROWTH = 0.2       # between later looks at a point that *is* reacting, while the
                         # reaction keeps getting bigger
HOVER_REACTION = 1.0     # cap on that. A fade measured at 700ms is why the hold is not zero,
                         # which is what it effectively was; the cap is what stops a screen
                         # that animates on its own from spending a whole pass in the sweep
HOVER_SAME_PLACE = NCELLS // 4   # a frame this far from the screen the cursor is sitting on
                         # is not a highlight, so it is not evidence about how far a frame may
                         # drift and still be the same screen - a mouse-over menu that opens a
                         # submenu really has gone somewhere else, and `relax_match` must not
                         # learn from it

# Every model call has so far seen exactly one picture: the whole window, scaled so its
# longest side is 1400px. On a 3840x2160 client that is a 2.7x reduction, and one grid
# cell - 120x120 real pixels - arrives 43px across. So the two cells a menu button lights
# up by are about 87x43 in the only image the model is given, which is why a vetter can
# say where the buttons are and never say what hovering did to one. A crop is saved at
# native resolution, because `save_png` only ever scales *down*, so the same button
# arrives 240x120: the same evidence, 2.7x sharper, at a tenth of the pixels.
CROP_MARGIN = 1          # cells of context around what moved. A crop of exactly the cells
                         # that changed is a highlight with nothing to attach it to
CROP_MIN = (5, 4)        # smallest crop, in cells, grown around the change rather than
                         # taken tight to it - a 1-cell crop is legible to the pixel test
                         # and to nobody else
CROP_MAX_AREA = 0.45     # a change wider than this is not a control reacting, it is the
                         # screen changing, and a crop of it is the frame again - which
                         # already exists as that appearance's own image
VET_CROPS = 3            # controls a vetting call carries close-ups of, widest reaction
                         # first, at two pictures each. The cap is tokens: the call
                         # already carries the whole window
# In time order, which is not the order they are taken in - the after frame of a hover is
# the only one available while the cursor is on the point, and the before frames of every
# control on a screen are taken together at the end of the sweep.
CROP_SLOTS = ("before", "pressed", "after")

# --- one control's own rectangle --------------------------------------------
#
# Everything above aims a camera at *cells*: the grid squares that moved, grown to a
# legible minimum. That is the right unit for "what did this input touch", and the wrong
# one for "where is this button". A cell of this grid is 35x111 real pixels on the window
# measured here, so the smallest crop the grid can express is 175x444 - a rectangle that
# holds a button, a slice of the panel behind it and usually a neighbour. Cropped that way,
# every close-up on a screen looks like the same neighbourhood, and the coordinate that
# comes out of it is the middle of a neighbourhood rather than the middle of a control.
#
# So an element gets its own rectangle, off the grid entirely, in three steps: the vetting
# call draws a box around what it can see, the pixels inside that box decide where its
# edges actually are (`controller.content_box`), and the tap point becomes the centre of
# the result. The division of labour is the same one the rest of this file uses - the model
# says what a thing is and roughly where, and a measurement says exactly where - and it is
# why the box the model drew is kept alongside the snapped one whenever the two disagree.
ELEMENT_PAD = 0.4        # of the hint box's own width and height, grabbed around it per
                         # side before trimming. Margin is what makes the trim possible at
                         # all: `content_box` reads the background off the edge of the
                         # patch, so a patch cut exactly to the control has the control's
                         # own colour as its background and finds nothing in it.
ELEMENT_PAD_MAX = 0.04   # of the window, per side, whatever `ELEMENT_PAD` works out to.
                         # A margin proportional to the box is right for a button and wrong
                         # for a panel: 40% of a box 0.6 wide is 0.24 of the screen of
                         # margin, and the trim then measures the bounding box of the panel
                         # *and* everything within a quarter of a screen of it. Measured on
                         # the fake game, this is the difference between placing its list at
                         # 0.06 and placing it at 0.25, where it is.
ELEMENT_SAMPLES = 140    # longest side, in samples, that the patch is trimmed at. The trim
                         # is a Python loop over every pixel, so this is a time budget: at
                         # 140 a patch costs about 15ms and a screen of twenty elements a
                         # third of a second. It is also plenty of precision - one sample
                         # is under 0.3% of the window, and a finger is wider than that.
ELEMENT_THIN = 24        # samples the *shorter* side gets at least, when `ELEMENT_SAMPLES`
                         # on the longer one would leave it thinner than this. A text slot
                         # is a wide, short strip: asking only for a longest side hands it
                         # back four pixels tall, `content_box` refuses anything under three
                         # either way, and even at five the top and bottom edges it is
                         # supposed to be measuring are a fifth of the patch apart. This is
                         # the constant that makes a text slot croppable at all.
ELEMENT_SAMPLES_MAX = 640  # ceiling on the longer side once `ELEMENT_THIN` has stretched it,
                         # so a 30:1 sliver is still one blit and one bounded loop. Cost is
                         # the product of the sides and these two budgets are deliberately
                         # alike: 140x140 is 19600 samples, 640x24 is 15360.
ELEMENT_MIN_SIDE = 0.008  # a snapped side thinner than this is a hairline, not a control,
                         # and taking it would aim a tap at the edge of the thing rather
                         # than at the thing
ELEMENT_MAX_AREA = 0.5   # a box larger than half the window is the screen, not an element
ELEMENT_DEFAULT = (0.09, 0.045)   # the box assumed for an element located by a point and
                         # no rectangle. Roughly a menu button on a portrait phone window,
                         # and deliberately a bit small: it is the seed for a trim that can
                         # only shrink from `ELEMENT_PAD` around it.
ELEMENT_SHRINK = 0.15    # of the hint's area, under which the trim is read as having found
                         # something *inside* the element rather than the element itself: the
                         # label on a panel, the highlighted row of a list, the icon on a
                         # plate. A hint twice too big on both axes still trims to a quarter
                         # of its own area, so this only fires on an order-of-magnitude
                         # shrink. Cut against the fake game's borderless list, whose panel
                         # is within `INK_DELTA` of the screen behind it and whose only
                         # visible mark is one highlighted row: without this the map placed
                         # that row and called it the list, measured and unqualified, which
                         # is worse than the loose box it started from.
ELEMENT_DRIFT = 0.6      # how far the snapped centre may move from the hint's, as a
                         # fraction of the hint's own size. Past this the trim has locked
                         # on to something else - the neighbour, or the panel edge - and
                         # the hint is kept, because a rectangle around the wrong control
                         # is worse than a coarse one around the right one.
# What an element is, as far as this harness cares - and it cares because each wants a
# different picture. A button is trimmed to its plate. Text is trimmed the same way, and
# the trim is the more valuable of the two there: a label's box is the answer to "did this
# number change" for every later pass. An animation is *not* trimmed, because trimming one
# frame of moving content crops it to whatever that frame happened to contain; its extent
# is already measured elsewhere, in `Screen.animated`, so that measurement is used instead.
ELEMENT_KINDS = ("button", "text", "icon", "animation", "meter", "panel", "other")
ELEMENT_LOCATES = 2      # attempts per screen, per pass, at locating its elements. A
                         # locate needs the screen still to be on display, so the one way
                         # it fails is the screen having moved on between the vetting call
                         # and this - which is a fact about a moment, so it is retried on a
                         # later occurrence rather than recorded. Not written to the map.

NAV_KEYS = ("up", "down", "left", "right")
COMMIT_KEYS = ("enter", "space", "esc")
# The kinds that name their target by position rather than by whatever is selected,
# and so are ruled on per screen and checked against the coordinate denylist.
MOUSE_KINDS = ("click", "drag", "scroll")

# --- the blind modalities ---------------------------------------------------
#
# Clicks have evidence behind them: the hover sweep says which points react, so a click
# candidate is a measured guess. Drag and scroll have no equivalent. A scrollable list
# looks exactly like an unscrollable one, and a draggable thing looks exactly like a
# fixed one until the button is already down - so there is nothing to sweep for, and a
# probe is the only way to find out. Which makes the policy question "how few probes can
# answer it", and the answer is: one, then escalate on evidence, the same shape the hover
# sweep already uses.
SCROLL_NOTCHES = 3       # per probe. One notch may be under a game's own threshold, and
                         # the probe's job is to be sure nothing moved rather than to
                         # scroll gently.
DRAG_SPAN = 0.25         # how far a probe drag travels, as a fraction of the window.
                         # Long enough that a camera pan or a marquee is unmistakable,
                         # short enough to stay inside the window from a hotspot.
PROBE_AT = (0.5, 0.5)    # where a blind probe happens: the middle, which is the one
                         # point on any screen that is not a guess about the layout.
# Ordered, and only the first is tried unprompted. Right before down because a
# horizontal drag is the one a vertical menu is least likely to react to by accident.
DRAG_DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
# Attempts per screen, per pass, at buying verdicts for the escalated probes. Two: the
# first can fail on one bad response and the second is the retry, while a third would mean
# the call itself is failing rather than the answer being unlucky - and a call retried
# every step spends the pass on it. Deliberately not written to the map, so a later pass
# tries again; a call that failed is a fact about a moment, not about the screen.
ESCALATION_ASKS = 2

# The one refusal that is temporary: it describes this session, not the control.
UNVETTED = "screen not vetted, so committing actions stay locked"

SAVE_EVERY = 20          # actions between JSON flushes; a killed session keeps its findings

# Bumped from /1 when the ontology became something a later pass reads back rather than
# only something a person reads. `resume` refuses anything else: the earlier shape is
# missing the masks and the tried sets, and every one of them absent reads as a
# plausible default - an unswept screen, an unprotected split - so a quiet degrade would
# hand a resumed pass a map that is wrong in exactly the places that are expensive.
#
# **Deliberately not bumped for drag and scroll**, which is the harder call. Adding action
# kinds does grow the format, and an older checkout reading a map with a drag edge in it
# builds a drag with no end point - but it *fails loudly* the moment it tries to route
# through that edge, rather than quietly exploring a game it thinks it has already
# covered. That is the distinction this constant is for. Bumping would have refused every
# map already on disk, thrown away the transitions and the paid-for verdicts in them, and
# made the next pass of a mapped game start from nothing: a certain cost, to insure
# against a loud failure in a checkout nobody is running. Read the other way round, a map
# written before this change resumes perfectly - the new flags default to "not probed
# yet", which is exactly what those screens are.
SCHEMA = "game-ontology/2"


# --- fingerprints -----------------------------------------------------------

def fingerprint(controller: Controller, verify: bool = True) -> bytes:
    """Three bytes of BGR mean per grid cell.

    `verify=False` for callers that only want to *watch* the window. The default asks
    `grab` to confirm the game is in the foreground first, and that check escalates - a
    window that is not foreground sends `ensure_readable` looking for a fix, up to and
    including closing the game. Right for a driver mid-errand, wrong for an observer,
    whose whole question is what the window is doing without being touched.

    The averaging is GDI's, not ours: `grab_thumbnail` downsamples with HALFTONE, so
    each returned pixel is already the mean of the source region behind it. That is
    the right reduction for identity (it is stable against a pixel of noise) and the
    wrong one for anything extremum-based - a thin bright line survives averaging as
    a barely-changed mean, which is why detail work elsewhere grabs 1:1 instead."""
    raw = controller.grab(GRID_COLS, GRID_ROWS, verify=verify)
    out = bytearray()
    for i in range(0, len(raw), 4):
        out += raw[i:i + 3]
    return bytes(out)


def hover_order(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The order to sweep the cursor in, such that any prefix covers the whole window.

    This exists because the sweep is allowed to give up early, and a bail is only
    honest if what it has seen so far represents the screen. Striding alone does not
    give that. A stride visits every Nth point of a row-major list, which spreads the
    prefix across rows but keeps it in list order overall, so the last corner of the
    window is still probed near the end - and a game whose only controls sit in that
    corner gets recorded as ignoring the cursor entirely. That happened: four menu
    buttons in the bottom right, every one of them hover-reactive, on a screen the
    sweep called inert after fourteen probes that never went below the middle.

    So the points are bucketed by half of the window in each axis and taken round
    robin, which makes "probes so far" cover the four quadrants evenly at every
    length. Within a quadrant the stride still applies, so a prefix there is scattered
    rather than one row.
    """
    buckets: dict[tuple[bool, bool], list[tuple[float, float]]] = {}
    for point in points:
        buckets.setdefault((point[0] >= 0.5, point[1] >= 0.5), []).append(point)
    strided = [[bucket[i] for offset in range(HOVER_STRIDE)
                for i in range(offset, len(bucket), HOVER_STRIDE)]
               for _, bucket in sorted(buckets.items())]
    return [point for row in zip_longest(*strided) for point in row if point is not None]


def hover_rescue_points() -> list[tuple[float, float]]:
    """A shifted sweep for screens that looked inert on the coarse pass.

    The primary sweep samples cell centres. This one samples quarter-offset points in
    the same balanced order, so thin controls and text links between centres still get
    a chance before the screen is declared hover-inert.
    """
    points = []
    for r in range(HOVER_ROWS):
        for c in range(HOVER_COLS):
            points.append(((c + 0.25) / HOVER_COLS, (r + 0.25) / HOVER_ROWS))
            points.append(((c + 0.75) / HOVER_COLS, (r + 0.75) / HOVER_ROWS))
    return hover_order(points)


def diff_cells(a: bytes, b: bytes, delta: int) -> set[int]:
    return {i // 3 for i in range(0, min(len(a), len(b)), 3)
            if (abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1])
                + abs(a[i + 2] - b[i + 2])) // 3 > delta}


def agreement(fp: bytes, rep: bytes, volatile: set[int],
              delta: int) -> tuple[float, int, set[int]]:
    """How much of a screen's *stable* area this frame reproduces.

    Returns the fraction, how many cells that was judged on, and which stable cells
    disagreed. The second number is what stops the first from lying: as a volatile
    mask grows, agreement is computed over less and less of the screen, and a score
    of 1.0 over eleven cells is not a match, it is a coincidence."""
    differing = diff_cells(fp, rep, delta)
    stable_count = NCELLS - len(volatile)
    if stable_count <= 0:
        return 0.0, 0, differing
    stable_differing = differing - volatile
    return 1.0 - len(stable_differing) / stable_count, stable_count, differing


# Words that say what kind of thing a screen is rather than which one it is. Two
# names that share only these have not agreed on anything.
GENERIC_WORDS = {"screen", "menu", "page", "view", "window", "dialog", "the", "a", "of"}


def names_agree(a: str, b: str) -> bool:
    """Whether two names the model wrote refer to the same place.

    Compared as word sets, because 'main menu' and 'Main Menu screen' are the same
    answer and a string comparison would call them a disagreement. Deliberately
    generous: a wrong "these agree" leaves a screen merged, which is exactly what a
    threshold alone would have done, while a wrong "these differ" invents a screen
    that does not exist."""
    words = [set(re.findall(r"[a-z0-9]+", name.lower())) for name in (a, b)]
    if not all(words):
        return True
    specific = [w - GENERIC_WORDS for w in words]
    if all(specific):
        words = specific
    return len(words[0] & words[1]) / len(words[0] | words[1]) >= 0.5


def variant_key(fp: bytes) -> str:
    return hashlib.blake2s(fp, digest_size=6).hexdigest()


def volatile_map(volatile: set[int]) -> list[str]:
    """The volatile mask as one string per grid row, '#' where content moved.

    Written into the JSON in this shape because it is legible in both directions: a
    person scrolling the file sees the board and the scoreboard as blocks, and a
    later consumer can parse it back to indices without a bespoke decoder."""
    return ["".join("#" if r * GRID_COLS + c in volatile else "."
                    for c in range(GRID_COLS)) for r in range(GRID_ROWS)]


def cell_set(rows: list[str]) -> set[int]:
    """`volatile_map` read back. The claim that shape makes - legible in both
    directions - is only true if something actually reads it, and a resumed pass has to
    restore these masks exactly rather than approximately."""
    return {r * GRID_COLS + c for r, row in enumerate(rows)
            for c, mark in enumerate(row) if mark == "#"}


# --- where to point the camera ----------------------------------------------

def _grow(low: int, high: int, least: int, limit: int) -> tuple[int, int]:
    """Widen a span of cells to at least `least`, centred, and clamp it to the grid.

    Clamping second and re-widening after it, because a control against an edge is the
    common case - a menu title in the top row, a Back button in the corner - and a span
    that loses half its margin to the edge would come out half the intended size."""
    short = least - (high - low)
    if short > 0:
        low, high = low - (short + 1) // 2, high + short // 2
    low, high = max(0, low), min(limit, high)
    if high - low < least:
        low, high = (0, min(limit, least)) if low == 0 else (max(0, high - least), high)
    return low, high


def cell_box(cells: set[int]) -> tuple[float, float, float, float] | None:
    """A fractional crop rectangle around a set of grid cells.

    None when there is nothing worth cropping to: no cells, or so many of them that the
    crop would be most of the window. The second case is not a failure, it is the
    difference between a control reacting and the game changing screens, and the caller
    is expected to fall back on the full-window picture that already exists."""
    if not cells:
        return None
    cols = [c % GRID_COLS for c in cells]
    rows = [c // GRID_COLS for c in cells]
    left, right = _grow(min(cols) - CROP_MARGIN, max(cols) + 1 + CROP_MARGIN,
                        CROP_MIN[0], GRID_COLS)
    top, bottom = _grow(min(rows) - CROP_MARGIN, max(rows) + 1 + CROP_MARGIN,
                        CROP_MIN[1], GRID_ROWS)
    if (right - left) * (bottom - top) >= CROP_MAX_AREA * NCELLS:
        return None
    return (left / GRID_COLS, top / GRID_ROWS,
            (right - left) / GRID_COLS, (bottom - top) / GRID_ROWS)


def point_box(fx: float, fy: float) -> tuple[float, float, float, float]:
    """A crop around a point nothing has been measured at.

    The case this exists for is a control named by a plan on a screen that ignores the
    cursor: there is no reaction to take the extent from, so the crop is a default-sized
    box centred on the point. Weaker evidence than a measured one and deliberately the
    same shape, so it can be shown to the model the same way."""
    col = min(int(fx * GRID_COLS), GRID_COLS - 1)
    row = min(int(fy * GRID_ROWS), GRID_ROWS - 1)
    return cell_box({row * GRID_COLS + col}) or (0.0, 0.0, 1.0, 1.0)


def as_box(value) -> tuple[float, float, float, float] | None:
    """A model's `[x, y, w, h]` read as a fractional rectangle, or None.

    Tolerant of any shape for the same reason `is_fraction` is: every caller is checking
    something a model chose, so a string, a dict or a five-element list all have to come
    back None and be reported rather than raise inside the check meant to catch them.

    Clamped to the window rather than refused for overhanging it, because a box drawn
    slightly off the edge is the commonest way to describe a control *against* the edge -
    a back arrow in the corner, a bottom navigation bar - and those are the ones worth
    having. A box that misses the window entirely has nothing left after clamping and is
    refused by the side check."""
    try:
        x, y, w, h = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    left, top = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    right, bottom = min(max(x + w, 0.0), 1.0), min(max(y + h, 0.0), 1.0)
    w, h = right - left, bottom - top
    if w < ELEMENT_MIN_SIDE or h < ELEMENT_MIN_SIDE or w * h > ELEMENT_MAX_AREA:
        return None
    return left, top, w, h


def box_centre(box: tuple[float, float, float, float]) -> tuple[float, float]:
    """Where to aim at a rectangle. The one place this is decided, so the point in the map
    and the point a click is sent to cannot drift apart."""
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def box_around(at: tuple[float, float],
               size: tuple[float, float]) -> tuple[float, float, float, float]:
    """A rectangle of `size` centred on a point, clamped to the window."""
    return as_box((at[0] - size[0] / 2, at[1] - size[1] / 2, *size)) or (0.0, 0.0, 1.0, 1.0)


def pad_box(box: tuple[float, float, float, float], pad: float,
            most: float = 1.0) -> tuple[float, float, float, float]:
    """A box grown by `pad` of its own size on every side, clamped to the window.

    `most` caps the growth in fractions of the window, and exists because a margin
    proportional to the box stops being a margin once the box is large: 40% of a panel
    0.6 wide reaches a quarter of the screen in each direction and swallows every control
    around it. See `ELEMENT_PAD_MAX`."""
    x, y, w, h = box
    grow_x, grow_y = min(w * pad, most), min(h * pad, most)
    return (as_box((x - grow_x, y - grow_y, w + 2 * grow_x, h + 2 * grow_y))
            or (0.0, 0.0, 1.0, 1.0))


def _axis(start: float, length: float, patch_start: float, patch_length: float,
          low: float, high: float, low_open: bool,
          high_open: bool) -> tuple[float, float]:
    """Where one axis of a control is, from what the trim could and could not measure.

    `start`/`length` are the described extent on this axis, `patch_start`/`patch_length`
    the padded patch the trim read, and `low`/`high` the content's edges as fractions of
    that patch. An edge is *open* when the content reached the patch there, which means it
    continues past it and nothing on that side was measured. Three cases:

    - **both edges measured** - the measurement, converted back to fractions of the
      window. Nothing to decide.
    - **neither measured** - the content crosses the whole patch on this axis, so there is
      no measurement here at all and the description stands. Widening to the patch instead
      would return the hint grown by the margin, which is measurably *worse* than the box
      it replaced.
    - **one measured** - the interesting one, and the reason this is a function. What is
      known is that one real edge is at the measured place and the control continues past
      the patch on the other side. So position comes from the measurement and size from
      the description: the described length, laid against the edge that was measured, and
      clipped to the patch because that is the whole of what was looked at.

      The described length rather than the visible one, and this is the part with a trap in
      it. An open edge means the content reaches the patch there, so the *visible* length
      on this axis is always "as far as the patch goes" - taking it would return the hint
      grown by the margin, with a neighbouring control inside it, on every element with an
      open edge. The open side carries no measurement of extent at all. It only says which
      way the control runs.

    That last rule is a fix for a live failure and not a refinement. Keeping the described
    edge on the open side instead - the obvious reading of "that side was not measured" -
    produces a box that is provably too small, because content was seen right up to the
    patch's edge and the box stops short of it. Clash Royale's battle-result screen put its
    OK button's described box 0.03 of the window low; the bottom edge measured, the top ran
    off the patch, and the surviving 0.025-tall strip had its centre on the button's own
    bottom border. Sixteen taps in a row reported "nothing visible changed", the pass could
    not dismiss the screen it was standing on, and a hand tap at the button's real centre
    dismissed it first try. Anchoring puts the aim 0.013 higher, inside the plate.
    """
    measured_low = patch_start + patch_length * low
    measured_high = patch_start + patch_length * high
    if low_open and high_open:
        return start, start + length
    if not low_open and not high_open:
        return measured_low, measured_high
    # Never past the patch. Where the described length would reach beyond it, what is left
    # is the whole visible span, which is the most that can be claimed from one edge.
    if low_open:
        return max(patch_start, measured_high - length), measured_high
    return measured_low, min(patch_start + patch_length, measured_low + length)


def box_cells(box: tuple[float, float, float, float]) -> set[int]:
    """The grid cells a fractional box covers, so a rectangle can be compared with a mask.

    Only used to check a claim against a measurement - "the model called this an animation,
    do any cells here actually move" - and never to build a box, because going through the
    grid is exactly the precision this rectangle exists to avoid."""
    x, y, w, h = box
    # Half-open, hence the epsilon: a box exactly one cell wide ends on the boundary
    # between two cells, and `int` on that boundary claims the cell on the far side of it.
    # Left in, the smallest box this file can express covers four cells instead of one.
    first_col = min(int(x * GRID_COLS), GRID_COLS - 1)
    first_row = min(int(y * GRID_ROWS), GRID_ROWS - 1)
    last_col = min(max(int((x + w) * GRID_COLS - 1e-9), first_col), GRID_COLS - 1)
    last_row = min(max(int((y + h) * GRID_ROWS - 1e-9), first_row), GRID_ROWS - 1)
    return {row * GRID_COLS + col
            for row in range(first_row, last_row + 1)
            for col in range(first_col, last_col + 1)}


def _inside(box: tuple[float, float, float, float], at: tuple[float, float]) -> bool:
    return (box[0] <= at[0] <= box[0] + box[2]
            and box[1] <= at[1] <= box[1] + box[3])


def _intersect(one: tuple[float, float, float, float],
               two: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The overlap of two boxes, which `as_box` refuses when there is none."""
    left, top = max(one[0], two[0]), max(one[1], two[1])
    right = min(one[0] + one[2], two[0] + two[2])
    bottom = min(one[1] + one[3], two[1] + two[3])
    return left, top, right - left, bottom - top


def element_kind(element: dict) -> str:
    """The element's kind, restricted to `ELEMENT_KINDS`.

    A free-text field would work everywhere except the one place it is read - the choice
    of how to measure the box - so anything unrecognised becomes "other" and is measured
    the ordinary way rather than silently taking the animation path."""
    kind = str(element.get("kind", "")).strip().lower()
    return kind if kind in ELEMENT_KINDS else "other"


def point_key(at: tuple[float, float]) -> str:
    """How a point is named in the crop-box table - the same text `Action.id` uses, so a
    box measured by a hover can be found again by the click that follows it."""
    return f"{at[0]:.3f},{at[1]:.3f}"


def probe_drag(start: tuple[float, float], direction: tuple[int, int]) -> Action:
    """A drag of `DRAG_SPAN` from a point, clamped to stay on the window.

    Clamped rather than skipped when it would run off the edge: a drag from a hotspot
    near the right edge is still worth trying, it just travels less far. A drag that
    left the window would be refused by `Controller.point`, and correctly."""
    dx, dy = direction
    end = (min(1.0, max(0.0, start[0] + dx * DRAG_SPAN)),
           min(1.0, max(0.0, start[1] + dy * DRAG_SPAN)))
    return Action("drag", at=start, to=end)


def shot_name(screen_id: str, action: Action) -> str:
    """A stable file stem for one action on one screen.

    Stable rather than sequential on purpose: an action that is taken forty times
    overwrites its own three pictures instead of leaving forty copies, and a resumed pass
    writes to the same names the pass it inherited from used."""
    return f"{screen_id}-" + "".join(c if c.isalnum() else "-" for c in action.id)


# --- what an action is ------------------------------------------------------

@dataclass(frozen=True)
class Action:
    kind: str                       # "hover" | "key" | "click" | "drag" | "scroll"
    key: str = ""
    at: tuple[float, float] | None = None
    # Where a drag ends. The start is `at`, so everything keyed on `at` - the crop box,
    # the denylist point check, `point_key` - goes on working for a drag without
    # knowing what one is, and aims at the place the drag began, which is where the
    # thing being dragged was.
    to: tuple[float, float] | None = None
    button: str = "left"
    # Wheel notches, signed: positive away from the user. Not a count of some smaller
    # unit - see `Controller.scroll` on why three notches is three events.
    notches: int = 0
    horizontal: bool = False
    # Keys held down for the duration. A tuple because `Action` is frozen and hashed,
    # and because the order is part of the identity of the chord as written.
    modifiers: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        """A stable name, used as a dict key in five places that outlive the process.

        `screen.tried`, `variant.tried`, the vetting verdicts, the crop-box table and
        the image filenames are all keyed on this text, and a resumed map has to keep
        matching. So the forms that existed before drag and scroll did are unchanged to
        the byte: a plain left click with no modifier is still `click:0.500,0.600`, and
        only the parts that differ from that default appear. A scheme that decorated
        every id with its button and modifiers would have been tidier and would have
        orphaned every verdict in every map already on disk."""
        chord = "+".join(self.modifiers)
        prefix = f"{chord}+" if chord else ""
        if self.kind == "key":
            return f"key:{prefix}{self.key}"
        where = f"{self.at[0]:.3f},{self.at[1]:.3f}"
        if self.kind == "drag":
            button = "" if self.button == "left" else f"{self.button}:"
            return f"drag:{prefix}{button}{where}>{self.to[0]:.3f},{self.to[1]:.3f}"
        if self.kind == "scroll":
            axis = "right" if self.notches > 0 else "left"
            if not self.horizontal:
                axis = "up" if self.notches > 0 else "down"
            return f"scroll:{prefix}{axis}{abs(self.notches)}:{where}"
        button = "" if self.button == "left" else f"{self.button}:"
        return f"{self.kind}:{prefix}{button}{where}"

    @property
    def committing(self) -> bool:
        """Whether this action can do something that cannot be walked back.

        Cursor moves and arrow keys are excluded on the grounds that a UI which
        destroys data on a hover or an arrow press is broken in a way no explorer
        can defend against anyway. Everything else needs permission.

        A wheel is deliberately *not* added to that list, though it is tempting: on
        most screens it zooms or scrolls and is as harmless as a hover. But a wheel
        over a number is how a quantity is chosen - how many to buy, how many to sell,
        how many troops to commit - and a harness that cannot read the number cannot
        tell that screen from a map. The exemption has to be defensible for every
        screen the modality can land on, and this one is not.

        A drag is committing for a plainer reason: it is a click that also travels."""
        return not (self.kind == "hover" or (self.kind == "key" and self.key in NAV_KEYS
                                            and not self.modifiers))

    def describe(self) -> str:
        """What the vetting call is shown, so it has to read as an instruction to a
        person rather than as an identifier. This is the only description of an action
        the model ever sees."""
        chord = "".join(f"{m}+" for m in self.modifiers)
        if self.kind == "key":
            return f"press {chord}{self.key}"
        where = f"({self.at[0]:.3f}, {self.at[1]:.3f})"
        if self.kind == "drag":
            return (f"{chord}drag with the {self.button} button held, from {where} to "
                    f"({self.to[0]:.3f}, {self.to[1]:.3f})")
        if self.kind == "scroll":
            axis = ("right" if self.notches > 0 else "left") if self.horizontal \
                else ("up" if self.notches > 0 else "down")
            return (f"{chord}scroll the wheel {axis} {abs(self.notches)} "
                    f"notch{'es' if abs(self.notches) != 1 else ''} at {where}")
        button = "" if self.button == "left" else f"{self.button}-"
        return f"{chord}{button}{self.kind} at {where}"


@dataclass
class Variant:
    id: str
    key: str
    fp: bytes
    observations: int = 1
    image: str = ""
    first_seen: int = 0
    stored: bool = True
    # Committing *keys* are tracked and vetted here rather than on the screen,
    # because a keypress acts on whatever is currently selected and the selection is
    # precisely what distinguishes one variant from another. Asked "is enter safe on
    # this menu?", the only defensible answer is no - it depends on the row. Asked
    # "is enter safe with this row lit?", it is an answerable question about a
    # readable label. Clicks stay on the screen: a click names its target by
    # position, so the highlight is irrelevant to it.
    tried: set[str] = field(default_factory=set)
    vetting: dict | None = None
    highlighted: str = ""
    # What moves while *this* appearance is the one on screen, sampled with no input in
    # flight. On the variant rather than on the screen because the movement that breaks
    # appearance identity is usually caused by the selection: a highlight that pulses
    # does not exist until something is highlighted, so a mask measured on the screen's
    # first sighting - nothing selected yet - comes out empty and catches nothing.
    #
    # Unioning per-appearance masks into the screen would be worse than useless. The
    # cells that pulse are exactly the cells that say *which* row is selected, so a
    # screen-wide union of them makes "nothing selected" and "Sandbox selected"
    # indistinguishable, which is the one distinction the whole variant mechanism
    # exists to draw. Kept per appearance, it does the opposite: a frame at a different
    # phase of this row's glow is this appearance, while a frame with the glow on the
    # next row differs *outside* this mask and is correctly a new one.
    animated: set[int] = field(default_factory=set)
    # A close-up of what makes this appearance different from the screen's first sighting,
    # which on a menu is the selection. Taken for the vetting call that has to name what is
    # selected, and kept because a picture handed to the model and then thrown away is
    # evidence nobody can check.
    differs_image: str = ""


@dataclass
class Screen:
    id: str
    representative: bytes
    first_seen: int
    observations: int = 1
    volatile: set[int] = field(default_factory=set)
    variants: dict[str, Variant] = field(default_factory=dict)
    unstored_variants: int = 0
    tried: set[str] = field(default_factory=set)
    # Cells known to tell this screen apart from another one, which the volatile mask
    # is therefore never allowed to dismiss as movement. Without this, splitting a
    # screen off does not stick: the mask that merged the two in the first place covers
    # exactly the cells that differ, so the old screen goes on matching the new one's
    # frames perfectly and claims them back.
    protected: set[int] = field(default_factory=set)
    # Monotonic, never `len(variants)`: variants move out of a screen when it splits,
    # and a length-derived name then hands a second appearance an id that is already
    # on an image file and in recorded transitions.
    variant_seq: int = 0
    arbitrations: int = 0
    # Cells this screen moves on its own, sampled with no input in flight - a mascot,
    # a shimmer on a logo, a drifting background. Distinct from `volatile`, and the
    # difference is not where the cells are but how they were found: `volatile`
    # accumulates everything that ever differed while this was still called the same
    # place, so by the time a frame is being filed its own changes are already in
    # there, and subtracting it would make every frame the same appearance. This is
    # measured before any action is taken, so it can be subtracted safely.
    animated: set[int] = field(default_factory=set)
    # Three frames of it, cropped to those cells. What one still picture cannot say:
    # whether the movement is a spinner, a countdown running down, or a mascot waving -
    # and the first two are facts about the game's state, not decoration.
    animation: list[str] = field(default_factory=list)
    hotspots: list[tuple[float, float]] = field(default_factory=list)
    # Where each reacting point's control actually is, as a fractional crop rectangle
    # keyed by `point_key`. Measured, not assumed: the cells that moved when the cursor
    # arrived are the control's own extent, which is what makes a close-up of it evidence
    # rather than a guess about where a button might be. Shared by the hover that found
    # it and every later click at the same point.
    crop_boxes: dict[str, list[float]] = field(default_factory=dict)
    # Cells each reacting point moved. How loud this screen's hover feedback is, which is
    # what separates a game whose buttons merely underline from one whose buttons repaint
    # a quarter of the window - and the second kind is why `screen_match` cannot be one
    # number for every game.
    hover_reactions: list[int] = field(default_factory=list)
    # Points whose reaction outlived the cursor leaving, by `point_key`. Found by trying
    # to photograph them at rest and getting the hovered picture back, pixel for pixel:
    # on a menu of this kind the cursor does not light a button, it moves the selection,
    # and the selection stays where it was left. Worth keeping rather than discarding as a
    # failed photograph - it says the mouse and the arrow keys drive one mechanism, and it
    # is the reason such a point has one close-up instead of a pair.
    sticky: list[str] = field(default_factory=list)
    hover_probed: bool = False
    hover_inert: bool = False
    hover_probe_count: int = 0
    # Whether the blind modalities turned out to do anything here, set by `_record` the
    # first time one of them changes the picture. These are what the escalation in
    # `screen_actions` reads: one probe of each is spent on every screen, and the rest
    # are only spent where the first one proved there was something to find. Kept on the
    # screen rather than recomputed from the transitions because they are policy input
    # on every call to `screen_actions`, which the frontier search runs over every screen
    # it walks past.
    scrolls: bool = False
    drags: bool = False
    vetting: dict | None = None
    degenerate: bool = False
    vet_budget: int = 0
    # Set when this screen exists because the model's naming contradicted the geometry
    # that had merged it into another one. Kept in the output: a screen that only a
    # disagreement separated is exactly the one a reader should check.
    split_from: str = ""
    split_name: str = ""

    def image(self) -> str:
        first = next(iter(self.variants.values()), None)
        return first.image if first else ""


@dataclass
class Transition:
    id: str
    source: str
    dest: str
    action: Action
    kind: str                       # "none" | "variant" | "screen"
    from_variant: str
    to_variant: str
    changed: int
    settle_ms: int
    count: int = 1
    first_seen: int = 0
    # Close-ups of the thing this action touched: `before`, `pressed`, `after`. The
    # full-window pair either side of a transition is already in the map, and it is the
    # wrong picture for the commonest edge in it - an action that changed 4 cells of 576.
    # A slot is filmed at most once, so these are pictures of one specific occurrence and
    # not a composite of forty.
    crops: dict[str, str] = field(default_factory=dict)
    # Where those pictures were aimed. Kept because it is the only thing that lets a
    # *later* pass film the before frame of a keypress: what a key moves is not known
    # until it has been pressed once, and without this the answer dies with the session.
    crop_box: list[float] = field(default_factory=list)


# --- the session ------------------------------------------------------------

class Recon:
    def __init__(self, controller: Controller, out: Path, vetter=None,
                 allow_clicks: bool = True):
        self.controller = controller
        self.out = out
        self.images = out / "images"
        self.vetter = vetter
        self.allow_clicks = allow_clicks
        self.screens: dict[str, Screen] = {}
        self.transitions: dict[str, Transition] = {}
        self.actions_taken = 0
        self.blocked: dict[str, str] = {}
        self.repeats: dict[str, dict[str, int]] = defaultdict(dict)
        # Calls spent asking about escalated probes, per screen. In memory only - see
        # `ESCALATION_ASKS`.
        self.escalation_asks: dict[str, int] = defaultdict(int)
        # Attempts spent measuring where a screen's elements are - see `ELEMENT_LOCATES`.
        # In memory only for the same reason, and with the same shape.
        self.locates: dict[str, int] = defaultdict(int)
        self.actions_at_recovery = -1
        self.screen_match = controller.target.screen_match
        self.cell_delta = controller.target.cell_delta
        self.splits = 0
        self.match_scores: list[float] = []
        self.resumed_from = ""
        # Which screen the last classified frame was filed as, so the *next* frame can be
        # judged against the place we are standing in. Without it the incumbent
        # preference in `_match_screen` only holds inside a single recorded action, and
        # two mutually-qualifying screens still swap places across the step boundary.
        self.standing = ""
        # The last action taken, with what the screen looked like before it and how long
        # it took to settle: (screen, action, fingerprint, settle_ms). Kept for exactly one
        # purpose - an action can open a window that does not exist yet when its result is
        # read, and when that window turns up the action has to be credited with it. See
        # the handover in `step`.
        self.pending: tuple[Screen, Action, bytes, int] | None = None
        # Why the loop ended. Kept because the two endings are different results: a pass
        # that ran out of time was still finding things, while one that ran out of moves
        # has hit the limits of what modality gating and vetting let it reach, and only
        # the second means a longer pass would not have helped.
        self.stopped = ""
        # Which close-ups have already been taken, keyed by `shot_name`. Read before every
        # capture so a slot is filmed once and not once per occurrence: the arrow key that
        # is pressed forty times is exactly the one whose pictures would otherwise be
        # forty copies of the same two cells.
        self.shots: dict[str, dict[str, str]] = {}
        # Which of them are finished, meaning a before/after pair was taken on one
        # occurrence with one aim. Separate from `shots` because a stem can hold a
        # provisional picture and still be waiting for its pair - see `take`.
        self.filmed: set[str] = set()
        # Where to aim on the *next* occurrence of an action whose target is not a point.
        # A keypress has no place on the screen until it has been pressed once, so the
        # first press gets an after picture and no before, and every press after that gets
        # both - the box being the cells the key moved last time.
        self.boxes: dict[str, list[float]] = {}
        self.started = time.monotonic()
        self.images.mkdir(parents=True, exist_ok=True)

    # -- perception ---------------------------------------------------------

    def observe(self, fp: bytes | None = None,
                holding: Screen | None = None) -> tuple[Screen, Variant, bytes, bool]:
        """Classify a frame: which screen, which appearance, and whether that
        appearance is one nobody has seen before.

        `fp` lets a caller that has already grabbed a frame classify *that* frame.
        Re-grabbing instead would sample a later moment and quietly attribute it to
        the earlier one, which is how a transition ends up recorded against an
        appearance that was never on screen when the action landed.

        `holding` is the screen we were on before this frame, if the caller knows it."""
        if fp is None:
            fp = fingerprint(self.controller)
        screen = self._match_screen(fp, holding)
        variant, is_new = self._touch_variant(screen, fp)
        return screen, variant, fp, is_new

    def _match_screen(self, fp: bytes, holding: Screen | None = None) -> Screen:
        """Which known screen this frame is an appearance of, if any.

        Two separate questions, decided by two separate measures, because one measure
        answering both is what let a screen eat its neighbours. The volatile mask
        decides *membership*: is this frame close enough on the cells that identify the
        place. Raw closeness then decides *which* member, among everything that
        qualified.

        Ranking by the masked score instead rewards exactly the wrong screen. A mask
        grows every time its screen matches something, so a screen that has once
        absorbed a place it is not scores near 1.000 while judging on fewer and fewer
        cells - and it will then outbid the screen that was correctly split off it,
        take the frame back, and grow again. Raw distance cannot be inflated that way:
        it is measured against a fingerprint that never moves."""
        qualified: list[tuple[int, int, Screen, float, set[int]]] = []
        near: tuple[float, int, Screen] | None = None
        for screen in self.screens.values():
            score, stable, differing = agreement(fp, screen.representative,
                                                 screen.volatile, self.cell_delta)
            if stable < MIN_STABLE_CELLS:
                continue
            if near is None or score > near[0]:
                near = (score, stable, screen)
            if score >= self.screen_match:
                qualified.append((len(differing), -stable, screen, score, differing))

        if qualified:
            # Among screens that qualify, the one we were already on wins. Without that,
            # two places whose masks have grown large - a puzzle grid and the same grid
            # one move on - both qualify for nearly every frame, and which of them takes
            # it is settled by a raw-distance tiebreak that can go either way from one
            # frame to the next. The map then fills with edges between them, including
            # `hover` edges, which is a contradiction: a cursor move commits to nothing,
            # so it cannot have gone anywhere.
            #
            # This is hysteresis, and it is the cheap direction on purpose. Qualifying
            # already means "close enough to be the same place", so preferring the
            # incumbent is only asserting what the threshold was asked to decide; the
            # cost is a screen left merged, which the model's naming still splits.
            if holding is not None and any(c[2] is holding for c in qualified):
                qualified = [c for c in qualified if c[2] is holding]
            _, _, best, best_score, best_diff = min(qualified, key=lambda c: c[:2])
            self.match_scores.append(best_score)
            best.observations += 1
            # Everything that moved while we were still calling this the same place
            # is, by definition, not part of what identifies it.
            fresh = best_diff - best.volatile - best.protected
            if fresh:
                best.volatile |= fresh
                if NCELLS - len(best.volatile) < MIN_STABLE_CELLS and not best.degenerate:
                    best.degenerate = True
                    self.controller.note(
                        f"{best.id} has only {NCELLS - len(best.volatile)} stable cells left "
                        f"of {NCELLS} - it is nearly all dynamic content, so its identity is "
                        f"weak and it may be absorbing other screens")
            return best

        screen = Screen(id=f"sc{len(self.screens) + 1:02d}", representative=fp,
                        first_seen=self.actions_taken)
        self.screens[screen.id] = screen
        log(f"  + new screen {screen.id}" + (
            f" (nearest known was {near[2].id} at {near[0]:.3f} on {near[1]} "
            f"stable cells, under the {self.screen_match} threshold)" if near else
            " (the first one)"))
        return screen

    def _touch_variant(self, screen: Screen, fp: bytes) -> tuple[Variant, bool]:
        # Checked against the stored fingerprints before hashing, because a hash
        # answers "identical" and the question is "indistinguishable". A cell mean
        # of 127 against 128 is not a new appearance of anything, and neither is a
        # mascot two frames further into its loop - which is what `animated` removes.
        for variant in screen.variants.values():
            if not (diff_cells(fp, variant.fp, self.cell_delta)
                    - screen.animated - variant.animated):
                variant.observations += 1
                return variant, False

        key = variant_key(fp)
        screen.variant_seq += 1
        if len(screen.variants) >= MAX_VARIANTS:
            # Past the cap, appearances are counted but not stored. Returning one of
            # the stored variants instead would be cheaper and would also file this
            # transition under an appearance that is not the one it produced, so the
            # overflow gets its own honest identity with no image behind it.
            screen.unstored_variants += 1
            return Variant(id=f"{screen.id}-v?", key=key, fp=fp, stored=False,
                           first_seen=self.actions_taken), True

        variant = Variant(id=f"{screen.id}-v{screen.variant_seq}", key=key, fp=fp,
                          first_seen=self.actions_taken)
        name = f"{variant.id}.png"
        self.controller.save_png(self.images / name)
        variant.image = f"images/{name}"
        screen.variants[key] = variant
        self._measure_pulse(screen, variant)
        return variant, True

    def _measure_pulse(self, screen: Screen, variant: Variant) -> None:
        """Find what this appearance moves on its own, now that it is on screen.

        Costs two frames, paid once per stored appearance, and it is self-limiting in
        exactly the case that needs it: a pulsing highlight costs 0.6s the first time
        the row is selected, and every later frame of that pulse is then recognised for
        free instead of minting another appearance. Without it the arithmetic goes the
        other way - one measured run spent 47 presses of a dead `up` key, two thirds of
        the session, because each press produced a "new" appearance and nothing could
        conclude the key did nothing.

        Two guards on believing the result. Nothing may be in flight, which is true at
        every call site: appearances are filed either from an idle observation or after
        `wait_stable` has returned. And a mask wider than `PULSE_LIMIT` is discarded,
        because at that size the honest reading is not "this appearance shimmers" but
        "the game moved on while it was being sampled", and writing that in would give
        this appearance a licence to swallow whatever came next.

        Measured once, deliberately. Growing the mask on every match would repeat the
        volatile mask's mistake: everything that ever differed while we still called it
        this appearance ends up excused, and every frame collapses into one appearance."""
        frames = []
        for _ in range(ANIMATION_SAMPLES - 1):
            time.sleep(ANIMATION_GAP)
            frames.append(fingerprint(self.controller))
        mask: set[int] = set()
        for earlier, later in zip([variant.fp] + frames, frames):
            mask |= diff_cells(earlier, later, self.cell_delta)
        if len(mask) > PULSE_LIMIT:
            self.controller.note(
                f"{variant.id} changed {len(mask)} of {NCELLS} cells while being "
                f"sampled with no input in flight - too much to call animation, so it "
                f"is not excused from telling appearances apart")
            return
        variant.animated = mask - screen.animated
        if variant.animated:
            log(f"  {variant.id} animates {len(variant.animated)} cells of its own "
                f"(beyond {screen.id}'s {len(screen.animated)})")

    # -- hover mapping ------------------------------------------------------

    def map_animation(self, screen: Screen) -> None:
        """Find what this screen moves on its own, before anything is done to it.

        Without this, an animated screen has no stable notion of an appearance at all.
        Appearance identity is exact - two frames are the same appearance when no cell
        differs - so a menu with a looping mascot on it mints a new appearance on every
        single frame, and the consequences are not cosmetic: navigation stops when a
        run of presses reveals nothing new, and nothing is ever not-new, so the
        explorer presses the same dead key until its per-screen cap, comes back through
        the frontier and does it again. Measured on the real thing: `up` on a
        mouse-driven main menu did nothing 47 times, and those 47 presses were two
        thirds of the session.

        Three samples rather than two because one pair can land on two identical frames
        of a slow loop and conclude the screen is still.
        """
        frames = []
        for _ in range(ANIMATION_SAMPLES):
            frames.append(fingerprint(self.controller))
            time.sleep(ANIMATION_GAP)
        for earlier, later in zip(frames, frames[1:]):
            screen.animated |= diff_cells(earlier, later, self.cell_delta)
        if screen.animated:
            log(f"  {screen.id} animates {len(screen.animated)} of {NCELLS} cells "
                f"with no input; they do not count towards a new appearance")
            self._film_animation(screen)

    def _hover_reaction(self, screen: Screen,
                        before: bytes) -> tuple[bytes, set[int]]:
        """Hold the cursor still and return the frame once the reaction has arrived.

        A hover highlight is not on the next frame. Measured across eight points of a
        mouse-driven menu: two of them light up within 50ms, and five more *fade* in
        over 400 to 700ms. Sampling immediately - which is what this did - found the two
        and filed the screen as having one reactive point out of forty. Every point it
        missed is a click candidate that never existed, on a game whose only inputs are
        clicks, so the sweep was reporting the harness's own impatience as a fact about
        the game.

        The test is whether the difference from `before` is still *growing*, not whether
        the screen has gone quiet. Quiet is the wrong question twice over: a slow fade
        moves each cell by so little between consecutive frames that it reads as already
        still, and a screen with a mascot on it never goes quiet at all, so waiting for
        quiet spends the full timeout at all forty points. Growth is the thing actually
        being measured, and it terminates on both.

        Cost is the sweep's whole budget, so it is deliberately asymmetric: a point that
        does nothing costs one hold and stops, while only a point that is visibly
        reacting is allowed to spend more."""
        time.sleep(HOVER_SETTLE)
        after = fingerprint(self.controller)
        ignore = screen.volatile | screen.animated
        reaction = diff_cells(before, after, self.cell_delta) - ignore
        deadline = time.monotonic() + HOVER_REACTION
        while reaction and time.monotonic() < deadline:
            time.sleep(HOVER_GROWTH)
            later = fingerprint(self.controller)
            grown = diff_cells(before, later, self.cell_delta) - ignore
            if len(grown) <= len(reaction):
                break
            after, reaction = later, grown
        return after, reaction

    def map_hover(self, screen: Screen) -> None:
        """Find what reacts to the cursor, without clicking anything.

        A cursor move is the only input that can provoke a visible reaction while
        being safe to sweep blind across a UI nobody has mapped - so this runs
        before any committing action, and its results are what the click candidates
        are drawn from. Games that ignore hover entirely are the common case, so a
        screen that has not reacted after `HOVER_PATIENCE` probes is abandoned rather
        than swept to the end - which is only a claim about the screen because
        `hover_order` makes every prefix cover all of it."""
        screen.hover_probed = True
        order = hover_order([((c + 0.5) / HOVER_COLS, (r + 0.5) / HOVER_ROWS)
                             for r in range(HOVER_ROWS) for c in range(HOVER_COLS)])

        def probe_point(fx: float, fy: float) -> None:
            before = fingerprint(self.controller)
            self.controller.hover(fx, fy)
            after, reaction = self._hover_reaction(screen, before)
            screen.hover_probe_count += 1
            if len(reaction) < 2:
                return
            screen.hotspots.append((fx, fy))
            screen.hover_reactions.append(len(reaction))
            # The control's extent, measured while the evidence for it is on screen.
            # A reaction too wide to crop still gets a box, because the point of this
            # one is to photograph what is under the cursor, not what moved.
            box = cell_box(reaction) or point_box(fx, fy)
            screen.crop_boxes[point_key((fx, fy))] = list(box)
            action = Action("hover", at=(fx, fy))
            shots = self.shots.setdefault(shot_name(screen.id, action), {})
            shots.setdefault("after",
                             self._crop(f"{shot_name(screen.id, action)}-after.png", box))
            # Before the recording, not after the sweep. `_record` is what files a
            # frame as a screen, so a threshold corrected once the sweep is over has
            # already let the sweep's own first reaction invent a screen - and with
            # passes inheriting each other, that screen is then permanent.
            self.relax_match(screen, after)
            self._record(screen, action, before, after, 0,
                         crops={"after": shots["after"]}, box=box)

        started = time.monotonic()
        for fx, fy in order:
            if self.controller.target.forbids(fx, fy):
                continue
            probe_point(fx, fy)
            if not screen.hotspots and screen.hover_probe_count >= HOVER_PATIENCE:
                break

        if not screen.hotspots:
            rescue = 0
            for fx, fy in hover_rescue_points():
                if rescue >= HOVER_RESCUE_PROBES:
                    break
                if self.controller.target.forbids(fx, fy):
                    continue
                probe_point(fx, fy)
                rescue += 1
                if screen.hotspots:
                    break

        if not screen.hotspots:
            screen.hover_inert = True
        self._film_resting(screen)

        log(f"  hover map for {screen.id}: {len(screen.hotspots)} reacting of "
            f"{screen.hover_probe_count} probed in {time.monotonic() - started:.1f}s"
            + (f", widest {max(screen.hover_reactions)} cells" if screen.hover_reactions
               else "")
            + (" (inert, stopped early)" if screen.hover_inert else ""))

    def relax_match(self, screen: Screen, fp: bytes) -> None:
        """Loosen the screen-identity threshold if this sweep proved it is too tight.

        The threshold a pass *starts* with is the one problem `calibrate.py` cannot
        solve, because it recuts from transitions a pass has to have recorded first. That
        was survivable when a session was one long run and its mistakes died with it.
        With passes that inherit each other it is not: a screen invented on the third
        action of pass 1 - one that is really a menu with a button lit - is in the map
        every later pass resumes, and no evidence arriving afterwards removes it.

        A hover sweep is the fix, because of what it is: the cursor moved and nothing was
        committed, so every reaction it recorded is by construction *the same place,
        changed*. That is precisely the population the recut needs a maximum from, it is
        available before any committing action has been taken, and it is measured on this
        game rather than inherited from another one. Measured here: a game whose menu
        buttons light up by 42 cells, run at the 0.94 cut of a game whose highlight moves
        by 16, filed its own hover reactions as travel to another screen.

        One direction only. A sweep that stays well inside the threshold is no evidence
        that the threshold is too loose - it says the reactions were small, not that
        nothing bigger belongs to this screen - and tightening on it would split screens
        on the strength of an absence.

        What is measured is the frame's distance from the screen's *first sighting*, not
        the size of the reaction the cursor just caused. Those are different numbers and
        only the first is the one the threshold is compared against: the previous probe's
        highlight is still gone, and anything the screen animates on its own has moved
        further along, so a 18-cell reaction can sit 36 cells from the representative.
        Relaxing on the reaction size measures the wrong gap and clears it by luck."""
        score, stable, differing = agreement(fp, screen.representative,
                                            screen.volatile, self.cell_delta)
        # The masked count, which is the one the score is built from and therefore the one
        # the threshold judges. Using the raw diff instead relaxes on frames that already
        # passed comfortably, because everything the screen has ever been seen to move is
        # in there and none of it counted against the frame.
        drift = len(differing - screen.volatile)
        if stable < MIN_STABLE_CELLS or drift > HOVER_SAME_PLACE:
            return
        needed = round(1.0 - (drift + SLACK_CELLS) / stable, 3)
        if needed >= self.screen_match:
            return
        loosened = max(needed, MATCH_FLOOR)
        self.controller.note(
            f"screen_match {self.screen_match} -> {loosened}: a cursor move on "
            f"{screen.id} left a frame {drift} of {stable} identifying cells away "
            f"({score:.3f}) without committing to anything, so a frame that far from "
            f"this screen is still this screen")
        self.screen_match = loosened

    # -- close-ups ----------------------------------------------------------

    def _crop(self, name: str, box: tuple[float, float, float, float]) -> str:
        """Save a crop of the live frame and return its path inside this session."""
        return self._crop_frame(name, lambda: self.controller.capture(box))

    def _crop_frame(self, name: str, frame) -> str:
        """Write an already-grabbed crop, or one grabbed by calling `frame`.

        Failures are swallowed deliberately. A missing picture makes the report worse; an
        exception raised here would abandon the action that was being recorded, and losing
        the transition in order to save the photograph of it is the wrong trade."""
        try:
            self.controller.write_capture(self.images / name,
                                          frame() if callable(frame) else frame)
        except Exception as error:                      # noqa: BLE001
            self.controller.note(f"could not crop {name}: {error}")
            return ""
        return f"images/{name}"

    def crop_box(self, screen: Screen, action: Action) -> tuple[float, float, float, float] | None:
        """Where to aim before an action is sent, or None if there is nowhere to aim yet.

        Three sources, in descending order of how much was measured. A click or hover on a
        point the cursor was seen to react to is filmed on the cells that reacted, which is
        the control itself. A point nobody has measured - a control named by a plan on a
        screen that ignores the cursor - gets a default box around it. A key gets the cells
        it moved the last time it was sent here, and nothing on its first press."""
        if action.at is not None:
            measured = screen.crop_boxes.get(point_key(action.at))
            if measured:
                return tuple(measured)                  # type: ignore[return-value]
            return point_box(*action.at)
        learned = self.boxes.get(shot_name(screen.id, action))
        return tuple(learned) if learned else None      # type: ignore[return-value]

    # -- one control's own rectangle ----------------------------------------

    def patch_samples(self, region: tuple[float, float, float, float]) -> int:
        """The `longest` to ask `capture` for, so both of `region`'s sides are measurable.

        `capture` scales to a longest side, which is the right rule for a picture and the
        wrong one for a measurement: a trim counts ink along rows *and* columns, so a wide
        short strip asked for at `ELEMENT_SAMPLES` comes back a few pixels tall and has no
        rows to find a top edge in. The window's own shape is part of the sum - a region
        that is square in fractions is nowhere near square in pixels on a portrait phone
        window - so this reads the client rather than the fractions."""
        _, _, width, height = self.controller.last_good_rect
        wide, high = max(1.0, width * region[2]), max(1.0, height * region[3])
        aspect = max(wide, high) / min(wide, high)
        return int(min(ELEMENT_SAMPLES_MAX,
                       max(ELEMENT_SAMPLES, ELEMENT_THIN * aspect)))

    def snap_box(self, hint: tuple[float, float, float, float]) -> tuple[tuple, str]:
        """Trim a box the model drew to where the pixels put the control's edges.

        Returns the box and a sentence about it, empty when the trim was ordinary. The
        sentence is the reason this is not a silent improvement: three things can go wrong
        and each of them is a finding about the screen rather than a failure to handle.

        - **Nothing in the patch differs from its own background.** The box is on flat
          panel, so either the model put it in the wrong place or the control it named is
          not drawn right now. The hint is kept and said out loud.
        - **The content runs off a side of the padded patch.** Whatever is in there
          continues past the margin, so *that side* was not measured and `_axis` decides
          what to put there. Handled per edge rather than per box, because the common case
          is one edge: a button in a column of identical buttons has its neighbour inside
          the margin, and a trim that took the neighbour's far edge would report one
          control where there are two. Only when all four sides run off is nothing
          measured, and then the hint is kept whole and said out loud.
        - **The trimmed box is under `ELEMENT_SHRINK` of the area described.** The trim found
          a detail inside the element - a label, a highlighted row - and not its edges.
        - **The trimmed centre moved further than `ELEMENT_DRIFT`.** The trim locked on to
          a neighbour or a panel edge. The hint is kept, for the reason on that constant.

        Read off the live window, so it is only meaningful while the screen it belongs to
        is the one on display - which is `locate_elements`' job to establish, not this
        method's.

        Returns `(box, why, kept)`, where `kept` names the sides the trim could not measure
        and left as described. Empty on an ordinary trim, and worth carrying rather than
        discarding: a box measured on three sides is better than the hint and is not the
        same claim as one measured on four."""
        padded = pad_box(hint, ELEMENT_PAD, ELEMENT_PAD_MAX)
        try:
            pixels, width, height = self.controller.capture(padded,
                                                           self.patch_samples(padded))
        except Exception as error:                      # noqa: BLE001
            return hint, f"could not read the pixels around it ({error})", ()
        found = content_box(pixels, width, height)
        if found is None:
            return hint, ("nothing inside it differs from the background around it, so "
                          "either it is somewhere else or it is not drawn on this frame"), ()
        left, top, right, bottom = found
        # Per edge. An edge of the content sitting on an edge of the patch means the content
        # continues out of frame, so nothing was measured on that side. `found` is
        # half-open, hence `>=`.
        open_sides = {"left": left <= 0, "top": top <= 0,
                      "right": right >= width, "bottom": bottom >= height}
        kept = tuple(side for side, out in open_sides.items() if out)
        x0, x1 = _axis(hint[0], hint[2], padded[0], padded[2],
                       left / width, right / width,
                       open_sides["left"], open_sides["right"])
        y0, y1 = _axis(hint[1], hint[3], padded[1], padded[3],
                       top / height, bottom / height,
                       open_sides["top"], open_sides["bottom"])
        if len(kept) == 4:
            return hint, ("its contents reach every edge of the margin around it - "
                          "either it is drawn on the game's own artwork rather than on a "
                          "plain background, or it is bigger than that margin - so its "
                          "own edges were not measured"), kept
        snapped = as_box((x0, y0, x1 - x0, y1 - y0))
        if snapped is None:
            return hint, (f"the pixels in it trim to {x1 - x0:.3f}x{y1 - y0:.3f} of the "
                          f"window, which is too thin or too large to be one control"), kept
        shrunk = (snapped[2] * snapped[3]) / (hint[2] * hint[3])
        if shrunk < ELEMENT_SHRINK:
            return hint, (f"the pixels in it trim to {shrunk:.0%} of the area described, so "
                          f"the trim found something inside it rather than the thing "
                          f"itself"), kept
        drifted = max(abs(box_centre(snapped)[0] - box_centre(hint)[0]) / hint[2],
                      abs(box_centre(snapped)[1] - box_centre(hint)[1]) / hint[3])
        if drifted > ELEMENT_DRIFT:
            return hint, (f"the pixels in it trim to a rectangle whose centre is "
                          f"{drifted:.1f} of its own size away, so the trim found "
                          f"something other than what was described"), kept
        return snapped, "", kept

    def locate_elements(self, screen: Screen, variant: Variant) -> None:
        """Give every element the vetting call named a rectangle, a point and a picture.

        This is what turns "there is a Battle button on this screen, around (0.5, 0.78)"
        into a rectangle measured off the window, a tap point at the middle of it, and a
        close-up of that rectangle alone. All three are worth having for different reasons:
        the rectangle is how a later pass or a wiki refers to the control without
        re-deriving it, the point is what a click is aimed at, and the picture is the only
        evidence anyone can check the other two against.

        Ordered by how much is measured, and every step down is recorded on the element as
        `located`, so nothing in the map claims more precision than it has:

        - `trimmed` - the model drew a box and the pixels inside it found its edges.
        - `trimmed except left`, and the other three sides - the same, on every side but
          those, where the thing inside the box ran off the margin and so has no measured
          edge there; `_axis` says what goes in its place. Named rather than folded into
          `trimmed`, because which side is unmeasured is exactly what a reader checking a
          crop against a screenshot needs to know - and, since the box is only anchored
          where it was measured, how much of its position to believe.
        - `measured movement` - an animation, whose extent comes from `Screen.animated`
          rather than from a trim. See `ELEMENT_KINDS` on why trimming it would be wrong.
        - `described` - the box is the model's, unchanged, because the trim reported one of
          the three things in `snap_box` and the note says which.
        - `a point` - there was no box, only a coordinate, grown to `ELEMENT_DEFAULT`
          before the trim. Common on a first pass and not a problem: the trim usually
          rescues it, and the note says when it did not.

        Guarded on the live frame still being this appearance, because every measurement
        below reads the window rather than the saved image. A screen that has moved on
        gets nothing written to it at all - a rectangle measured off the next screen would
        be wrong in the one way nothing downstream could detect - and is retried on a later
        occurrence, up to `ELEMENT_LOCATES`.

        The guard counts only cells that are *not* already known to move: `Screen.animated`
        and `Variant.animated` for what moves with nothing in flight, and `Screen.volatile`
        for what changed while this was still the same place. Counting them all would make
        this refuse on any live game - measured on Clash Royale, an idle main screen sits 21
        of 576 cells from its own stored appearance because a coin counter went from 113 to
        1 063, against a tolerance of 15 - and every element would come back `described` on
        a screen whose buttons had not moved at all. This is the same subtraction
        `_touch_variant` makes to decide whether an appearance is new, for the same reason:
        a counter ticking is content, not layout."""
        elements = (screen.vetting or {}).get("elements", [])
        pending = [e for e in elements if not e.get("located")]
        if not pending or self.locates[screen.id] >= ELEMENT_LOCATES:
            return
        self.locates[screen.id] += 1
        drifted = (diff_cells(fingerprint(self.controller), variant.fp, self.cell_delta)
                   - screen.animated - variant.animated - screen.volatile)
        if len(drifted) > (1.0 - self.screen_match) * NCELLS:
            self.controller.note(
                f"{screen.id}: not measuring where its {len(pending)} elements are - the "
                f"window has moved {len(drifted)} of {NCELLS} cells away from {variant.id} "
                f"since it was vetted, beyond what is known to move on it, and a rectangle "
                f"read off a different frame would be wrong with nothing to show it")
            return

        animated = cell_box(screen.animated) if screen.animated else None
        for index, element in enumerate(elements, start=1):
            if element.get("located"):
                continue
            label = element.get("label") or "an unnamed element"
            kind = element_kind(element)
            hint = as_box(element.get("box"))
            at = element.get("at")
            if hint is None and not is_fraction(at):
                self.controller.note(
                    f"{screen.id}: cannot place {label!r} - the vetting call gave it "
                    f"neither a usable box ({element.get('box')!r}) nor a point inside "
                    f"the window ({at!r}), so there is nothing to crop or to tap")
                element["located"] = "nowhere"
                continue
            source = "described"
            if hint is None:
                hint = box_around((float(at[0]), float(at[1])), ELEMENT_DEFAULT)
                source = "a point"
            if kind == "animation":
                box, why, source = self._animation_box(hint, animated)
            else:
                box, why, kept = self.snap_box(hint)
                if not why:
                    source = ("trimmed" if not kept
                              else "trimmed except " + " and ".join(sorted(kept)))
            # On the element rather than in `controller.notes`, which is the report's
            # "what went wrong" list. A box that could not be trimmed does not belong
            # there: an element sitting on the game's own painted background is the normal
            # case on a screen that is a painting, the description of it is still usable,
            # and it is only *not a measurement*. So the sentence is filed beside the box
            # and the crop, where a reader is already looking, in the same words - and
            # cleared when a later occurrence does manage to measure it.
            if why:
                element["placed_why"] = why
            else:
                element.pop("placed_why", None)
            element["kind"] = kind
            element["box"] = [round(v, 4) for v in box]
            element["located"] = source
            # Overwritten, and this is the point of the whole exercise: what a click is
            # aimed at becomes the middle of a measured rectangle instead of a coordinate
            # somebody eyeballed off a picture scaled to 1400px. Where the model's own
            # point disagrees with its own box, the box wins and the point is kept beside
            # it, because the two disagreeing is a thing a reader should be able to see.
            if is_fraction(at) and not _inside(box, (float(at[0]), float(at[1]))):
                element["described_at"] = [round(float(at[0]), 4), round(float(at[1]), 4)]
            element["at"] = [round(v, 4) for v in box_centre(box)]
            element["image"] = self._crop(f"{screen.id}-el{index:02d}.png", box)
        tally: dict[str, int] = defaultdict(int)
        for element in pending:
            tally[element.get("located") or "nowhere"] += 1
        log(f"  placed {len(pending)} elements on {screen.id}: "
            + ", ".join(f"{count} {how}" for how, count in sorted(tally.items())))

    @staticmethod
    def _animation_box(hint: tuple[float, float, float, float],
                       animated: tuple | None) -> tuple[tuple, str, str]:
        """Where a moving region is, from the cells measured to move rather than from a trim.

        The intersection of the two, not one or the other. `Screen.animated` is every cell
        that moved with nothing in flight, so on a screen with a spinner *and* a waving
        mascot it covers both and its box covers the gap between them; the hint is which of
        them the model meant. Where they do not overlap at all, the claim and the
        measurement disagree and that is worth a sentence: an element called an animation in
        a place where nothing was seen to move is either a still, or movement slower than
        the three frames `map_animation` sampled."""
        if animated is None:
            return hint, ("it is described as animated, but this screen was measured with "
                          "nothing in flight and no cell of it moved"), "described"
        overlap = as_box(_intersect(hint, animated))
        if overlap is None:
            return hint, (f"it is described as animated, and the cells this screen was "
                          f"measured to move are elsewhere - around "
                          f"({box_centre(animated)[0]:.2f}, {box_centre(animated)[1]:.2f}), "
                          f"not ({box_centre(hint)[0]:.2f}, {box_centre(hint)[1]:.2f})"), \
                "described"
        return overlap, "", "measured movement"

    def _film_resting(self, screen: Screen) -> None:
        """Photograph every reacting control with the cursor off it.

        The sweep can only take the hovered picture. At the moment a point is known to
        react the cursor is already sitting on it, and the frame from before the move is
        gone - so the resting pictures are taken together at the end, with the cursor
        parked somewhere that reacted to nothing. One settle for the whole screen instead
        of one per control, which is the difference between 0.5s and 20s on a menu with
        forty reacting points.

        The pair is the point. A picture of a lit button on its own is a picture of a
        button; next to the same pixels unlit, it is a statement about what the cursor
        does to it, and that statement is the one thing the full-window frame cannot make
        at 43 pixels to a cell."""
        if not screen.hotspots:
            return
        park = self._parking_spot(screen)
        if park is None:
            self.controller.note(f"every free point on {screen.id} reacts to the cursor, so "
                                 f"there is nowhere to park it and its controls have no "
                                 f"resting picture")
            return
        self.controller.hover(*park)
        time.sleep(HOVER_SETTLE)
        for point in screen.hotspots:
            action = Action("hover", at=point)
            shots = self.shots.setdefault(shot_name(screen.id, action), {})
            box = screen.crop_boxes.get(point_key(point))
            if "before" in shots or not box or point_key(point) in screen.sticky:
                continue
            resting = self._crop(f"{shot_name(screen.id, action)}-before.png",
                                 tuple(box))
            if resting and self._identical(resting, shots.get("after", "")):
                # Not a resting picture at all - see `Screen.sticky`. Kept out of the
                # pair, because two of the same picture labelled `at rest` and `with the
                # cursor on it` is a statement that the cursor does nothing, which is the
                # opposite of what was measured when this point was found.
                (self.out / resting).unlink(missing_ok=True)
                screen.sticky.append(point_key(point))
                self.filmed.add(shot_name(screen.id, action))
                continue
            shots["before"] = resting
            self._file_crop(screen.id, action.id, "before", shots["before"])
            # Finished, so a later cursor move to the same point does not re-film it. That
            # would be a pair whose before frame was taken with the cursor already on the
            # control, which is the same picture twice.
            self.filmed.add(shot_name(screen.id, action))
        if screen.sticky:
            self.controller.note(
                f"{len(screen.sticky)} of {len(screen.hotspots)} reacting points on "
                f"{screen.id} look identical with the cursor parked elsewhere, so the "
                f"cursor is moving this screen's selection rather than lighting a control")

    def _identical(self, one: str, other: str) -> bool:
        """Whether two saved crops are the same picture, byte for byte.

        Sound only because both went through the same encoder at the same size from the
        same box, which is true of every pair this asks about; it is not a general image
        comparison."""
        if not one or not other:
            return False
        try:
            return (self.out / one).read_bytes() == (self.out / other).read_bytes()
        except OSError:
            return False

    def _parking_spot(self, screen: Screen) -> tuple[float, float] | None:
        """A probe point that is allowed and as far as possible from anything reactive.

        Chosen from the hover grid rather than from a corner, because a corner is not
        automatically safe: the denylist exists precisely because some points must never be
        touched, and a hard-coded parking place is a per-game fact in a file that is not
        allowed to hold one."""
        free = [((c + 0.5) / HOVER_COLS, (r + 0.5) / HOVER_ROWS)
                for r in range(HOVER_ROWS) for c in range(HOVER_COLS)]
        free = [p for p in free
                if not self.controller.target.forbids(*p) and p not in screen.hotspots]
        if not free:
            return None
        return max(free, key=lambda p: min(abs(p[0] - h[0]) + abs(p[1] - h[1])
                                           for h in screen.hotspots))

    def _film_animation(self, screen: Screen) -> None:
        """Take pictures of what the measurement just found moving on its own.

        A second pass rather than keeping the frames the measurement used, because which
        cells move is only known once all three fingerprints have been compared and a crop
        has to be aimed before it is taken. It costs one more sampling cycle, paid only on
        a screen that was measured to move at all, so a still menu pays nothing."""
        if screen.animation:
            return
        box = cell_box(screen.animated)
        if box is None:
            self.controller.note(
                f"{screen.id} moves {len(screen.animated)} of {NCELLS} cells with no input "
                f"- too much of the window to crop, so its own image is the picture of it")
            return
        for index in range(ANIMATION_SAMPLES):
            shot = self._crop(f"{screen.id}-anim{index + 1}.png", box)
            if shot:
                screen.animation.append(shot)
            time.sleep(ANIMATION_GAP)

    def _file_crop(self, screen_id: str, action_id: str, slot: str, path: str) -> None:
        """Attach a picture taken after the fact to the edges it belongs to.

        The resting pictures are the case: the transition was recorded during the sweep,
        and the frame it wants was taken minutes later with the cursor parked. Filed with
        `setdefault`, so a picture never replaces one taken on the occasion itself."""
        if not path:
            return
        for transition in self.transitions.values():
            if transition.source == screen_id and transition.action.id == action_id:
                transition.crops.setdefault(slot, path)

    def candidate_crops(self, screen: Screen, variant: Variant,
                        candidates: list[Action]) -> list[dict]:
        """Close-ups to send with a vetting call, as {label, path} pairs.

        Two kinds, and which one is available says what the call is for. The first
        appearance of a screen is being asked what its controls are, so it gets the
        measured rest/hover pairs of the points it is ruling on - capped, widest reaction
        first, since a wide reaction is the best available evidence that a point is a
        control rather than a stray repaint. A later appearance is being asked what is
        selected in it, so it gets one crop of the cells that differ from the screen's
        first sighting, which is where the selection has to be."""
        crops: list[dict] = []
        # By point rather than by action id: a hotspot's measured rest/hover pair is
        # evidence about the *place*, so it is the right close-up for whichever mouse
        # action is being ruled on there - a click on it, or a wheel over it.
        wanted = {tuple(a.at) for a in candidates
                  if a.kind in MOUSE_KINDS and a.at is not None}
        for point, cells in sorted(zip(screen.hotspots, screen.hover_reactions),
                                   key=lambda pair: -pair[1]):
            if len(crops) >= VET_CROPS * 2:
                break
            if tuple(point) not in wanted:
                continue
            shots = self.shots.get(shot_name(screen.id, Action("hover", at=point)), {})
            # A sticky point has no resting picture and its single crop must not claim to
            # be half of a pair, or the model reads the absent one as evidence of nothing.
            hovered = ("with the cursor on it, and it stayed this way after the cursor left"
                       if point_key(point) in screen.sticky else "with the cursor on it")
            for slot, what in (("before", "at rest"), ("after", hovered)):
                if shots.get(slot) and (self.out / shots[slot]).exists():
                    crops.append({"label": f"({point[0]:.3f}, {point[1]:.3f}) {what}, "
                                           f"{cells} cells reacted",
                                  "path": self.out / shots[slot]})
        if screen.vetting is not None:
            differs = diff_cells(variant.fp, screen.representative,
                                 self.cell_delta) - screen.animated
            box = cell_box(differs)
            if box is not None:
                variant.differs_image = self._crop(f"{variant.id}-differs.png", box)
                if variant.differs_image:
                    crops.append({"label": f"the {len(differs)} cells where this appearance "
                                           f"differs from {screen.id}'s first sighting",
                                  "path": self.out / variant.differs_image})
        return crops

    # -- policy -------------------------------------------------------------

    def permitted(self, screen: Screen, variant: Variant,
                  action: Action) -> tuple[bool, str]:
        """Whether this action may be taken, and if not, why not.

        The verdict for a click is looked up on the screen and the verdict for a key
        on the variant, matching how each one picks its target: by position, or by
        whatever happens to be selected."""
        if not action.committing:
            return True, ""
        if action.kind in MOUSE_KINDS:
            if not self.allow_clicks:
                return False, "mouse actions are disabled for this session (--no-clicks)"
            why = self.controller.target.forbids(*action.at)
            if not why and action.kind == "drag":
                # Both ends and the line between them, because a drag holds the button
                # down all the way across - see `Target.forbids_path`. Checked here as
                # well as in the controller so the refusal is a recorded finding with a
                # reason, rather than a PermissionError mid-mission.
                why = (self.controller.target.forbids(*action.to)
                       or self.controller.target.forbids_path(action.at, action.to))
            if why:
                return False, why
            source = screen.vetting
        else:
            source = variant.vetting
        if source is None:
            return False, UNVETTED
        verdict = source.get("actions", {}).get(action.id)
        if verdict is None:
            return False, "no verdict for this action"
        if not verdict.get("safe"):
            return False, verdict.get("why", "judged unsafe")
        return True, ""

    def screen_actions(self, screen: Screen) -> list[Action]:
        """Actions whose meaning does not depend on what is selected.

        Ordered by how much evidence is behind them, because `next_action` takes the
        first one it may have. Arrow keys need no permission. Clicks are aimed at points
        the cursor was measured to react to. Then the blind probes, which are aimed at
        nothing but the middle of the window - so they go last, and a screen with plenty
        of measured candidates spends its budget on those first.

        The escalation is the interesting half. One wheel probe each way and one drag are
        offered on every screen; the rest are offered only where those proved the screen
        responds. Without that gate a hover-inert screen with eight hotspots would carry
        twenty blind candidates, every one of them needing a verdict and a settle, on a
        screen that ignores the wheel entirely - and the frontier search would keep
        travelling back to it because they were all still untried."""
        actions = [Action("key", key=k) for k in NAV_KEYS]

        # Text-labeled controls often do not react to hover, so use vetted element
        # coordinates first and keep hotspots as a fallback sweep.
        seen_clicks: set[str] = set()
        if screen.vetting is not None:
            for element in screen.vetting.get("elements", []):
                at = element.get("at")
                if not is_fraction(at):
                    continue
                point = (float(at[0]), float(at[1]))
                key = point_key(point)
                if key in seen_clicks:
                    continue
                seen_clicks.add(key)
                actions.append(Action("click", at=point))
        for point in screen.hotspots:
            key = point_key(point)
            if key in seen_clicks:
                continue
            seen_clicks.add(key)
            actions.append(Action("click", at=point))

        actions += [Action("scroll", at=PROBE_AT, notches=-SCROLL_NOTCHES),
                    Action("scroll", at=PROBE_AT, notches=SCROLL_NOTCHES),
                    probe_drag(PROBE_AT, DRAG_DIRECTIONS[0])]
        if screen.scrolls:
            # A screen that scrolls in the middle may scroll differently over a control -
            # a list inside a panel, a value under the cursor - and the hotspots are the
            # only places on it anything is known to be.
            for point in screen.hotspots:
                actions += [Action("scroll", at=point, notches=-SCROLL_NOTCHES),
                            Action("scroll", at=point, notches=SCROLL_NOTCHES)]
        if screen.drags:
            actions += [probe_drag(PROBE_AT, d) for d in DRAG_DIRECTIONS[1:]]
        return actions

    @staticmethod
    def variant_actions() -> list[Action]:
        return [Action("key", key=k) for k in COMMIT_KEYS]

    def variant_has_work(self, screen: Screen, variant: Variant) -> bool:
        """Whether this appearance still has a committing key worth reaching.

        Unvetted counts as work only while the screen's vetting budget lasts -
        without that, an exhausted budget would leave every appearance looking
        eternally promising and the explorer navigating between them forever."""
        if not variant.stored:
            return False
        for action in self.variant_actions():
            if action.id in variant.tried:
                continue
            if variant.vetting is None:
                if screen.vet_budget > 0:
                    return True
                continue
            if self.permitted(screen, variant, action)[0]:
                return True
        return False

    def pending_actions(self, screen: Screen, variant: Variant) -> Iterator[Action]:
        """Every untried permitted action here, in the order `next_action` takes them.

        Split out of `next_action` so a pass can say what it is about to do *and* what
        follows it. One action at a time reads as a series of surprises; the same action
        with the next one beside it reads as a queue being worked through, which is what
        it is. Sharing the ordering by construction, rather than by two functions agreeing
        to sort the same way.

        Side-effect free, for the reason `next_action` gives below."""
        for action in self.screen_actions(screen):
            if action.id not in screen.tried and self.permitted(screen, variant, action)[0]:
                yield action
        for action in self.variant_actions():
            if action.id not in variant.tried and self.permitted(screen, variant, action)[0]:
                yield action
        if self.nav_spent(screen) < NAV_BUDGET and any(
                v is not variant and self.variant_has_work(screen, v)
                for v in screen.variants.values()):
            navigator = self.navigator(screen)
            if navigator is not None:
                yield navigator

    def next_action(self, screen: Screen, variant: Variant) -> Action | None:
        """An untried permitted action, cheapest and most reversible first.

        Arrow keys lead because they need no permission and usually only move a
        highlight - so a keyboard menu gets mapped before anything is committed to,
        which is both the safe order and the informative one. Then this appearance's
        committing keys, then clicks.

        The last clause is what makes a keyboard UI explorable at all. Once the
        arrow keys have gone stale and this row's `enter` is settled, other rows of
        the same menu still have untried `enter`s - and the only way to reach a row
        is to navigate to it. So an arrow key goes back on the table as the move that
        crosses an *intra-screen* frontier, which is a different job from the one it
        was retired for.

        Deliberately free of side effects: the frontier search calls this on every
        screen it walks past, and a version that marked actions tried while looking
        at them would consume the very frontier it was searching for."""
        return next(self.pending_actions(screen, variant), None)

    def aimed_at(self, screen: Screen, action: Action) -> str:
        """The vetted element this action is aimed at, named, or "" for none.

        For the running commentary, so a watched pass says "the Damage stat" and not only a
        pair of coordinates - the whole reason a reader is watching is to know what is
        about to be touched. Matched on `point_key`, the same rounding `Action.id` uses, so
        a click minted from an element's centre finds that element; a blind probe that
        happens to land on the same point is named the same way, which is correct - the
        line is about where the input goes, not about where it came from."""
        if action.at is None or screen.vetting is None:
            return ""
        wanted = point_key(action.at)
        for element in screen.vetting.get("elements", []):
            at = element.get("at")
            if is_fraction(at) and point_key((float(at[0]), float(at[1]))) == wanted:
                return element.get("label") or ""
        return ""

    def nav_spent(self, screen: Screen) -> int:
        """How many navigation presses this screen has absorbed, all keys together.

        The clause in `next_action` that returns a navigator is the one hole in the
        per-key caps: it exists to cross an *intra-screen* frontier and so it must be
        able to hand back a key that `screen.tried` has retired. That is right when the
        key walks a list, and unbounded when it does not - a dead key still produces
        appearances the harness cannot tell apart, each of them with untried committing
        keys, each of them therefore evidence that navigating is worth another press.
        One total makes the hole finite without taking away what it is for."""
        return self.repeats[screen.id].get("!nav", 0)

    def navigator(self, screen: Screen) -> Action | None:
        """An arrow key already observed to change this screen's appearance.

        Chosen from evidence rather than assumed, because which arrow walks a list is
        a property of the game: a vertical menu ignores left and right, and a
        horizontal one ignores up and down. Falls back to `down` only when nothing
        has been observed yet."""
        moves = [t for t in self.transitions.values()
                 if t.source == screen.id and t.kind == "variant"
                 and t.action.kind == "key" and t.action.key in NAV_KEYS]
        if moves:
            return max(moves, key=lambda t: t.count).action
        return Action("key", key="down")

    def screen_has_frontier(self, screen: Screen) -> bool:
        """Whether anything remains to be tried on a screen we are not currently on.

        Checked without a live frame, so it cannot ask about the current appearance -
        it asks whether *any* appearance still has work, which is the right question
        for "is it worth travelling back there"."""
        for action in self.screen_actions(screen):
            if action.id not in screen.tried:
                return True
        return any(self.variant_has_work(screen, v) for v in screen.variants.values())

    def prune_blocked(self, screen: Screen, variant: Variant) -> None:
        """Retire the actions that will never be allowed, recording why.

        Separate from `next_action` so the search stays pure, and kept in the output
        because "the model would not clear this button" is a finding about the game -
        an unexplored branch with a stated reason, rather than a silent gap."""
        for action, tried in ([(a, screen.tried) for a in self.screen_actions(screen)]
                              + [(a, variant.tried) for a in self.variant_actions()]):
            if action.id in tried:
                continue
            ok, why = self.permitted(screen, variant, action)
            if ok:
                continue
            scope = screen.id if tried is screen.tried else variant.id
            self.blocked[f"{scope} {action.id}"] = why
            # Only *permanent* refusals retire the action. "Not vetted yet" is a
            # state of this session, not a property of the control, and burning the
            # action on it would leave it untried even after a later pass clears it.
            if why != UNVETTED:
                tried.add(action.id)

    def route_to_frontier(self, screen: Screen) -> Action | None:
        """The first step toward the nearest screen that still has something untried.

        Breadth-first over the screen-changing transitions already observed. Without
        this, a session that exhausts a screen either sits there or wanders at
        random; with it, exhausting a screen is what pushes exploration outward."""
        outgoing: dict[str, list[tuple[Action, str]]] = {}
        for transition in self.transitions.values():
            if transition.kind == "screen":
                outgoing.setdefault(transition.source, []).append(
                    (transition.action, transition.dest))

        queue = deque([(screen.id, None)])
        seen = {screen.id}
        while queue:
            here, first = queue.popleft()
            target_screen = self.screens.get(here)
            if first is not None and target_screen is not None \
                    and self.screen_has_frontier(target_screen):
                return first
            for action, dest in outgoing.get(here, []):
                if dest not in seen:
                    seen.add(dest)
                    queue.append((dest, first or action))
        return None

    # -- acting -------------------------------------------------------------

    def perform(self, action: Action, during=None) -> None:
        """Send one action. `during` is a camera shutter for the moment a mouse button is
        held down, which is the only moment a pressed control exists - see
        `Controller.click`. Ignored for anything that has no such moment."""
        if action.kind == "hover":
            self.controller.hover(*action.at)
        elif action.kind == "click":
            self.controller.click(*action.at, button=action.button,
                                  modifiers=action.modifiers, during=during)
        elif action.kind == "drag":
            self.controller.drag(action.at, action.to, button=action.button,
                                 modifiers=action.modifiers, during=during)
        elif action.kind == "scroll":
            self.controller.scroll(*action.at, action.notches,
                                   horizontal=action.horizontal,
                                   modifiers=action.modifiers)
        elif action.modifiers:
            with self.controller.holding(*action.modifiers):
                self.controller.press(action.key)
        else:
            self.controller.press(action.key)

    def _record(self, screen: Screen, action: Action, before_fp: bytes,
                after_fp: bytes, settle_ms: int, crops: dict | None = None,
                box: tuple[float, float, float, float] | None = None
                ) -> tuple[Transition, bool]:
        before_variant = next((v for v in screen.variants.values()
                               if not diff_cells(before_fp, v.fp, self.cell_delta)), None)
        differing = diff_cells(before_fp, after_fp, self.cell_delta)
        changed = len(differing)

        if changed == 0 and before_variant is not None:
            # An identical picture cannot be a different place, and classifying it again
            # can say otherwise: two screens with large volatile masks - a puzzle grid
            # and the same grid one move on - each match almost anything, so which one
            # wins is decided by a tiebreak the pixels have no say in, and an action that
            # moved nothing gets recorded as travel between them. That is not a cosmetic
            # mislabel. It enters the evidence as a screen change of zero cells, and the
            # recut then sees a population of screen changes that starts below every
            # same-place move, concludes no threshold separates them, and gives up on
            # geometry for the whole game.
            after_screen, after_variant, is_new = screen, before_variant, False
        else:
            after_screen, after_variant, _, is_new = self.observe(after_fp, holding=screen)

        if after_screen.id != screen.id:
            kind = "screen"
        elif after_variant.key != (before_variant.key if before_variant else None):
            kind = "variant"
        else:
            kind = "none"

        # Whether the blind modalities do anything here, which is what decides how many
        # more of them are worth spending - see `screen_actions`. Recorded on the screen
        # the action was sent *from*, and only on a real effect: a probe that changed
        # nothing is the answer "this screen does not do that", and it is the whole point
        # of spending one probe before offering eight.
        #
        # Cells the screen moves on its own do not count, and `kind` is not the test.
        # A shimmering logo makes every action on the screen look like it did something -
        # it is enough to leave the before frame matching no known appearance, which is
        # then classified as a variant change of *zero* cells. Taken as evidence, an
        # animated screen would open the gate on every one of its own probes.
        if action.kind in ("scroll", "drag") and differing - screen.animated:
            setattr(screen, "scrolls" if action.kind == "scroll" else "drags", True)

        self.standing = after_screen.id
        # Every occurrence, and including the ones that changed nothing, because the pass
        # has just announced this action and a reader is owed a result under it. "Nothing
        # visible changed" is a finding rather than the absence of one: seven of the twelve
        # actions in the 3-minute Clash Royale pass were exactly that, and they are what
        # says a stat panel is a stat panel and not a menu. The old line printed only for
        # new, effective transitions, so most of a quiet screen's work was silent.
        #
        # Hovers excepted, and they are the only exception: they arrive forty at a time from
        # `map_hover`, they are free and commit to nothing, and `announce` never sees them.
        # A result line with no announced action above it reads as input nobody asked for,
        # which is the confusion this whole commentary exists to remove. The sweep prints
        # its own one-line summary instead.
        if action.kind != "hover":
            log(f"      -> {EFFECT_WORDS[kind]}"
                + (f", now on {after_screen.id}" if kind == "screen" else "")
                + f", {changed} cells, {settle_ms}ms")
        key = f"{screen.id}|{action.id}|{kind}|{after_screen.id}"
        pictures = {slot: path for slot, path in (crops or {}).items() if path}
        existing = self.transitions.get(key)
        if existing:
            existing.count += 1
            # Only pictures taken on *this* occurrence are passed in, so this fills the
            # slots an earlier one could not - the before frame of a key, which does not
            # exist until the key has been pressed once and the camera knows where to aim.
            existing.crops.update(pictures)
            existing.crop_box = existing.crop_box or list(box or ())
            return existing, is_new

        transition = Transition(
            id=f"tr{len(self.transitions) + 1:03d}", source=screen.id, dest=after_screen.id,
            action=action, kind=kind,
            from_variant=before_variant.id if before_variant else "",
            to_variant=after_variant.id, changed=changed, settle_ms=settle_ms,
            first_seen=self.actions_taken, crops=pictures, crop_box=list(box or ()))
        self.transitions[key] = transition
        return transition, is_new

    def look(self) -> tuple[Screen, Variant, bytes]:
        """Make the window readable, classify what is on it, and settle the books.

        Split out of `step` so that anything driving this session - the explorer, or a
        mission executing someone else's plan - perceives through one code path. A
        second implementation of "where are we" is a second place for the handover
        credit below to be forgotten, and forgetting it does not fail loudly: it files
        an edge under the wrong action."""
        handovers = self.controller.handovers
        self.controller.ensure_readable()
        screen, variant, before_fp, _ = self.observe(
            holding=self.screens.get(self.standing))

        if self.controller.handovers > handovers and self.pending is not None:
            # The game moved to a window nobody was driving, and the action that made it
            # happen was the last one taken - a click on a launcher's play button, whose
            # window did not exist yet when the click's result was read 0.4s later. It was
            # measured at 2.8s on the launcher this was written for.
            #
            # Waiting for it at the time was the other option and it is much worse: the
            # wait would have to be paid after *every* committing action, most of which
            # start nothing, and at this game's own measured startup that is a third of a
            # pass spent watching for a window that is not coming. Crediting it late costs
            # nothing and records the same edge.
            #
            # Without this the handover is a discontinuity rather than a route: the click
            # is recorded as a change to the launcher's own picture, the game's screen
            # arrives with no edge leading into it, and every later pass concludes there
            # is no way back to it - which is what the first sweep of a launcher-based
            # game actually recorded.
            source, action, source_fp, settle = self.pending
            self._record(source, action, source_fp, before_fp, settle)
            self.pending = None
        return screen, variant, before_fp

    def take(self, screen: Screen, variant: Variant, before_fp: bytes,
             action: Action) -> tuple[Transition, bool, int]:
        """Do one action and record what it did. The only way anything is ever sent.

        Marks the action tried *before* performing it, so an action that kills the
        window is not the first thing the next pass tries again. Which set it is marked
        in follows what the action names: a committing key acts on whatever is
        selected, so it belongs to the appearance, and everything else to the screen.

        Up to three close-ups are taken around it - the target untouched, the target with
        the mouse button still down, and the target afterwards - and the rule for when is
        the only interesting part. They are filmed together, on the first occurrence where
        there is somewhere to aim *before* the action is sent, and never again. Filling the
        slots piecemeal across occurrences was the first attempt and it produced a lie: a
        key whose before frame could only be taken on the second press ended up with a
        before picture of the state the first press had already left the screen in, which
        is pixel-for-pixel its own after picture, filed as a pair. Until an action has a
        box, each occurrence records a provisional `after` aimed at whatever moved, which
        is the one thing that can always be aimed because it is aimed at the answer."""
        (variant.tried if action.committing and action.kind == "key"
         else screen.tried).add(action.id)
        self.actions_taken += 1
        stem = shot_name(screen.id, action)
        shots = self.shots.setdefault(stem, {})
        taken: dict[str, str] = {}
        box = None if stem in self.filmed else self.crop_box(screen, action)

        if action.kind in ("scroll", "drag"):
            # The cursor has to travel to the target before either of these can be sent,
            # and on a game whose controls light under the hand that journey repaints part
            # of the window. Measured on the synthetic menu in `selftest.py`: a wheel probe
            # at the middle of the window came back with 40 changed cells, every one of
            # them a button lighting up and going dark, and not one of them the wheel.
            #
            # So the before frame is read *after* the journey, which makes the pair say
            # what the modality did rather than that the cursor arrived. It matters more
            # here than for a click, where the hover reaction is part of what the click
            # did: for a blind probe the difference is the entire evidence, and it decides
            # whether the screen gets eight more probes or none.
            self.controller.hover(*action.at, settle=HOVER_SETTLE)
            before_fp = fingerprint(self.controller)

        if box is not None:
            shots["before"] = taken["before"] = self._crop(f"{stem}-before.png", box)
        # A pressed control springs back before the release, so the frame everything else
        # reads is taken too late to contain it. This is the only shutter that fires while
        # an input is in flight, and what it does there is grab pixels and nothing else:
        # writing the PNG takes most of the 80ms the button is meant to be down for, so
        # the file is written below, once the click is over.
        held: list[tuple[bytes, int, int]] = []
        self.perform(action, during=(lambda: held.append(self.controller.capture(box)))
                     if action.kind in ("click", "drag") and box is not None else None)
        settle = self.controller.wait_stable()
        after_fp = fingerprint(self.controller)
        for frame in held:
            shots["pressed"] = taken["pressed"] = self._crop_frame(
                f"{stem}-pressed.png", frame)

        moved = diff_cells(before_fp, after_fp, self.cell_delta) - screen.animated
        after_box = cell_box(moved)
        if box is not None:
            # Deliberately the same box as the before frame rather than the one the diff
            # suggests. A pair of pictures of two different rectangles is not a pair, and
            # what this pair is evidence about is the control - where the effect landed is
            # already recorded as a cell count and as the two full-window frames.
            shots["after"] = taken["after"] = self._crop(f"{stem}-after.png", box)
            self.filmed.add(stem)
        elif after_box is not None and stem not in self.filmed:
            shots["after"] = taken["after"] = self._crop(f"{stem}-after.png", after_box)
        if after_box is not None:
            # Where to aim next time. Not overwritten once set: the aim has to be the same
            # on the occurrence that films the pair as on the one that measured it.
            self.boxes.setdefault(stem, list(after_box))

        transition, found_something = self._record(
            screen, action, before_fp, after_fp, int(settle * 1000),
            crops=taken, box=box or after_box)
        # Held in case this action started something that has not appeared yet.
        self.pending = (screen, action, before_fp, int(settle * 1000))
        return transition, found_something, int(settle * 1000)

    def ask_about(self, screen: Screen, variant: Variant, actions: list[Action],
                  retire_unruled: bool = False) -> bool:
        """Buy a verdict for actions nobody has ruled on yet.

        The explorer only ever proposes actions it measured - arrow keys and points the
        cursor was seen to react to - so its vetting call can carry every candidate at
        once. A plan can name a control the cursor never reacted to, which is the whole
        reason mission mode exists for a game that ignores hover, and that action
        arrives with no verdict. So it gets its own call, merged into the same verdict
        dictionaries `permitted` already reads. Nothing here can unlock anything on its
        own: a failed call leaves the action exactly as locked as it was.

        Every point named gets a close-up of itself, which matters more here than anywhere
        else. On a screen the cursor is inert on, the only reason to believe there is a
        control at (0.500, 0.720) is a plan that said so, and a 43-pixel-wide patch of a
        scaled-down frame does not give the model enough to disagree with it.

        `retire_unruled` files a refusal for anything the call came back without a verdict
        for, said in words that make clear it is not the model's judgement. Off for a
        mission, whose planner can name the same control again next time and should get a
        real answer rather than an inherited shrug; on for the explorer, where the
        alternative is a candidate that is offered, refused and re-offered forever. It also
        keeps the close-up the question was asked with attached to something in the map,
        which an unruled action would otherwise leave orphaned on disk."""
        if self.vetter is None:
            return False
        asked: dict[str, str] = {}
        for action in actions:
            if action.at is None:
                continue
            shot = self._crop(f"ask-{shot_name(screen.id, action)}.png",
                              self.crop_box(screen, action) or point_box(*action.at))
            if shot:
                asked[action.id] = shot
        crops = [{"label": f"{action_id}, the point this asks about", "path": self.out / shot}
                 for action_id, shot in asked.items()]
        try:
            verdict = self.vetter(self.out / variant.image, screen, variant, actions, crops)
        except Exception as error:                      # noqa: BLE001
            self.controller.note(f"could not get a verdict for "
                                 f"{', '.join(a.id for a in actions)} ({error})")
            return False
        for action in actions:
            entry = verdict.get("actions", {}).get(action.id)
            if entry is None:
                if not retire_unruled:
                    continue
                # Not a verdict, and worded so nobody reads it as one. A model that was
                # shown the point and would not rule on it has still settled the question
                # for this session, and leaving the gap open instead means the action is
                # offered, refused for want of a verdict, and offered again every step.
                entry = {"safe": False,
                         "why": "shown to the model, which returned no verdict for it"}
            scope = variant if action.committing and action.kind == "key" else screen
            if scope.vetting is None:
                # Everything else on the screen stays locked: this is one verdict, not
                # the screen's vetting call, and the name and elements it came back with
                # are not recorded here for the same reason.
                scope.vetting = {"actions": {}}
            # The picture the verdict was bought with, kept on the verdict. This is the
            # only route by which a close-up reaches the map without a transition to hang
            # it on - the action may well never be permitted, and "here is what the model
            # was looking at when it refused" is the part worth being able to check.
            if action.id in asked:
                entry["image"] = asked[action.id]
            scope.vetting.setdefault("actions", {})[action.id] = entry
            log(f"  verdict for {action.id} on {scope.id}: "
                f"{'cleared' if entry.get('safe') else 'refused'} - {entry.get('why', '')}")
        return True

    def ask_about_escalated(self, screen: Screen, variant: Variant) -> None:
        """Buy verdicts for the blind probes that exist only because the gate opened.

        Every other candidate the explorer proposes is known before the screen's vetting
        call: the arrow keys are fixed and the hotspot clicks come out of the hover map,
        which finishes first. The escalated wheel and drag probes are the one exception -
        they are minted by `screen_actions` only after a probe proved the screen answers
        the modality, which is necessarily *after* the vetting call has been paid for. So
        they arrive with no verdict, and a missing verdict is not a temporary refusal:
        `prune_blocked` retires everything except `UNVETTED` permanently, and a retired id
        stays retired through every later pass because `tried` is on the map. Measured on
        Tile Tale: all 16 escalated wheel probes on its settings menu were retired unsent
        on first offer, so the escalation never once fired.

        Restricted to the blind modalities on purpose. A hotspot click with no verdict
        would mean the hover map grew after vetting, which is a different bug, and buying
        it a call here would hide it.

        A call that fails outright leaves everything as locked as it was, and is bounded by
        `ESCALATION_ASKS` within the pass rather than retired, so the next pass tries
        again. Anything the call answers with silence is retired by `retire_unruled`."""
        if self.vetter is None or screen.vetting is None:
            return
        known = screen.vetting.get("actions", {})
        fresh = [a for a in self.screen_actions(screen)
                 if a.kind in ("scroll", "drag")
                 and a.id not in known and a.id not in screen.tried]
        if not fresh or self.escalation_asks[screen.id] >= ESCALATION_ASKS:
            return
        self.escalation_asks[screen.id] += 1
        log(f"  {screen.id} answered the wheel or the drag, so {len(fresh)} escalated "
            f"probes need a verdict nobody has been asked for")
        self.ask_about(screen, variant, fresh, retire_unruled=True)

    def step(self) -> str:
        screen, variant, before_fp = self.look()

        if not screen.hover_probed:
            # Animation first, then hover, then vet. Each needs the one before it: a
            # hover reaction is "cells changed that do not change by themselves", and
            # the click candidates handed to the vetting call are exactly the points
            # seen to react, so both maps have to finish before there is anything to
            # ask about.
            self.map_animation(screen)
            self.map_hover(screen)

        if self.wants_vetting(screen, variant):
            # Rebound, because vetting can decide this appearance was never this
            # screen. Everything below has to act on the screen it actually belongs
            # to, or the action gets recorded against the place it was mistaken for.
            screen = self.vet(screen, variant)

        # After vetting and before anything reads a candidate's coordinates, because this
        # is what those coordinates *are*: it replaces every element's eyeballed point with
        # the middle of a rectangle measured off the window. A step that aimed first and
        # measured afterwards would spend the accurate coordinate on the following step and
        # send this one at the guess.
        if screen.vetting is not None:
            self.locate_elements(screen, variant)

        # Before pruning, not after: pruning is what retires a candidate with no verdict,
        # and the escalated probes are the only candidates that can be minted after the
        # vetting call that would have covered them.
        self.ask_about_escalated(screen, variant)
        self.prune_blocked(screen, variant)
        queued = list(islice(self.pending_actions(screen, variant), 2))
        action = queued[0] if queued else self.route_to_frontier(screen)
        if action is None:
            return "exhausted"
        self.announce(screen, action, queued[1:] if queued else None)

        transition, found_something, _ = self.take(screen, variant, before_fp, action)

        # A navigation key that changed something is walking a list, and one press
        # only ever reveals one entry of it - so it goes back in the pool and keeps
        # being pressed.
        #
        # The stopping rule cannot be "stop as soon as the result is familiar":
        # walking a list of menu rows alternates between new appearances and ones
        # already seen, and the very first press back down the list lands somewhere
        # known. That reads as exhausted while most of the menu is still unvisited.
        # So it stops on a *run* of presses that reveal nothing new, which is what
        # actually happens at the end of a list or when a key does nothing here.
        if action.kind == "key" and action.key in NAV_KEYS:
            counts = self.repeats[screen.id]
            # Counted whatever the press achieved, including nothing. The per-key rules
            # below only see presses that changed something, which is correct for
            # deciding whether a key walks a list - and is exactly why they cannot bound
            # the total: a press that does nothing visible is the cheapest one to repeat
            # forever.
            counts["!nav"] = counts.get("!nav", 0) + 1
            if counts["!nav"] == NAV_BUDGET:
                self.controller.note(
                    f"{screen.id} has absorbed {NAV_BUDGET} navigation presses; no more "
                    f"will be spent reaching its other appearances")

            if transition.kind != "none":
                counts[action.id] = counts.get(action.id, 0) + 1
                stale_key = f"{action.id}!stale"
                counts[stale_key] = 0 if found_something else counts.get(stale_key, 0) + 1
                if counts[action.id] < NAV_REPEAT and counts[stale_key] < NAV_STALE:
                    screen.tried.discard(action.id)
                elif counts[action.id] >= NAV_REPEAT:
                    log(f"    {action.key} on {screen.id} capped at {NAV_REPEAT} presses "
                        f"while still finding new appearances; moving on")
        return "ok"

    def announce(self, screen: Screen, action: Action,
                 after: list[Action] | None) -> None:
        """Say what is about to be sent, and what is queued behind it.

        Printed *before* the input goes out. A line that appears only once the click has
        landed is a receipt, and the reason somebody watches a pass against a live account
        is to see what it is about to do while there is still time to stop it. It is also
        the only order under which an action that hangs or kills the window prints at all -
        which is the case a reader most needs named.

        `after` is the rest of this screen's queue, or None when the action came from
        `route_to_frontier` and so is travel rather than a test of this screen."""
        label = self.aimed_at(screen, action)
        if after is None:
            following = "on the way to a screen with untried actions"
        elif after:
            following = f"next {after[0].describe()}"
        else:
            following = "last one queued here"
        log(f"  [{self.actions_taken + 1}] {screen.id}: {action.describe()}"
            + (f" - {label}" if label else "")
            + f"   ({following})")

    def wants_vetting(self, screen: Screen, variant: Variant) -> bool:
        """Whether this appearance is worth a vetting call.

        Each screen gets a budget, which is what stops one whose look changes
        constantly from spending the session on calls about the same three buttons.
        The exception is an appearance *far* from the screen's first sighting: it is
        only filed here because the volatile mask let it in, which makes it the
        likeliest place for two screens to have been merged into one - and once the
        budget is spent nothing else in the session will ever notice. Those get a small
        allowance of their own, since vetting is now load-bearing for identity and not
        only for safety."""
        if self.vetter is None or variant.vetting is not None or not variant.stored:
            return False
        if screen.vetting is None or screen.vet_budget > 0:
            return True
        raw = 1.0 - len(diff_cells(variant.fp, screen.representative,
                                   self.cell_delta)) / NCELLS
        if raw < self.screen_match and screen.arbitrations < ARBITRATION_CALLS:
            screen.arbitrations += 1
            log(f"  {variant.id} shares only {raw:.3f} of its cells with "
                f"{screen.id}'s first sighting; spending an arbitration call on it "
                f"past the vetting budget")
            return True
        return False

    def vet(self, screen: Screen, variant: Variant) -> Screen:
        """Ask the model what this appearance is and what may be pressed on it.

        One call covers both scopes because it is one image and one question. The
        first appearance of a screen also carries the click candidates and the
        screen's name; later appearances differ only in what is selected, so they are
        asked about the keys alone.

        Returns the screen this appearance belongs to afterwards, which is not always
        the one it was passed - see `split_screen`."""
        first = screen.vetting is None
        candidates = self.variant_actions()
        if first:
            candidates += [a for a in self.screen_actions(screen) if a.committing]
        try:
            verdict = self.vetter(self.out / variant.image, screen, variant, candidates,
                                  self.candidate_crops(screen, variant, candidates))
        except Exception as error:                      # noqa: BLE001
            # A failed vetting call must not unlock anything. Left as None, which
            # `permitted` reads as "committing actions stay locked" - the session
            # degrades to navigation-only here instead of guessing.
            self.controller.note(f"vetting {variant.id} failed ({error}); "
                                 f"committing actions stay locked there")
            return screen

        screen.vet_budget -= 1
        variant.vetting = verdict
        variant.highlighted = verdict.get("highlighted", "")
        if first:
            screen.vetting = verdict
            screen.vet_budget = VET_VARIANTS - 1
        safe = sum(1 for v in verdict.get("actions", {}).values() if v.get("safe"))
        name = verdict.get("name", "")
        log(f"  vetted {variant.id}: {name or '?'!r}"
            + (f", selected {variant.highlighted!r}" if variant.highlighted else "")
            + f", {safe} of {len(candidates)} actions cleared "
            f"({max(screen.vet_budget, 0)} vetting calls left for {screen.id})")

        if first or not name or not variant.stored or len(screen.variants) < 2:
            return screen
        if names_agree(name, (screen.vetting or {}).get("name", "")):
            return screen
        # Measured on raw cells, deliberately NOT on stable-area agreement. The mask
        # is what let this appearance in: by the time it arrived, earlier variants had
        # already marked as volatile most of the cells it differs in, so its masked
        # score reads 1.000 while 42 cells of the frame are plainly different. Using
        # that number as the "too alike to be another place" guard means asking the
        # broken measure to referee its own mistake.
        raw = 1.0 - len(diff_cells(variant.fp, screen.representative,
                                   self.cell_delta)) / NCELLS
        if raw >= SPLIT_CEILING:
            self.controller.note(
                f"{variant.id} was named {name!r} on a screen called "
                f"{(screen.vetting or {}).get('name')!r}, but {raw:.3f} of its cells "
                f"match {screen.id}'s first sighting exactly - too alike to be a "
                f"different place, so it stays filed there")
            return screen
        return self.split_screen(screen, variant, name, raw)

    def split_screen(self, screen: Screen, variant: Variant, name: str,
                     score: float) -> Screen:
        """Promote one appearance to a screen of its own and re-file its transitions.

        Geometry decides screen identity with a threshold, and a threshold has to be
        wrong somewhere: opening a menu over a menu can move fewer cells than a busy
        screen moves on its own, so no single number separates "a new place" from "the
        same place, changed". Recalibrating only moves where it is wrong.

        What actually caught the error was a disagreement - the model named an
        appearance 'Settings menu' while geometry had filed it under the main menu -
        so naming arbitrates identity where a threshold cannot. Only in the splitting
        direction: two names differing is evidence of two places, while two names
        matching is no evidence at all that two screens are one, since 'inventory' is
        a fine name for eight different inventories.

        The variant keeps its id. It names an image already on disk and transitions
        already recorded, and renaming it for tidiness would break both.

        `score` is the fraction of raw cells this appearance shares with the screen's
        first sighting - reported rather than used, since the decision was the name's."""
        self.splits += 1
        # The cells that tell the two apart. Protected on both sides, because the mask
        # that merged them is built from exactly these and would otherwise dissolve the
        # distinction again within a few frames.
        distinct = diff_cells(screen.representative, variant.fp, self.cell_delta)
        fresh = Screen(id=f"sc{len(self.screens) + 1:02d}", representative=variant.fp,
                       first_seen=variant.first_seen, observations=variant.observations,
                       split_from=screen.id, split_name=name, protected=set(distinct))
        self.screens[fresh.id] = fresh
        screen.variants.pop(variant.key, None)
        fresh.variants[variant.key] = variant
        screen.observations = max(1, screen.observations - variant.observations)
        screen.protected |= distinct

        # Every cell the mis-filed appearance differed in was recorded as dynamic
        # content of the old screen. Rebuilt from the appearances that remain, which
        # is the evidence still attributed to it. Only stored variants contribute, so
        # this can under-count on a screen that overflowed `MAX_VARIANTS` - it will be
        # relearned on the next revisit, which is how it was learned in the first place.
        screen.volatile = set().union(set(), *(
            diff_cells(screen.representative, other.fp, self.cell_delta)
            for other in screen.variants.values())) - screen.protected
        screen.degenerate = NCELLS - len(screen.volatile) < MIN_STABLE_CELLS

        moved = self._refile(screen.id, fresh.id, variant.id)
        log(f"  ! {variant.id} is {name!r}, not "
            f"{(screen.vetting or {}).get('name')!r} - splitting it out as {fresh.id} "
            f"({score:.3f} of its cells match {screen.id}'s first sighting, and the "
            f"volatile mask covered the rest); {moved} transition(s) re-filed")
        # Deliberately left unvetted. The name is on record as `split_name`, but the
        # click verdicts and hotspots belong to the screen it was merged into, so this
        # one gets its own hover sweep and its own first-appearance call.
        return fresh

    def _refile(self, old: str, new: str, variant_id: str) -> int:
        """Re-point the transitions that left from or arrived at one appearance.

        A transition that used to stay inside one screen becomes a screen change once
        its two ends live in different screens - which is the whole finding, and why
        this cannot just rewrite the ids and leave the classification alone."""
        rebuilt: dict[str, Transition] = {}
        moved = 0
        for transition in self.transitions.values():
            before = (transition.source, transition.dest)
            if transition.source == old and transition.from_variant == variant_id:
                transition.source = new
            if transition.dest == old and transition.to_variant == variant_id:
                transition.dest = new
            if (transition.source, transition.dest) != before:
                moved += 1
            if transition.source != transition.dest:
                transition.kind = "screen"
            key = (f"{transition.source}|{transition.action.id}|"
                   f"{transition.kind}|{transition.dest}")
            existing = rebuilt.get(key)
            if existing:
                # Two edges that were only distinct because one of their ends was
                # classified twice. Counts are summed rather than one being dropped.
                existing.count += transition.count
                continue
            rebuilt[key] = transition
        self.transitions = rebuilt
        return moved

    # -- the loop -----------------------------------------------------------

    def run(self, minutes: float) -> None:
        deadline = time.monotonic() + minutes * 60
        log(f"\nrecon for {minutes:.1f} minutes; "
            f"{'model vetting on' if self.vetter else 'no model, navigation only'}")
        while time.monotonic() < deadline:
            try:
                result = self.step()
            except PermissionError as error:
                self.controller.note(f"denylist stopped an action: {error}")
                continue
            except WindowLost as error:
                # The user's rule for an unattended session: if the window breaks,
                # restart the loop. What was learned stays - it is still true, and a
                # session that discarded it on every crash would never get past the
                # first screen.
                self.controller.note(f"lost the window ({error}); restarting")
                self.controller.start()
                continue
            if result == "exhausted":
                if not self.recover_frontier():
                    log("  nothing left to try and no way back to anything new; stopping")
                    self.stopped = "nothing left to try"
                    return
            if self.actions_taken and self.actions_taken % SAVE_EVERY == 0:
                self.save()
        self.stopped = "time up"
        log(f"\ntime is up after {self.actions_taken} actions")

    def recover_frontier(self) -> bool:
        """Everything reachable has been tried. A relaunch is the one move that
        reliably returns an unknown game to a known starting point, so spend it -
        and if the frontier is still empty afterwards, the session is genuinely done
        rather than merely stuck."""
        unexplored = [s for s in self.screens.values() if self.screen_has_frontier(s)]
        if not unexplored:
            return False
        if self.actions_taken == self.actions_at_recovery:
            # The last relaunch bought nothing: we came back to the same screen, found
            # it exhausted again, and asked for another. The untried screens exist but
            # nothing knows a route to them, and relaunching in a loop would spend the
            # rest of the session proving that repeatedly.
            self.controller.note(
                f"relaunching did not reach the frontier - "
                f"{', '.join(s.id for s in unexplored)} still have untried actions but "
                f"no observed route leads back to them")
            return False
        self.actions_at_recovery = self.actions_taken
        self.controller.note("frontier unreachable from here; relaunching to get back to the start")
        self.controller.close()
        self.controller.start()
        return True

    # -- resuming -----------------------------------------------------------

    def resume(self, data: dict, source: Path) -> str:
        """Reload a previous pass's map so this one extends it instead of redoing it.

        The point of short passes is that each one starts from a cold launch, which is
        the only move that reliably returns an unknown game to a known state - and the
        cost of a cold start is that everything learned is on the floor. This is what
        makes that cost optional. A resumed pass rejoins the game already knowing which
        keys it has answered on which appearance, which controls the model cleared, and
        which cells tell two screens apart, so its three minutes go into territory the
        earlier passes did not reach.

        Nothing here is inferred. Every field is one a pass wrote down, and the maps
        round-trip exactly, because a resumed screen with a rebuilt-from-scratch mask is
        a different screen wearing the same id: the protected cells in particular are
        the whole reason a split stays split, and a pass that guessed at them would
        re-merge the screens its predecessor separated and then re-pay for the split.

        Images are copied rather than referenced. A pass directory that cannot render
        its own report is not an artifact, and the alternative - paths reaching back
        into a sibling directory - breaks the moment one is moved or pruned."""
        if data.get("schema") != SCHEMA:
            raise SystemExit(f"cannot resume from schema {data.get('schema')!r}, "
                             f"this is {SCHEMA}")
        for image in (source / "images").glob("*.png"):
            copyfile(image, self.images / image.name)

        for entry in data["screens"]:
            explored = entry.get("explored", {})
            screen = Screen(
                id=entry["id"],
                representative=base64.b64decode(entry["fingerprint_b64"]),
                first_seen=entry.get("first_seen_action", 0),
                observations=entry.get("observations", 1),
                volatile=cell_set(entry.get("volatile_map", [])),
                protected=cell_set(entry.get("protected_map", [])),
                animated=cell_set(entry.get("animated_map", [])),
                unstored_variants=entry.get("variants_not_stored", 0),
                tried=set(explored.get("tried", [])),
                variant_seq=max(explored.get("next_variant_number", 1) - 1, 0),
                arbitrations=explored.get("arbitrations_spent", 0),
                hotspots=[tuple(p) for p in entry.get("hover", {}).get("reacting_points", [])],
                hover_reactions=entry.get("hover", {}).get("reaction_cells", []),
                crop_boxes=entry.get("hover", {}).get("crop_boxes", {}),
                sticky=entry.get("hover", {}).get("sticky_points", []),
                animation=entry.get("animation", []),
                hover_probed=entry.get("hover", {}).get("swept", False),
                hover_inert=entry.get("hover", {}).get("inert", False),
                hover_probe_count=entry.get("hover", {}).get("probed", 0),
                degenerate=entry.get("identity_is_weak", False),
                vet_budget=explored.get("vetting_calls_left", 0),
                split_from=entry.get("split_from") or "",
                split_name=entry.get("split_name") or "",
                scrolls=explored.get("wheel_does_something", False),
                drags=explored.get("drag_does_something", False),
            )
            if explored.get("vetted"):
                screen.vetting = {"name": entry.get("name") or "",
                                  "purpose": entry.get("purpose") or "",
                                  "elements": entry.get("elements", []),
                                  # `click_verdicts` is the name this block had before
                                  # drag and scroll existed. Read as well as the current
                                  # one, and not instead: a map written by an earlier pass
                                  # holds real verdicts that were paid for with real
                                  # calls, and dropping them on a rename would make every
                                  # resumed session re-buy them.
                                  "actions": (entry.get("mouse_verdicts")
                                              or entry.get("click_verdicts", {}))}
            # A screen that has no vetting budget left and no vetter this pass is not
            # the same as one nobody has looked at, and `wants_vetting` reads the two
            # off different fields, so both are restored rather than recomputed.
            for record in entry.get("variants", []):
                fp = base64.b64decode(record["fingerprint_b64"])
                variant = Variant(
                    id=record["id"], key=variant_key(fp), fp=fp,
                    observations=record.get("observations", 1),
                    image=record.get("image", ""),
                    differs_image=record.get("differs_image", ""),
                    first_seen=record.get("first_seen_action", 0),
                    tried=set(record.get("tried", [])),
                    highlighted=record.get("selected") or "",
                    animated=cell_set(record.get("animated_map", [])),
                )
                if record.get("vetted"):
                    variant.vetting = {"actions": record.get("key_verdicts", {}),
                                       "highlighted": variant.highlighted,
                                       "name": entry.get("name") or ""}
                screen.variants[variant.key] = variant
            self.screens[screen.id] = screen
            self.repeats[screen.id]["!nav"] = explored.get("navigation_presses", 0)

        for record in data["transitions"]:
            at = record["action"].get("at")
            to = record["action"].get("to")
            action = Action(kind=record["action"]["kind"],
                            key=record["action"].get("key", ""),
                            at=tuple(at) if at else None,
                            to=tuple(to) if to else None,
                            button=record["action"].get("button", "left"),
                            notches=record["action"].get("notches", 0),
                            horizontal=record["action"].get("horizontal", False),
                            modifiers=tuple(record["action"].get("modifiers", ())))
            transition = Transition(
                id=record["id"], source=record["from"], dest=record["to"],
                action=action, kind=record["effect"],
                from_variant=record.get("from_variant", ""),
                to_variant=record.get("to_variant", ""),
                changed=record.get("changed_cells", 0),
                settle_ms=record.get("settle_ms", 0),
                count=record.get("times_taken", 1),
                first_seen=record.get("first_seen_action", 0),
                crops=record.get("crops", {}),
                crop_box=record.get("crop_box", []))
            # What this action was measured to move, restored as the aim for this pass's
            # close-ups. This is the only way the before frame of a keypress is ever taken
            # on the *first* press of a session: the box is a fact the previous pass paid
            # for, and rediscovering it costs the same press again.
            if transition.crop_box:
                self.boxes.setdefault(shot_name(transition.source, action),
                                      transition.crop_box)
            # Merged rather than replaced: one action on one screen can have two recorded
            # outcomes, and the pictures of it are shared between them.
            stem = shot_name(transition.source, action)
            self.shots.setdefault(stem, {}).update(transition.crops)
            if {"before", "after"} <= set(transition.crops):
                # Already a complete pair. Re-filming it would work and would cost two
                # captures per inherited action per pass, for pictures of the same thing.
                self.filmed.add(stem)
            # Rebuilt to the same key `_record` would compute, so a transition taken
            # again this pass increments the count it already had rather than being
            # filed as a second edge between the same two screens.
            self.transitions[f"{transition.source}|{action.id}|"
                             f"{transition.kind}|{transition.dest}"] = transition

        self.blocked = {entry["what"]: entry["why"]
                        for entry in data.get("blocked_actions", [])
                        # A refusal that only described the previous session is not
                        # carried: it would present "we ran out of vetting budget" as a
                        # property of the control forever.
                        if entry["why"] != UNVETTED}
        self.resumed_from = source.name
        return (f"resumed {len(self.screens)} screens, "
                f"{sum(len(s.variants) for s in self.screens.values())} appearances and "
                f"{len(self.transitions)} transitions from {source.name}")

    # -- output -------------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA,
            "target": {
                "name": self.controller.target.name,
                "window_title": self.controller.target.window_title,
                # The last rect that read as a real window, not a live one: by the
                # time this is written the game may have been closed, and a fresh read
                # would report the 0x0 of a window on its way out.
                "client": [self.controller.last_good_rect[2],
                           self.controller.last_good_rect[3]],
            },
            "session": {
                "seconds": round(time.monotonic() - self.started, 1),
                "actions": self.actions_taken,
                # Which pass this one stood on. Without it, a map with forty screens in
                # it looks like the work of three minutes.
                "resumed_from": self.resumed_from or None,
                "stopped": self.stopped or "cut short",
                "restarts": self.controller.restarts,
                "vetted_by_model": self.vetter is not None,
                "clicks_enabled": self.allow_clicks,
                "grid": [GRID_COLS, GRID_ROWS],
                "screen_match_threshold": self.screen_match,
                "cell_delta": self.cell_delta,
                # How often the model's naming overruled that threshold. A number
                # climbing here says the threshold is cut too loose for this game.
                "screens_split_by_name": self.splits,
                "median_match_score": round(
                    sorted(self.match_scores)[len(self.match_scores) // 2], 4)
                if self.match_scores else None,
                "notes": self.controller.notes,
            },
            "screens": [
                {
                    "id": screen.id,
                    "name": (screen.vetting or {}).get("name") or screen.split_name or None,
                    "split_from": screen.split_from or None,
                    "purpose": (screen.vetting or {}).get("purpose"),
                    "observations": screen.observations,
                    "first_seen_action": screen.first_seen,
                    "image": screen.image(),
                    "stable_cells": NCELLS - len(screen.volatile),
                    "protected_cells": len(screen.protected),
                    "identity_is_weak": screen.degenerate,
                    "volatile_map": volatile_map(screen.volatile),
                    # The masks as maps rather than counts, because a later pass has to
                    # restore them exactly: the protected set is what stops a resumed
                    # screen from re-absorbing the neighbour a split separated it from,
                    # and rediscovering it costs the same split all over again.
                    "protected_map": volatile_map(screen.protected),
                    # Two different statements about movement, both worth keeping. The
                    # volatile map is everything that ever differed between visits, so it
                    # includes content an input moved; this is only what moved with
                    # nothing in flight, which is the part no action can be credited for.
                    "animated_cells": len(screen.animated),
                    "animated_map": volatile_map(screen.animated),
                    # Frames of that movement, cropped to it. A reader - or a model - can
                    # tell a spinner from a countdown from these and from nothing else in
                    # the map, and the difference is whether the screen is waiting or busy.
                    "animation": screen.animation,
                    "hover": {
                        "probed": screen.hover_probe_count,
                        "inert": screen.hover_inert,
                        "reacting_points": [list(p) for p in screen.hotspots],
                        "reaction_cells": screen.hover_reactions,
                        # Each reacting control's own extent, so a later pass aims its
                        # close-ups at what was measured here instead of at a default box
                        # around the point.
                        "crop_boxes": screen.crop_boxes,
                        # Points where the cursor moves the selection instead of lighting
                        # a control, measured rather than assumed: their hovered and
                        # resting close-ups came out pixel-identical.
                        "sticky_points": screen.sticky,
                        # Distinct from `probed > 0`: a screen whose every probe point
                        # is denylisted is swept without a single probe being taken,
                        # and a later pass must not read that as unswept and pay for
                        # the sweep again.
                        "swept": screen.hover_probed,
                    },
                    # What the exploration of this screen has already spent and what it
                    # was told. Carried so a later pass continues the session instead of
                    # restarting it: without the tried sets it re-presses every key it
                    # has already answered, and without the verdicts it re-buys every
                    # vetting call it has already paid for.
                    "explored": {
                        "vetted": screen.vetting is not None,
                        "tried": sorted(screen.tried),
                        "navigation_presses": self.repeats[screen.id].get("!nav", 0),
                        "vetting_calls_left": max(screen.vet_budget, 0),
                        "arbitrations_spent": screen.arbitrations,
                        "next_variant_number": screen.variant_seq + 1,
                        # What the blind probes found, so a later pass does not re-derive
                        # it by spending them again - and so the escalated candidates are
                        # on the table from its first step on this screen.
                        "wheel_does_something": screen.scrolls,
                        "drag_does_something": screen.drags,
                    },
                    # Every verdict that was bought for a *position* rather than for
                    # whatever is selected: clicks, drags and wheels alike. Named for the
                    # modality group rather than for `click:` because that is what the
                    # scope actually is - `permitted` looks all three up on the screen.
                    "mouse_verdicts": {
                        action_id: verdict
                        for action_id, verdict in (screen.vetting or {}).get("actions", {}).items()
                        if not action_id.startswith("key:")
                    },
                    "variants": [
                        {"id": v.id, "image": v.image, "observations": v.observations,
                         # The close-up the vetting call was given to read the selection
                         # off, when there was one. Recorded so the answer in `selected`
                         # can be checked against the picture it came from.
                         "differs_image": v.differs_image,
                         "first_seen_action": v.first_seen,
                         "tried": sorted(v.tried),
                         # Stated rather than inferred from an empty verdict list: "the
                         # model has ruled on this appearance and cleared nothing" and
                         # "nobody has asked" permit the same actions today and must not
                         # cost the same call tomorrow.
                         "vetted": v.vetting is not None,
                         # Only what this appearance moves beyond what the whole screen
                         # does, which is usually the highlight on the selected row.
                         "animated_map": volatile_map(v.animated),
                         # What the model read as selected in this appearance. The
                         # label a keypress would have acted on, which is the only
                         # thing that makes a per-variant key verdict meaningful
                         # later - and the tie between an image and a menu entry.
                         "selected": v.highlighted or None,
                         # Every appearance's fingerprint, not just the screen's. What
                         # a session's identity rules got wrong can then be re-argued
                         # against the frames themselves - which is how the numbers on
                         # `Target` were cut, and it should not cost another 8 minutes
                         # of the game to do it again.
                         "fingerprint_b64": base64.b64encode(v.fp).decode(),
                         "key_verdicts": {
                             action_id: verdict
                             for action_id, verdict in (v.vetting or {}).get("actions", {}).items()
                             if action_id.startswith("key:")
                         }}
                        for v in screen.variants.values()
                    ],
                    "variants_not_stored": screen.unstored_variants,
                    "elements": (screen.vetting or {}).get("elements", []),
                    # Kept so a later session can extend this map instead of
                    # rediscovering it, and so a threshold argument can be settled
                    # against recorded frames rather than re-run against the game.
                    "fingerprint_b64": base64.b64encode(screen.representative).decode(),
                }
                for screen in self.screens.values()
            ],
            "transitions": [
                {
                    "id": t.id, "from": t.source, "to": t.dest, "effect": t.kind,
                    # Written out in full rather than reconstructed from `id`, because the
                    # id is a name and parsing a name back into an action is how the two
                    # drift apart. Only the fields that are not at their default appear,
                    # so a keypress and a plain click serialise exactly as they did before
                    # drag and scroll existed - and a map written by this code stays
                    # readable to the pass that wrote the one before it.
                    "action": {"kind": t.action.kind, "key": t.action.key,
                               "at": list(t.action.at) if t.action.at else None,
                               "id": t.action.id,
                               **({"to": list(t.action.to)} if t.action.to else {}),
                               **({"button": t.action.button}
                                  if t.action.button != "left" else {}),
                               **({"notches": t.action.notches} if t.action.notches else {}),
                               **({"horizontal": True} if t.action.horizontal else {}),
                               **({"modifiers": list(t.action.modifiers)}
                                  if t.action.modifiers else {})},
                    "from_variant": t.from_variant, "to_variant": t.to_variant,
                    "before_image": self._variant_image(t.source, t.from_variant),
                    "after_image": self._variant_image(t.dest, t.to_variant),
                    # The two above are the whole window either side of this edge. These
                    # are the same event at native resolution, cropped to the part that
                    # took part in it - which for most edges in a map is 4 cells of 576.
                    "crops": t.crops,
                    "crop_box": t.crop_box,
                    "changed_cells": t.changed, "settle_ms": t.settle_ms,
                    "times_taken": t.count, "first_seen_action": t.first_seen,
                }
                for t in self.transitions.values()
            ],
            "blocked_actions": [{"what": k, "why": v} for k, v in self.blocked.items()],
        }

    def _variant_image(self, screen_id: str, variant_id: str) -> str:
        screen = self.screens.get(screen_id)
        if not screen:
            return ""
        return next((v.image for v in screen.variants.values() if v.id == variant_id), "")

    def save(self) -> Path:
        path = self.out / "ontology.json"
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        return path


# --- report -----------------------------------------------------------------

EFFECT_WORDS = {
    "none": "nothing visible changed",
    "variant": "same screen, different appearance",
    "screen": "went to another screen",
}


def _element_place(element: dict) -> str:
    """Where an element is, for the report line that names it.

    The picture inline, because a rectangle is the one claim in this file a reader can check
    in a glance, and only if the crop is next to the numbers. `located` is quoted rather
    than translated: "described" next to a box is the report saying *this one was not
    measured*, and softening that is how a guess starts reading as a measurement."""
    box = as_box(element.get("box"))
    if box is None:
        at = element.get("at")
        return f" - around ({at[0]:.3f}, {at[1]:.3f})" if is_fraction(at) else " - unplaced"
    x, y = box_centre(box)
    where = (f" - **({x:.3f}, {y:.3f})**, in `[{box[0]:.3f}, {box[1]:.3f}, "
             f"{box[2]:.3f}, {box[3]:.3f}]` ({element.get('located', 'described')})")
    if element.get("placed_why"):
        where += f", because {element['placed_why']}"
    described = element.get("described_at")
    if described:
        where += (f", though the call that named it put it at "
                  f"({described[0]:.3f}, {described[1]:.3f}), outside that box")
    if element.get("image"):
        where += f" ![{element.get('label', '?')}]({element['image']})"
    return where


def _same_name_warnings(screens: list[dict]) -> list[str]:
    """Pairs of screens the model gave the same name to - a free finding, derived.

    The session already spends model calls on the opposite question: `vet` splits a screen
    off when a new appearance is named something the incumbent's name disagrees with. It
    never asks whether two *separate* screens ended up with the same name, and that is the
    more likely error of the two, because it needs no disagreement to happen - just two
    calls, minutes apart, describing similar screens from one image each.

    Nothing is merged on the strength of it. Two screens can honestly share a name (a game
    with two social tabs), and a name is a description while the geometry is a measurement,
    so the measurement wins. What this does is put the pair in front of a reader, which is
    the whole job of the report. Measured on Clash Royale: sc04 and sc06 were both called a
    "Social screen" and sc02 and sc07 both named a deck - four of eight screens, in a pass
    where nothing in the output said so."""
    named = [(s["id"], s.get("name") or "") for s in screens]
    pairs = [(a, an, b, bn) for i, (a, an) in enumerate(named)
             for (b, bn) in named[i + 1:] if an and bn and names_agree(an, bn)]
    if not pairs:
        return []
    lines = ["## Screens the model named the same thing\n",
             "Kept separate - geometry is a measurement and a name is a description - but "
             "worth a look: either two of these are one place the pixel test failed to "
             "merge, or the names need to be more specific before they reach a wiki.\n"]
    lines += [f"- **{a}** {an!r} and **{b}** {bn!r}" for a, an, b, bn in pairs]
    return lines + [""]


def write_report(data: dict, out: Path) -> Path:
    """A Markdown view of the same JSON, with the images inline.

    Separate from the JSON rather than instead of it: the JSON is what a later stage
    consumes, and this is what a person reads to find out whether the JSON is worth
    consuming. Everything here is derived - if the two ever disagree, the JSON is
    right."""
    session, lines = data["session"], []
    lines.append(f"# {data['target']['name']} - recon\n")
    lines.append(f"{session['actions']} actions in {session['seconds'] / 60:.1f} minutes "
                 f"({session['actions'] / max(session['seconds'], 1) * 60:.0f} per minute) "
                 f"at {data['target']['client'][0]}x{data['target']['client'][1]}. "
                 f"{len(data['screens'])} screens, {len(data['transitions'])} distinct "
                 f"transitions, {session['restarts']} restarts.\n")
    lines.append(f"Screen identity: {session['grid'][0]}x{session['grid'][1]} grid, "
                 f"match threshold {session['screen_match_threshold']}, "
                 f"median observed match {session['median_match_score']}"
                 + (f", {session['screens_split_by_name']} screen(s) split off after the "
                    f"model named them something else"
                    if session.get("screens_split_by_name") else "") + ". "
                 f"Committing actions were "
                 f"{'vetted by the model' if session['vetted_by_model'] else 'LOCKED (no model)'}.\n")
    if session["notes"]:
        lines.append("## What went wrong\n")
        lines += [f"- {note}" for note in session["notes"]] + [""]
    lines += _same_name_warnings(data["screens"])

    outgoing: dict[str, list[dict]] = {}
    for transition in data["transitions"]:
        outgoing.setdefault(transition["from"], []).append(transition)

    lines.append("## Screens\n")
    for screen in data["screens"]:
        title = screen["name"] or "(unnamed - no model pass)"
        lines.append(f"### {screen['id']} - {title}\n")
        if screen.get("split_from"):
            lines.append(f"Separated from {screen['split_from']}, which the pixel test had "
                         f"merged it into: the model named this appearance differently.\n")
        if screen["purpose"]:
            lines.append(f"{screen['purpose']}\n")
        lines.append(f"Seen {screen['observations']} times, first at action "
                     f"{screen['first_seen_action']}. "
                     f"{screen['stable_cells']} of {GRID_COLS * GRID_ROWS} cells held still"
                     + (" - **identity is weak**" if screen["identity_is_weak"] else "") + ".\n")
        if screen.get("animated_cells"):
            lines.append(f"{screen['animated_cells']} of {GRID_COLS * GRID_ROWS} cells move "
                         f"with no input at all, so two frames differing only there are the "
                         f"same appearance.\n")
        if screen["image"]:
            lines.append(f"![{screen['id']}]({screen['image']})\n")
        if screen.get("animation"):
            lines.append(f"What moves on its own, {len(screen['animation'])} frames "
                         f"{ANIMATION_GAP}s apart, cropped to the cells that move:\n")
            lines.append(" ".join(f"![frame {n + 1}]({shot})"
                                  for n, shot in enumerate(screen["animation"])) + "\n")

        for element in screen["elements"]:
            lines.append(f"- **{element.get('label', '?')}** - {element.get('what', '')}"
                         + _element_place(element))
            for modality, effect in (element.get("behaviour") or {}).items():
                evidence = effect.get("evidence") or []
                mark = f" `[{', '.join(evidence)}]`" if evidence else " *(hypothesis)*"
                lines.append(f"  - `{modality}`: {effect.get('effect', '')}{mark}")
        if screen["elements"]:
            lines.append("")
        for note in screen.get("notes", []):
            lines.append(f"> {note}")
        if screen.get("notes"):
            lines.append("")

        lines.append("Where the content moved (`#` = never held still):\n")
        lines.append("```")
        lines += screen["volatile_map"]
        lines.append("```\n")

        if outgoing.get(screen["id"]):
            lines.append("| action | effect | goes to | cells | settle | times | close-ups |")
            lines.append("|---|---|---|---|---|---|---|")
            for t in sorted(outgoing[screen["id"]], key=lambda x: x["action"]["id"]):
                dest = t["to"] if t["effect"] == "screen" else "-"
                # Inline in the table rather than in a gallery below it. A crop is only
                # evidence about the action it was taken for, and 30px pictures next to the
                # row that names the action is the one layout where that stays true.
                shots = " ".join(f"[{slot}]({(t.get('crops') or {})[slot]})"
                                 for slot in CROP_SLOTS if (t.get("crops") or {}).get(slot))
                lines.append(f"| `{t['action']['id']}` | {EFFECT_WORDS[t['effect']]} | {dest} "
                             f"| {t['changed_cells']} | {t['settle_ms']}ms | {t['times_taken']} "
                             f"| {shots or '-'} |")
            lines.append("")
            pairs = [t for t in outgoing[screen["id"]]
                     if (t.get("crops") or {}).get("before") and t["crops"].get("after")]
            if pairs:
                lines.append("Before and after, at full resolution, cropped to what took "
                             "part:\n")
                for t in sorted(pairs, key=lambda x: x["action"]["id"]):
                    lines.append(f"- `{t['action']['id']}`: "
                                 + " ".join(f"![{slot}]({t['crops'][slot]})"
                                            for slot in CROP_SLOTS
                                            if t["crops"].get(slot)))
                lines.append("")

            sticky = screen["hover"].get("sticky_points") or []
            if sticky:
                lines.append(f"{len(sticky)} of "
                             f"{len(screen['hover']['reacting_points'])} reacting points "
                             f"looked the same once the cursor had left them, so they have "
                             f"one close-up and not a pair: the cursor moves this screen's "
                             f"selection rather than lighting a control. "
                             f"`{'`, `'.join(sticky)}`\n")

        if len(screen["variants"]) > 1:
            lines.append(f"{len(screen['variants'])} appearances stored"
                         + (f", {screen['variants_not_stored']} more seen and not stored"
                            if screen["variants_not_stored"] else "") + ":\n")
            for variant in screen["variants"]:
                lines.append(f"![{variant['id']}]({variant['image']}) ")
            lines.append("")
            # The close-up beside the appearance it was taken from, and what the model
            # read off it. Together they are checkable; either alone is not.
            selections = [v for v in screen["variants"] if v.get("differs_image")]
            if selections:
                lines.append("What is different about each of them, at full resolution:\n")
                for variant in selections:
                    lines.append(f"- {variant['id']}"
                                 + (f", selected {variant['selected']!r}"
                                    if variant.get("selected") else "")
                                 + f": ![{variant['id']}]({variant['differs_image']})")
                lines.append("")

    if data["blocked_actions"]:
        lines.append("## What was not tried, and why\n")
        for entry in data["blocked_actions"]:
            lines.append(f"- `{entry['what']}` - {entry['why']}")
        lines.append("")

    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- cli --------------------------------------------------------------------

def main() -> None:
    readable_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", required=True,
                        help="the game's name, as a person would write it")
    # Three rather than ten. A pass is not a budget any more, it is one attempt that
    # keeps what it learned - `sweep.py` runs several and each starts from a cold launch,
    # which is the one move that reliably returns an unknown game to a known state.
    parser.add_argument("--minutes", type=float, default=3.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--resume", default="",
                        help="a previous pass's directory, whose map this pass extends")
    parser.add_argument("--no-model", action="store_true",
                        help="no vetting call, so committing actions stay locked")
    parser.add_argument("--no-clicks", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    import calibrate

    target = targets.resolve(args.game, calibrate.load(args.game))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(__file__).parent / "out" / f"{target.name}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    vetter = None
    if not args.no_model:
        import describe
        vetter = describe.make_vetter()

    set_dpi_aware()
    controller = Controller(target)
    session = Recon(controller, out, vetter=vetter, allow_clicks=not args.no_clicks)
    if args.resume:
        source = Path(args.resume)
        log(session.resume(json.loads((source / "ontology.json").read_text(
            encoding="utf-8")), source))
    try:
        controller.start()
        session.run(args.minutes)
    except KeyboardInterrupt:
        log("\ninterrupted")
    finally:
        data = session.to_json()
        log(f"\nwrote {session.save()}")
        log(f"wrote {write_report(data, out)}")
        log(f"{len(session.screens)} screens, {len(session.transitions)} transitions, "
            f"{sum(len(s.variants) for s in session.screens.values())} images")
        if not args.keep_open:
            log(f"closed via {controller.close()}")


if __name__ == "__main__":
    main()
