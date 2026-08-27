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
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path
from shutil import copyfile

import target as targets
from calibrate import MATCH_FLOOR, SLACK_CELLS
from controller import Controller, WindowLost, log, set_dpi_aware

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

NAV_KEYS = ("up", "down", "left", "right")
COMMIT_KEYS = ("enter", "space", "esc")

# The one refusal that is temporary: it describes this session, not the control.
UNVETTED = "screen not vetted, so committing actions stay locked"

SAVE_EVERY = 20          # actions between JSON flushes; a killed session keeps its findings

# Bumped from /1 when the ontology became something a later pass reads back rather than
# only something a person reads. `resume` refuses anything else: the earlier shape is
# missing the masks and the tried sets, and every one of them absent reads as a
# plausible default - an unswept screen, an unprotected split - so a quiet degrade would
# hand a resumed pass a map that is wrong in exactly the places that are expensive.
SCHEMA = "game-ontology/2"


# --- fingerprints -----------------------------------------------------------

def fingerprint(controller: Controller) -> bytes:
    """Three bytes of BGR mean per grid cell.

    The averaging is GDI's, not ours: `grab_thumbnail` downsamples with HALFTONE, so
    each returned pixel is already the mean of the source region behind it. That is
    the right reduction for identity (it is stable against a pixel of noise) and the
    wrong one for anything extremum-based - a thin bright line survives averaging as
    a barely-changed mean, which is why detail work elsewhere grabs 1:1 instead."""
    raw = controller.grab(GRID_COLS, GRID_ROWS)
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


# --- what an action is ------------------------------------------------------

