"""Play Training Camp matches back to back, measuring how well each one went.

The third entry point in this directory, and the narrowest. `run_recon.py` explores a game
it knows nothing about; `drive.py` runs a directed errand one hand-read tap at a time.
Neither can play a battle. Exploration would spend a vetting call per frame on a screen
that changes every frame, and a hand-driven tap takes longer to decide than the elixir
takes to refill.

So this file is the opposite of both: no model, no policy worth the name, and an action
space of exactly two gestures. It is not a Clash Royale AI. It is the smallest thing that
can put cards on the board fast enough to matter, and its whole claim to safety is that
the two gestures are fixed constants checked before the first one is sent.

**Why Training Camp and nothing else.** A ladder match is a real-time game against a live
person that cannot be backed out of once joined, which is why the Battle button is on the
denylist. Training Camp is the authorised exception, and the reason is on the dialog that
starts it: "You don't get rewards from the Training Camp." No rewards, no trophies, no
opponent waiting on the other end - the one battle whose outcome costs nobody anything.
Hence `--allow-battle`, which has to be passed: the default of this file is to refuse.

**Why three of the four card slots, and which three.** The four cards sit in a row at the
bottom of the arena; the deploy gesture drags one up into the player's own half. Which of
those drags are allowed is not decided here - `Controller.drag` checks the whole path, and
the Battle button's denylist box (x 0.32-0.69, y 0.72-0.84) lies between the card row and
the board. So the answer is a measurement of where the cards are, and getting that
measurement wrong changed the answer twice.

As it stands: slot 1 (centre x 0.310) reaches the left bridge, slots 3 (0.686) and 4
(0.874) reach the right one, and **slot 2 (0.498) reaches neither**. Slot 2 sits squarely
above the box and there is no straight line out of it that misses it - escaping sideways
before y 0.84 needs a path so shallow that continuing it to the river leaves the window
entirely. Slot 3 is the interesting one, and the honest note is that its clearance is four
pixels: its grab point is just right of the box's right edge, and its path to the right
bridge only moves further right. That is a coincidence of where the Battle button sits, not
a designed margin, and it is used anyway for one reason - it fails closed and loudly. If the
card row is measured differently tomorrow, `forbids_path` refuses and `vet_the_gestures`
stops the run before its first gesture. There is no version of being wrong about this that
quietly starts dragging across the box.

None of this is an override, and it was tempting to make one: the box describes a control
on the *main* screen, and during a match those coordinates are grass. It is not one because
it does not have to be. A played card is replaced in the slot it left, so three slots turn
over the whole deck; and the right lane getting two gestures to the left lane's one is not
a cost but the closest this file comes to a tactic, since a push concentrated on one side
beats the same cards split evenly.

**How it knows there is a match at all.** By measurement, and this is the lesson of the
first run rather than a design instinct. That run sent its three taps into a window that
was not in front, opened nothing, and then deployed sixty-one gestures at the main screen -
which cost nothing, changed nothing, and looked exactly like a successful pass in the log.
So one frame is photographed before anything is tapped, and the board must *not* look like
that frame before a single gesture is sent. A change test, not a content test: "is there a
magenta elixir bar here" is a claim about a bar, and one more thing to be wrong about; "is
this still the picture I took a moment ago" needs nothing to be true about the game.

**How it knows the match is over**, which the first two versions did not. They watched for
the *main screen* to come back, and a finished match does not go there - it stops on a
result screen with an OK button, which those runs spent their whole remaining window
dragging at. What actually distinguishes the two is not the crowns, it is that **the card
panel is gone**: the bottom of a board has four cards and an elixir bar, and the bottom of
a result screen has grass.

Which part of the panel to watch is a measurement, and the obvious answer is wrong. The
whole strip drifts 7% away from its own opening frame over thirty seconds of ordinary play,
and the elixir row drifts 25%, because the cards turn over and the bar fills - a run with
the threshold at 50% of the strip declared victory after twenty-two seconds and left the
trainer to win 3-0 against nobody. So what is watched is two slivers at the ends of the
panel, outside the card row and outside the next-card thumbnail, which are the parts the
game never draws in: measured across the same thirty seconds they moved 0%, and on the
result screen they read 100%. Both have to change, confirmed twice half a second apart,
with a foreground check in between - because a window with something in front of it also
reads 100% everywhere, and that is not the match ending.

Then OK is tapped, and whether *that* worked is measured too: the lobby has to come back,
or the run stops and says so rather than tapping again into the dark.

**What "played better" means here**, since it has to mean something measurable. Three
gestures and a timer leave one real quantity to improve: how many cards actually got onto
the board. A drag whose card cannot be paid for does nothing at all - the card stays in
the hand - so the count of gestures sent has never been the count of cards played, and
every run before this one reported the former while implying the latter.

Where to read that is also a measurement, and the obvious answer is wrong again. Watching
the slot the drag started from does not work: a drag that fails to deploy leaves its card
*selected*, drawn larger and lit up, so the slot changes either way and stays changed. A
run measured that way read twenty of its first twenty-one attempts as played, which no
elixir budget in the game allows. What is watched instead is the next-card thumbnail in
the bottom-left corner, which advances only when a card actually leaves the hand and is
never selected and never greyed. The slot reading is still taken and still logged, as the
over-reporting number it is, so that the two can be compared on any future run.

The cadence is flat, because there is nothing to tune. An attempt that cannot be paid for
costs a drag and no elixir, so sending attempts faster than the hand can fill them is free
- the only thing a slower interval would buy is a lower attempt count for the same number
of cards played. The earlier version of this file ran a closed loop that moved the interval
on the landing rate; with the rate as confounded as it was, all that loop did was drive
itself to its own floor, which is where a flat cadence already is.

Run:  python experiments/android-bot/battle.py --allow-battle
      python experiments/android-bot/battle.py --allow-battle --matches 5
      python experiments/android-bot/battle.py --allow-battle --navigate-only
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import (changed_cells, is_foreground, log,  # noqa: E402
                        readable_output, set_dpi_aware)

from attach import attach  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"

# The fingerprint grid the recon session uses, borrowed for one question only: does the
# window still look like the screen it looked like before any of this started?
GRID_COLS, GRID_ROWS = 32, 18
SAME_SCREEN = 0.90   # agreement at or above which the window is showing the screen the
                     # run started on. Loose on purpose: the main screen animates by
                     # itself - running water, waving flags - and a pass measured its
                     # idle self-agreement at 0.971, while a match in progress scores
                     # nothing like either. One threshold between "the main screen, still"
                     # and "a board", not a fine judgement about which board.

# --- the route in ------------------------------------------------------------
# Read off photographs of this game on this window, not guessed: `out/drive-t1-menu-after`
# is the menu these coordinates were measured on and `drive-t2-training-after` the dialog.
# Every one of them is clear of the denylist, so the way in needs no exception at all -
# only the deploy gesture ever comes near a box.
MENU = (0.916, 0.107)             # the hamburger, top right of the main screen
TRAINING_CAMP = (0.598, 0.328)    # its fifth item, below the TV Royale / Training divider
CONFIRM = (0.681, 0.578)          # "Do you want to start a training match?" -> OK
LOADING = 6.0                     # seconds from OK to a board that accepts input, which
                                  # includes the match's own 3-2-1 countdown
RESULT_OK = (0.500, 0.909)        # the OK plate under the scoreboard, measured on
                                  # out/battle-end.png at (0.502, 0.907) twice running

# --- the card panel ----------------------------------------------------------
# Measured off out/battle-t060.png, a 450x800 frame of a live board: the row of four cards
# spans x 92..392 and y 660..750, so the slots are 0.167 wide and the row starts at 0.204.
# Cheaper to derive the four boxes from that one measurement than to write four down, and
# the arithmetic is the claim being made - four equal slots in a row - stated once.
# Two slivers at the far ends of the panel, and the reason they are slivers is measured.
# The obvious region is the whole strip, and it does not work: over thirty seconds of live
# play a full-width strip drifted 7% away from its own opening frame, and the elixir row
# alone drifted 25%, because the cards turn over and the bar fills. A run with the
# threshold at 50% called a match finished after twenty-two seconds and left the trainer to
# win 3-0 unopposed.
#
# These two columns are the parts of the panel the game never draws in: outside the card
# row on the right, outside the "Next:" thumbnail on the left. Measured across the same
# thirty seconds they moved 0% and 0-3% - one cell of thirty-six, twice - and on the result
# screen that follows, where they are grass, both read 100%. That is the whole margin this
# check needs, and it is an order of magnitude wider than the one it replaces.
PANEL_EDGES = ((0.0, 0.855, 0.030, 0.145), (0.955, 0.855, 0.045, 0.145))
PANEL_COLS, PANEL_ROWS = 3, 12
PANEL_GONE = 0.50   # fraction of a sliver that must stop agreeing with the board's own
                    # panel for "there is no card panel behind this any more". Both slivers
                    # have to clear it: they are grass together or they are panel together,
                    # so requiring both costs nothing against a real ending and rules out
                    # anything that only covers one end of the window.
PANEL_CELLS = PANEL_COLS * PANEL_ROWS

SLOT_COLS, SLOT_ROWS = 6, 6
SLOT_PLAYED = 0.40  # fraction of one slot that must change to call the card played. A
                    # replacement card is different artwork edge to edge; the noise this
                    # has to clear is a card un-greying, which is why it is not lower.
SLOT_ROW_TOP, SLOT_ROW_HEIGHT = 0.825, 0.113

# Centre and pitch rather than left edge and width, because the pitch is what the version
# before this one got wrong. It read the row off a 450px frame as starting at 0.204 with a
# 0.167 pitch, which put slot 4's grab point at 0.788 - in the *gap* between cards 3 and 4,
# where a drag picks up nothing at all. That run played 4 of 4 cards from slot 1 and 0 of 4
# from slot 4, and reported the failures as "no elixir", because a gesture that grabs air
# and a gesture that grabs an unaffordable card look identical from the slot.
#
# These numbers come from a brightness profile taken across a live card row - the artwork
# is bright and the gaps between cards are the panel's dark blue - which put the selected
# card's centre at 0.490 and its neighbour's at 0.686, and from out/battle-stuck.png at
# 787x1400, where the four cards measure x 192..300, 322..462, 480..600 and 615..765.
SLOT_FIRST, SLOT_PITCH, SLOT_WIDTH = 0.310, 0.188, 0.150

# The next-card thumbnail, bottom left, below the "Next:" label: x 25..95 and y 1290..1380
# of out/battle-stuck.png at 787x1400. This is where "was a card actually played" gets
# asked, and the slot it came from is the wrong place to ask - see `deploy`.
NEXT_CARD = (0.032, 0.921, 0.089, 0.065)
NEXT_COLS, NEXT_ROWS = 6, 4
NEXT_CELLS = NEXT_COLS * NEXT_ROWS
NEXT_PLAYED = 0.40  # fraction of the thumbnail that must change to call a card played

LANES = {1: 0.216, 3: 0.750, 4: 0.750}
# x of each bridge, measured on out/battle-stuck.png: the left one spans 0.184..0.248 and
# the right one 0.718..0.781. Slots 1 and 4 are one lane each; slot 3 is the third gesture
# the corrected geometry made legal, and it goes right because right is the only way it can
# go - see the docstring.
DEPTH = 0.470                   # y to drop at: just inside our own half at the near end
                                # of the bridge, so a card walks straight across. Backing
                                # it off groups cards up instead, which is `--depth`'s
                                # reason to exist.


@dataclass(frozen=True)
class Gesture:
    """One deploy: which slot, where to pick it up, where to put it, and how to tell."""
    slot: int
    grab: tuple[float, float]
    drop: tuple[float, float]
    box: tuple[float, float, float, float]


def gestures(depth: float = DEPTH) -> tuple[Gesture, ...]:
    """The two legal deploys at a given drop depth.

    The pairing of slot to lane is not a choice: slot 1 is the left of the panel and slot
    4 the right, so each reaches its own side's bridge without the path sweeping across
    the board - and, more to the point, without crossing the denylist box between them.
    """
    out = []
    for slot, lane_x in LANES.items():
        centre = SLOT_FIRST + (slot - 1) * SLOT_PITCH
        out.append(Gesture(slot=slot,
                           grab=(centre, 0.873),
                           drop=(lane_x, depth),
                           box=(centre - SLOT_WIDTH / 2, SLOT_ROW_TOP,
                                SLOT_WIDTH, SLOT_ROW_HEIGHT)))
    return tuple(out)


# --- how often to try -------------------------------------------------------

CADENCE = 1.6   # seconds between deploy attempts, flat, and flat on purpose.
                #
                # A version of this file steered the interval from the measured landing
                # rate: land three in a row and go faster, fail three and go slower. It
                # was the wrong shape of answer to a question that turns out not to be a
                # question. An attempt that cannot be paid for **costs nothing at all** -
                # the card stays in the slot, the elixir keeps filling at its own rate,
                # and the only thing spent is half a second of dragging that nothing else
                # was waiting on. So there is no interval to optimise: asking as often as
                # the drag itself allows spends every elixir at the first moment it can be
                # spent, which is the whole of what a good elixir policy does.
                #
                # What that loop actually did was drive itself to its own floor within
                # fifty seconds, which is the right answer arrived at for no reason. This
                # is the same answer, stated once, and it cannot be fooled by a bad
                # measurement because it does not read one.
                #
                # 1.6s rather than lower because a drag is about half a second and each
                # cycle also takes four small captures; below about 1.2s the loop is
                # mostly its own overhead.


# --- how much of the match to record -----------------------------------------

FRAME_EVERY = 60.0  # seconds between pictures. The record of what the match looked like,
                    # kept small: the PNG encoder is a Python loop over every pixel, and
                    # five matches' worth of full frames would spend more of the pass
                    # encoding than playing.
FRAME_LONGEST = 700
END_CONFIRM = 0.6   # seconds between the two panel readings that agree the match is over
DISMISS_TRIES = 3
DISMISS_SETTLE = 2.5
BETWEEN_MATCHES = 3.0


@dataclass
class Match:
    """What one match did, in the terms this file can actually measure."""
    number: int
    attempts: int = 0
    played: int = 0
    slot_said: int = 0          # the same question asked at the slot, kept for comparison
    per_slot: dict[int, int] = field(default_factory=dict)
    seconds: float = 0.0
    ended: str = ""             # why the loop stopped
    result: Path | None = None

    @property
    def rate(self) -> float:
        return self.played / self.attempts if self.attempts else 0.0

    def line(self) -> str:
        slots = ", ".join(f"slot {s}: {n}" for s, n in sorted(self.per_slot.items()))
        return (f"match {self.number}: {self.played} of {self.attempts} cards played "
                f"({self.rate:.0%}) in {self.seconds:.0f}s, {slots} "
                f"(the slot reading, which over-reports, said {self.slot_said}) "
                f"- {self.ended}")


def shoot(controller, name: str, longest: int = FRAME_LONGEST) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"battle-{name}.png"
    width, height = controller.write_capture(path, controller.capture(longest=longest))
    log(f"  wrote {path.name} ({width}x{height})")
    return path


def vet_the_gestures(controller, deploys: tuple[Gesture, ...]) -> None:
    """Refuse to start unless every gesture this file can send is clear of every box.

    Checked here, once, against the same `forbids`/`forbids_path` the send goes through,
    so a denylist that grows a box across one of these paths stops the run at the top
    rather than raising `PermissionError` out of the middle of a live match. The gestures
    are constants once `--depth` is fixed: if they pass here they pass every time.
    """
    for point, what in ((MENU, "the menu"), (TRAINING_CAMP, "the Training Camp item"),
                        (CONFIRM, "the confirm button"), (RESULT_OK, "the result OK")):
        why = controller.target.forbids(*point)
        if why:
            raise SystemExit(f"REFUSED before starting: {what} at {point} is denylisted "
                             f"- {why}")
    for deploy in deploys:
        why = (controller.target.forbids(*deploy.grab)
               or controller.target.forbids(*deploy.drop)
               or controller.target.forbids_path(deploy.grab, deploy.drop))
        if why:
            raise SystemExit(f"REFUSED before starting: the deploy gesture "
                             f"{deploy.grab} -> {deploy.drop} is denylisted - {why}")
        log(f"  deploy from slot {deploy.slot}: {deploy.grab} -> {deploy.drop}, clear of "
            f"all {len(controller.target.denylist)} boxes including the path between them")


def fraction_changed(before: bytes, after: bytes, cells: int, cell_delta: int) -> float:
    """How much of a grid stopped agreeing with itself, as a fraction of its cells.

    The one perception primitive in this file, asked three different questions: has the
    window left the screen it started on, has this card slot turned over, is the card
    panel still there at all. A change test rather than a content test in all three
    cases - "is this still the picture I photographed a moment ago" needs nothing to be
    true about the game, where every claim about what a particular pixel means is one more
    thing that a layout change makes silently wrong.
    """
    return changed_cells(before, after, cell_delta) / cells


def looks_like(controller, reference: bytes) -> float:
    """How much of the window still agrees with `reference`, as a fraction of cells."""
    now = controller.grab(GRID_COLS, GRID_ROWS)
    return 1.0 - fraction_changed(reference, now, GRID_COLS * GRID_ROWS,
                                  controller.target.cell_delta)


def panel(controller) -> tuple[bytes, ...]:
    """Both ends of the card panel, small.

    Grabbed without the foreground check on purpose: this runs twice per deploy inside a
    live match, and `grab`'s own check calls `ensure_readable`, which is allowed to restart
    the game. The caller checks focus itself instead, and has to - a frame read while
    something is in front of the window is a frame of that something, which disagrees with
    everything and reads here as the match ending. That is not hypothetical: the probe that
    measured these two regions had exactly that happen to it, and an occluded window is
    indistinguishable from a result screen in these numbers.
    """
    return tuple(controller.grab(PANEL_COLS, PANEL_ROWS, region=region, verify=False)
                 for region in PANEL_EDGES)


def navigate(controller) -> None:
    """Main screen -> menu -> Training Camp -> the dialog's OK, with a picture of each.

    Three taps on a route already photographed, each preceded by a focus check. That
    check is not defensive padding: the first run of this file sent all three taps into
    a window that was not in front, opened nothing, and then played a whole match's worth
    of gestures at the main screen. Input here goes to wherever the pointer is rather
    than to a window handle, so a tap sent to an unfocused window is a tap sent nowhere -
    and it fails silently, which is the only reason it survived a run.

    Whether it worked is then *measured*, by `require_board`, rather than assumed from
    three taps having been sent. The route can fail harmlessly; failing to notice cannot.
    """
    for point, name in ((MENU, "menu"), (TRAINING_CAMP, "training-camp"),
                        (CONFIRM, "confirm")):
        if not is_foreground(controller.hwnd):
            log("  window is not in front - focusing before tapping")
            controller.focus()
        log(f"  tapping {name} at ({point[0]:.3f}, {point[1]:.3f})")
        controller.click(*point)
        time.sleep(1.2)
    log(f"  waiting {LOADING}s for the board and its countdown")
    time.sleep(LOADING)


def require_board(controller, reference: bytes) -> None:
    """Stop the run unless the window has actually left the screen it started on.

    The one check that would have turned the first run's silent no-op into a ten-second
    failure. It says nothing about *which* screen is up - only that three taps changed
    something, which for this route means the board. If they did not, no gesture is sent
    at all: the alternative is what happened the first time, sixty-one drags aimed at
    card slots on a screen that has no cards on it.
    """
    agreement = looks_like(controller, reference)
    log(f"  the window agrees with the lobby by {agreement:.3f} "
        f"(under {SAME_SCREEN} means the way in worked)")
    if agreement >= SAME_SCREEN:
        shoot(controller, "no-board", longest=1400)
        raise SystemExit(
            "REFUSED to play: the window still looks like the lobby, so the way in to "
            "Training Camp did not work and there is no board to play on. Nothing was "
            "deployed. Read battle-no-board.png and check the three coordinates at the "
            "top of this file against it.")


def deploy(controller, gesture: Gesture) -> tuple[bool, float, float]:
    """Drag one card onto the board; say whether a card actually left the hand.

    The gesture being sent and a card being played are different events, and only the
    second one is worth counting: an unaffordable card can be picked up and dragged and
    simply does not deploy. Every version of this file before this one reported the first
    number and implied the second.

    **Where to ask, which took two goes.** The obvious place is the slot dragged from - a
    played card is replaced by the next one in the cycle, so the artwork changes. It does
    not work, and the live log said so immediately: twenty-one attempts in the first fifty
    seconds and twenty of them read as played, which no elixir budget in the game allows.
    The confound is the selection highlight. A drag that fails to deploy leaves its card
    *selected*, drawn enlarged with a glow around it, so the slot changes whether or not
    the card went anywhere - and it stays changed, so waiting longer does not help.

    So the question is asked at the next-card thumbnail instead. Playing a card advances
    the hand and the thumbnail shows the following card; nothing else moves it. It is not
    selected, not greyed by affordability, and not dragged. Both readings are returned and
    both are logged, because the slot number is the evidence for that paragraph and it
    costs one small capture to keep it honest.
    """
    slot_cells = SLOT_COLS * SLOT_ROWS
    slot_before = controller.grab(SLOT_COLS, SLOT_ROWS, region=gesture.box, verify=False)
    next_before = controller.grab(NEXT_COLS, NEXT_ROWS, region=NEXT_CARD, verify=False)
    controller.drag(gesture.grab, gesture.drop)
    slot_after = controller.grab(SLOT_COLS, SLOT_ROWS, region=gesture.box, verify=False)
    next_after = controller.grab(NEXT_COLS, NEXT_ROWS, region=NEXT_CARD, verify=False)
    delta = controller.target.cell_delta
    slot_moved = fraction_changed(slot_before, slot_after, slot_cells, delta)
    next_moved = fraction_changed(next_before, next_after, NEXT_CELLS, delta)
    return next_moved >= NEXT_PLAYED, next_moved, slot_moved


def panel_moved(controller, panel_ref: tuple[bytes, ...]) -> float:
    """How much the *less* changed of the two slivers has changed. Both or neither."""
    return min(fraction_changed(was, now, PANEL_CELLS, controller.target.cell_delta)
               for was, now in zip(panel_ref, panel(controller)))


def match_is_over(controller, panel_ref: tuple[bytes, ...]) -> tuple[bool, float]:
    """Has the card panel been replaced by something that is not a card panel?

    Confirmed twice, `END_CONFIRM` apart, and with a foreground check between the two,
    because there are two ways for these slivers to stop showing a panel and only one of
    them is the match ending. The other is something in front of the window, which reads
    100% on every region at once - and calling a live match finished means tapping the
    result screen's OK coordinate into a board, where it lands on a card rather than on a
    button. The wait also covers the ordinary case a single reading gets wrong, a spell or
    a tower collapse painting over the strip for one frame.
    """
    gone = panel_moved(controller, panel_ref)
    if gone < PANEL_GONE:
        return False, gone
    time.sleep(END_CONFIRM)
    if not is_foreground(controller.hwnd):
        log("  the window went behind something - not calling that the end of the match")
        controller.focus()
        return False, gone
    return panel_moved(controller, panel_ref) >= PANEL_GONE, gone


def play(controller, match: Match, seconds: float, panel_ref: tuple[bytes, ...],
         cadence: float, deploys: tuple[Gesture, ...]) -> Match:
    """Cycle the deploy gestures until the match ends or `seconds` are up.

    Three ways to stop, in the order they are hoped for: the panel goes away, which means
    the match finished - and it can finish well short of three minutes, because a
    three-crown win ends it on the spot. Then the timer, which is the backstop rather than
    the plan. Then a keyboard interrupt, handled by the caller.

    The window is re-focused whenever it is not in front, because input here is sent to
    wherever the pointer is rather than to a window handle: a match played into a window
    that lost focus is input sent at somebody else's application - and, since every
    measurement in the loop is a picture of that same window, it is also every threshold
    here reading nonsense at once.
    """
    started = time.monotonic()
    next_frame = FRAME_EVERY
    while True:
        elapsed = time.monotonic() - started
        match.seconds = elapsed
        if elapsed >= seconds:
            match.ended = f"the {seconds:.0f}s window ran out with the match still on"
            break
        if not is_foreground(controller.hwnd):
            log("  window is not in front - focusing before sending anything")
            controller.focus()

        over, gone = match_is_over(controller, panel_ref)
        if over:
            match.ended = (f"both ends of the card panel are gone ({gone:.0%} of the "
                           f"smaller one changed) - the match ended")
            break

        gesture = deploys[match.attempts % len(deploys)]
        played, next_moved, slot_moved = deploy(controller, gesture)
        match.attempts += 1
        match.played += played
        match.slot_said += slot_moved >= SLOT_PLAYED
        match.per_slot[gesture.slot] = match.per_slot.get(gesture.slot, 0) + played
        log(f"  [{elapsed:5.1f}s] {match.attempts:3d} slot {gesture.slot} -> "
            f"({gesture.drop[0]:.3f}, {gesture.drop[1]:.3f}): "
            f"{'played' if played else 'not played':10} "
            f"(next card {next_moved:3.0%}, slot {slot_moved:3.0%}, panel {gone:3.0%})")

        if elapsed >= next_frame:
            shoot(controller, f"m{match.number}-t{int(elapsed):03d}")
            next_frame += FRAME_EVERY
        time.sleep(cadence)

    return match


def dismiss_result(controller, reference: bytes) -> str:
    """Tap OK until the lobby is back, and give up loudly rather than tap forever.

    The lobby coming back is the only evidence that the result screen was dismissed, so it
    is what this waits for. Three tries because the screen animates its crowns in and can
    swallow an early tap; a fourth would be tapping into the dark, and this file would
    rather stop with a photograph than keep pressing a coordinate whose meaning it has
    stopped being able to check.
    """
    for attempt in range(1, DISMISS_TRIES + 1):
        agreement = looks_like(controller, reference)
        if agreement >= SAME_SCREEN:
            return f"the lobby is back (agrees {agreement:.3f})"
        if not is_foreground(controller.hwnd):
            controller.focus()
        log(f"  tapping OK at {RESULT_OK} - attempt {attempt}, the window agrees with "
            f"the lobby by {agreement:.3f}")
        controller.click(*RESULT_OK)
        time.sleep(DISMISS_SETTLE)
    agreement = looks_like(controller, reference)
    if agreement >= SAME_SCREEN:
        return f"the lobby is back (agrees {agreement:.3f})"
    shoot(controller, "stuck", longest=1400)
    raise SystemExit(
        f"STOPPING: {DISMISS_TRIES} taps on OK and the window still only agrees with the "
        f"lobby by {agreement:.3f}. Something is on screen that this file has never seen "
        f"and must not guess at. Read battle-stuck.png and clear it by hand.")


def require_lobby(controller, lobby: bytes, number: int) -> None:
    """Refuse to start a match from anywhere but the screen the first one started on.

    Matters only from the second match onward, and that is exactly why the lobby picture
    is taken once in `main` and passed down rather than re-taken here: a reference grabbed
    at the top of each match is a picture of whatever is on screen, so the check would
    pass unconditionally and mean nothing.

    What it is guarding against is the lobby coming back with something on top of it - a
    chest, a quest, a level-up, any of the things this game puts in front of the main
    screen. Training Camp pays out none of those, so it should not happen; if it does, the
    honest move is to stop with a photograph, because the alternative is navigating by
    coordinates that now point at a dialog.
    """
    agreement = looks_like(controller, lobby)
    log(f"  the window agrees with the lobby by {agreement:.3f}")
    if agreement < SAME_SCREEN:
        shoot(controller, f"m{number}-not-lobby", longest=1400)
        raise SystemExit(
            f"STOPPING before match {number}: the window agrees with the lobby by only "
            f"{agreement:.3f}, so something is in front of it and the way in to Training "
            f"Camp would be tapping at a dialog. Read battle-m{number}-not-lobby.png.")


def one_match(controller, number: int, args, cadence: float,
              deploys: tuple[Gesture, ...], lobby: bytes) -> Match:
    """Lobby -> board -> play -> dismiss -> lobby, measured at each of those joins."""
    log(f"\n--- match {number} of {args.matches} " + "-" * 40)
    if number > 1:
        require_lobby(controller, lobby, number)
    navigate(controller)
    require_board(controller, lobby)
    panel_ref = panel(controller)
    log(f"  photographed both ends of the card panel ({PANEL_COLS}x{PANEL_ROWS} cells "
        f"each); {PANEL_GONE:.0%} of *both* changing means the match is over")

    match = Match(number=number)
    try:
        play(controller, match, args.seconds, panel_ref, cadence, deploys)
    except KeyboardInterrupt:
        match.ended = "interrupted"
        raise
    finally:
        match.result = shoot(controller, f"m{number}-end", longest=1400)
        log(f"  {match.line()}")
    log(f"  {dismiss_result(controller, lobby)}")
    time.sleep(BETWEEN_MATCHES)
    return match


def main() -> None:
    readable_output()
    set_dpi_aware()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--title", default="Clash Royale")
    parser.add_argument("--matches", type=int, default=1,
                        help="how many Training Camp matches to play back to back. Each "
                             "one starts from the lobby and puts it back")
    parser.add_argument("--seconds", type=float, default=210.0,
                        help="the longest one match may take. A match is three minutes "
                             "plus a countdown, and one won on crowns ends sooner - this "
                             "is the backstop for a match whose end goes unnoticed, not "
                             "the expected length")
    parser.add_argument("--cadence", type=float, default=CADENCE,
                        help=f"seconds between deploy attempts. Flat - {CADENCE}s by "
                             f"default - because an attempt that cannot be paid for costs "
                             f"no elixir, so there is no interval to optimise")
    parser.add_argument("--depth", type=float, default=None,
                        help=f"y to drop cards at. {DEPTH} is the near end of the bridge, "
                             f"so a card walks straight in; a larger number drops further "
                             f"back, which lets consecutive cards arrive together")
    parser.add_argument("--navigate-only", action="store_true",
                        help="reach the board and stop, without deploying anything")
    parser.add_argument("--allow-battle", action="store_true",
                        help="required. This is the only file here that plays a match at "
                             "all, and Training Camp is the only match it may play")
    args = parser.parse_args()

    if not args.allow_battle:
        raise SystemExit(
            "REFUSED: this plays a match, so it will not run without --allow-battle. "
            "Training Camp is the one authorised battle - no rewards, no trophies, no "
            "opponent - and this file has no way to reach any other kind.")

    depth = args.depth if args.depth is not None else DEPTH
    cadence = float(args.cadence)
    deploys = gestures(depth)
    log(f"  a card every {cadence:.2f}s, dropped at y {depth:.3f}, from slots "
        f"{', '.join(str(g.slot) for g in deploys)}")

    controller = attach(args.title)
    controller.focus()
    vet_the_gestures(controller, deploys)
    log(controller.ensure_readable(allow_restart=False))
    shoot(controller, "start", longest=FRAME_LONGEST)

    # Taken before anything is tapped, and the only thing this run knows for certain about
    # what the game looks like. Every screen check in every match is measured against it.
    lobby = controller.grab(GRID_COLS, GRID_ROWS)

    if args.navigate_only:
        navigate(controller)
        require_board(controller, lobby)
        shoot(controller, "board", longest=1400)
        log("navigate-only: on the board, nothing deployed, nothing dismissed")
        return

    played: list[Match] = []
    try:
        for number in range(1, args.matches + 1):
            played.append(one_match(controller, number, args, cadence, deploys, lobby))
    except KeyboardInterrupt:
        log("\ninterrupted")
    finally:
        log("\n" + "=" * 62)
        for match in played:
            log(match.line())
        attempts = sum(m.attempts for m in played)
        total = sum(m.played for m in played)
        if attempts:
            log(f"{len(played)} match(es): {total} of {attempts} cards played "
                f"({total / attempts:.0%}) at {cadence:.2f}s per attempt")
        log("read the battle-m*-end.png frames for the crowns - the scoreboard is the "
            "one thing here nothing measures")


if __name__ == "__main__":
    main()