@dataclass(frozen=True)
class Action:
    kind: str                       # "hover" | "key" | "click"
    key: str = ""
    at: tuple[float, float] | None = None

    @property
    def id(self) -> str:
        if self.kind == "key":
            return f"key:{self.key}"
        return f"{self.kind}:{self.at[0]:.3f},{self.at[1]:.3f}"

    @property
    def committing(self) -> bool:
        """Whether this action can do something that cannot be walked back.

        Cursor moves and arrow keys are excluded on the grounds that a UI which
        destroys data on a hover or an arrow press is broken in a way no explorer
        can defend against anyway. Everything else needs permission."""
        return not (self.kind == "hover" or (self.kind == "key" and self.key in NAV_KEYS))

    def describe(self) -> str:
        if self.kind == "key":
            return f"press {self.key}"
        return f"{self.kind} at ({self.at[0]:.3f}, {self.at[1]:.3f})"


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
    hotspots: list[tuple[float, float]] = field(default_factory=list)
    # Cells each reacting point moved. How loud this screen's hover feedback is, which is
    # what separates a game whose buttons merely underline from one whose buttons repaint
    # a quarter of the window - and the second kind is why `screen_match` cannot be one
    # number for every game.
    hover_reactions: list[int] = field(default_factory=list)
    hover_probed: bool = False
    hover_inert: bool = False
    hover_probe_count: int = 0
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

        started = time.monotonic()
        for fx, fy in order:
            if self.controller.target.forbids(fx, fy):
                continue
            before = fingerprint(self.controller)
            self.controller.hover(fx, fy)
            after, reaction = self._hover_reaction(screen, before)
            screen.hover_probe_count += 1
            if len(reaction) >= 2:
                screen.hotspots.append((fx, fy))
                screen.hover_reactions.append(len(reaction))
                # Before the recording, not after the sweep. `_record` is what files a
                # frame as a screen, so a threshold corrected once the sweep is over has
                # already let the sweep's own first reaction invent a screen - and with
                # passes inheriting each other, that screen is then permanent.
                self.relax_match(screen, after)
                self._record(screen, Action("hover", at=(fx, fy)), before, after, 0)
            if not screen.hotspots and screen.hover_probe_count >= HOVER_PATIENCE:
                screen.hover_inert = True
                break

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

    # -- policy -------------------------------------------------------------

    def permitted(self, screen: Screen, variant: Variant,
                  action: Action) -> tuple[bool, str]:
        """Whether this action may be taken, and if not, why not.

        The verdict for a click is looked up on the screen and the verdict for a key
        on the variant, matching how each one picks its target: by position, or by
        whatever happens to be selected."""
        if not action.committing:
            return True, ""
        if action.kind == "click":
            if not self.allow_clicks:
                return False, "clicks are disabled for this session"
            why = self.controller.target.forbids(*action.at)
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
        """Actions whose meaning does not depend on what is selected."""
        return ([Action("key", key=k) for k in NAV_KEYS]
                + [Action("click", at=point) for point in screen.hotspots])

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
        for action in self.screen_actions(screen):
            if action.id not in screen.tried and self.permitted(screen, variant, action)[0]:
                return action
        for action in self.variant_actions():
            if action.id not in variant.tried and self.permitted(screen, variant, action)[0]:
                return action
        if self.nav_spent(screen) < NAV_BUDGET and any(
                v is not variant and self.variant_has_work(screen, v)
                for v in screen.variants.values()):
            return self.navigator(screen)
        return None

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

    def perform(self, action: Action) -> None:
        if action.kind == "hover":
            self.controller.hover(*action.at)
        elif action.kind == "click":
            self.controller.click(*action.at)
        else:
            self.controller.press(action.key)

    def _record(self, screen: Screen, action: Action, before_fp: bytes,
                after_fp: bytes, settle_ms: int) -> tuple[Transition, bool]:
        before_variant = next((v for v in screen.variants.values()
                               if not diff_cells(before_fp, v.fp, self.cell_delta)), None)
        changed = len(diff_cells(before_fp, after_fp, self.cell_delta))

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

        self.standing = after_screen.id
        key = f"{screen.id}|{action.id}|{kind}|{after_screen.id}"
        existing = self.transitions.get(key)
        if existing:
            existing.count += 1
            return existing, is_new

        transition = Transition(
            id=f"tr{len(self.transitions) + 1:03d}", source=screen.id, dest=after_screen.id,
            action=action, kind=kind,
            from_variant=before_variant.id if before_variant else "",
            to_variant=after_variant.id, changed=changed, settle_ms=settle_ms,
            first_seen=self.actions_taken)
        self.transitions[key] = transition
        if kind != "none":
            log(f"    {action.describe()} -> {kind} "
                f"({screen.id} -> {after_screen.id}, {changed} cells, {settle_ms}ms)")
        return transition, is_new

    def step(self) -> str:
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

        self.prune_blocked(screen, variant)
        action = self.next_action(screen, variant) or self.route_to_frontier(screen)
        if action is None:
            return "exhausted"

        (variant.tried if action.committing and action.kind == "key"
         else screen.tried).add(action.id)
        self.actions_taken += 1
        self.perform(action)
        settle = self.controller.wait_stable()
        after_fp = fingerprint(self.controller)
        transition, found_something = self._record(screen, action, before_fp, after_fp,
                                                   int(settle * 1000))
        # Held in case this action started something that has not appeared yet.
        self.pending = (screen, action, before_fp, int(settle * 1000))

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
            verdict = self.vetter(self.out / variant.image, screen, variant, candidates)
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
                hover_probed=entry.get("hover", {}).get("swept", False),
                hover_inert=entry.get("hover", {}).get("inert", False),
                hover_probe_count=entry.get("hover", {}).get("probed", 0),
                degenerate=entry.get("identity_is_weak", False),
                vet_budget=explored.get("vetting_calls_left", 0),
                split_from=entry.get("split_from") or "",
                split_name=entry.get("split_name") or "",
            )
            if explored.get("vetted"):
                screen.vetting = {"name": entry.get("name") or "",
                                  "purpose": entry.get("purpose") or "",
                                  "elements": entry.get("elements", []),
                                  "actions": entry.get("click_verdicts", {})}
            # A screen that has no vetting budget left and no vetter this pass is not
            # the same as one nobody has looked at, and `wants_vetting` reads the two
            # off different fields, so both are restored rather than recomputed.
            for record in entry.get("variants", []):
                fp = base64.b64decode(record["fingerprint_b64"])
                variant = Variant(
                    id=record["id"], key=variant_key(fp), fp=fp,
                    observations=record.get("observations", 1),
                    image=record.get("image", ""),
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
            action = Action(kind=record["action"]["kind"],
                            key=record["action"].get("key", ""),
                            at=tuple(at) if at else None)
            transition = Transition(
                id=record["id"], source=record["from"], dest=record["to"],
                action=action, kind=record["effect"],
                from_variant=record.get("from_variant", ""),
                to_variant=record.get("to_variant", ""),
                changed=record.get("changed_cells", 0),
                settle_ms=record.get("settle_ms", 0),
                count=record.get("times_taken", 1),
                first_seen=record.get("first_seen_action", 0))
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
                    "hover": {
                        "probed": screen.hover_probe_count,
                        "inert": screen.hover_inert,
                        "reacting_points": [list(p) for p in screen.hotspots],
                        "reaction_cells": screen.hover_reactions,
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
                    },
                    "click_verdicts": {
                        action_id: verdict
                        for action_id, verdict in (screen.vetting or {}).get("actions", {}).items()
                        if action_id.startswith("click:")
                    },
                    "variants": [
                        {"id": v.id, "image": v.image, "observations": v.observations,
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
                    "action": {"kind": t.action.kind, "key": t.action.key,
                               "at": list(t.action.at) if t.action.at else None,
                               "id": t.action.id},
                    "from_variant": t.from_variant, "to_variant": t.to_variant,
                    "before_image": self._variant_image(t.source, t.from_variant),
                    "after_image": self._variant_image(t.dest, t.to_variant),
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

        for element in screen["elements"]:
            lines.append(f"- **{element.get('label', '?')}** - {element.get('what', '')}")
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
            lines.append("| action | effect | goes to | cells | settle | times |")
            lines.append("|---|---|---|---|---|---|")
            for t in sorted(outgoing[screen["id"]], key=lambda x: x["action"]["id"]):
                dest = t["to"] if t["effect"] == "screen" else "-"
                lines.append(f"| `{t['action']['id']}` | {EFFECT_WORDS[t['effect']]} | {dest} "
                             f"| {t['changed_cells']} | {t['settle_ms']}ms | {t['times_taken']} |")
            lines.append("")

        if len(screen["variants"]) > 1:
            lines.append(f"{len(screen['variants'])} appearances stored"
                         + (f", {screen['variants_not_stored']} more seen and not stored"
                            if screen["variants_not_stored"] else "") + ":\n")
            for variant in screen["variants"]:
                lines.append(f"![{variant['id']}]({variant['image']}) ")
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
