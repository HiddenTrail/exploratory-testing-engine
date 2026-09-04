"""Play Training Camp matches back to back, measuring how well each one went.

The third entry point in this directory, and the narrowest. `run_recon.py` explores a game
it knows nothing about; `drive.py` runs a directed errand one hand-read tap at a time.
Neither can play a battle. Exploration would spend a vetting call per frame on a screen
that changes every frame, and a hand-driven tap takes longer to decide than the elixir
takes to refill.

So this file is the opposite of both: no model, and an action space of fifteen gestures -
three usable card slots at each of five destinations. It is not a Clash Royale AI. It is the
smallest thing that can put the right cards on the board fast enough to matter, and its
whole claim to safety is that all fifteen gestures are fixed constants checked before the
first one is sent.

**The strategy is not in this file.** It is in `plan.py`, which was given four rules and
implements those and nothing else: destroy one tower and attack from that side; put our
troops as far from their surviving tower as the arena allows while still closing on the
king; giants attack, ranged supports, knights defend; don't throw spells at empty space.
This file's job is to take the pictures those rules need, hand them over, and carry out
whichever of its pre-vetted gestures comes back. `plan.decide` returns a *purpose* - and so
cannot name a coordinate nobody vetted - or nothing at all, which is a decision too.

**What it can see.** Three readings a pass, each in its own module and each answering a
question the others cannot:

  * `hand.py` - which of the four cards can be paid for, what they are, and how much elixir
    there is. The game draws unaffordable cards in greyscale, so affordability is read off
    the card rather than inferred. This is what makes "hold one pass for the Giant" possible
    and is the biggest single change in how the driver behaves: a run that could not read
    the panel spent about five attempts in six dragging cards it could not pay for.
  * `towers.py` - which of the four princess towers are standing. Rule 1 in one reading.
  * `arena.py` - which quadrant is moving, by comparing this pass's picture with the last.
    It detects **movement, not enemies**: a change test cannot tell whose troops those are,
    so a lane we just deployed into is marked untrustworthy for a couple of seconds rather
    than mistaken for a threat. Only our own half is believed at all - their half moves with
    the red no-deploy overlay, which comes and goes with our own card selection. The look
    must be taken **at the same point in every pass** or it detects the interface instead of
    the board; `play` says why at length, and it is the single most breakable thing here.
    `--blind` turns it off, as the control condition for whether it helps.

Most passes are ordinary attacks, and that is correct: nothing attacks us for most of a
Training Camp match, and a card played into a quiet board is a card attacking.

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

As it stands - and `plan.REACH` is where it is stated, because the policy has to know:
slot 1 (centre x 0.310) reaches the left of the board, slots 3 (0.686) and 4
(0.874) reach the right, and **slot 2 (0.498) reaches neither**. Slot 2 sits squarely
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
that frame before a single gesture is sent.

That was originally a change test and nothing else, on the argument that "is there a magenta
elixir bar here" is a claim about a bar and one more thing to be wrong about, while "is this
still the picture I took a moment ago" needs nothing to be true about the game. The argument
was good and the conclusion was wrong, and a later run showed why: **a change test cannot
tell a board from anything else that moves.** That run was started while the client was still
loading. The reference frame was a loading screen, the three taps went into artwork, the
screen duly changed - a percentage bar advances by itself - and four gestures were sent at a
picture. So there are now two tests either side of that mistake. `settled_lobby` refuses to
take a reference picture of a window that is still moving, which is the only way to rule out
a loading screen without describing one. And `require_board` adds the content test after all:
the elixir bar has to be showing, measured at 17%-87% pink on every board frame on disk
against 0%-1% on every frame that is not a board. A content test whose two populations are
that far apart is worth its own risk of being wrong, and being wrong about it means refusing
to play rather than playing something that is not a board.

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

**What "played better" means here**, since it has to mean something measurable. A drag whose
card cannot be paid for does nothing at all - the card stays in the hand - so the count of
gestures sent has never been the count of cards played, and the runs before the panel could
be read reported the former while implying the latter. Now that `hand` says which cards are
payable *before* the drag, the landing rate finally measures the drag: an attempt sent at a
card the driver believed it could afford, that then failed to deploy, is a real failure and
not an unpaid bill.

*When* to read that turned out to matter more than where, and it took three wrong answers to
find out. Watching the slot the drag started from over-reports, because a failed drag leaves
its card *selected* and the slot changes either way. Watching the next-card thumbnail
under-reports, because it moves only when the hand-cycle animation finishes. Watching the
elixir bar across the drag under-reports too, because the bar drains with an animation of its
own - a match won two towers while reporting 0 of 23 attempts landed. Every fast signal this
interface offers is an animation in progress.

So the landing is judged a whole pass later, against the elixir the *next* pass reads: a
spend is the game's own accounting, it cannot be faked by a highlight, and by then it has
finished happening. The reading is taken anyway, so it costs nothing, and the only price is
that the last attempt of a match is never judged - which is reported as such rather than
counted as a failure. The slot reading is still taken and still logged, as the over-reporting
number it is, so the two can be compared on any future run.

The cadence is flat, because there is nothing to tune. An attempt that cannot be paid for
costs a drag and no elixir, so sending attempts faster than the hand can fill them is free
- the only thing a slower interval would buy is a lower attempt count for the same number
of cards played. The earlier version of this file ran a closed loop that moved the interval
on the landing rate; with the rate as confounded as it was, all that loop did was drive
itself to its own floor, which is where a flat cadence already is.

There are now two flat cadences, and the second one is the point. A pass that decides to
send nothing pays no drag, so it can look again in `HOLD_CADENCE` rather than `CADENCE` -
which matters because the reason to hold is elixir arriving on the game's clock, and a long
hold interval is how a Giant held at 4 elixir gets played most of a second late.

**How fast it can go**, since "faster" was a guess twice before it was a measurement. The
seven captures a pass takes were timed through the same `grab_thumbnail` the run uses, at
the same sizes: 6ms each for the small ones, 12ms for the arena, 48ms in total - about 2% of
a cycle. So trimming captures, which was the obvious place to look, buys nothing. What a
pass is actually made of is the drag and the wait, and both came down: the cadence from 1.6s
to 0.9s and the pre-drag hover from 0.20s to 0.08s, for roughly 1.33s a pass against 2.17s
measured before. The floor is about 0.43s, and it is the drag.

Run:  python experiments/android-bot/battle.py --allow-battle
      python experiments/android-bot/battle.py --allow-battle --matches 5
      python experiments/android-bot/battle.py --allow-battle --blind
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

import arena  # noqa: E402
import hand  # noqa: E402
import plan  # noqa: E402
import towers  # noqa: E402
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

# Before that reference is taken at all, the window has to stop moving - see
# `settled_lobby` for the run this was learned on. STILL is tighter than 1 - SAME_SCREEN
# because it is measuring the same screen against itself a second apart rather than two
# screens against each other: the idle main screen measured 0.971 self-agreement, i.e. it
# moves by about 0.029 on its own, so 0.05 leaves room for the water and the flags while
# a loading screen's advancing percentage bar moves far more.
STILL = 0.05
SETTLE_WAIT = 1.0
SETTLE_TRIES = 30    # 30 seconds. A cold start of this client takes about twenty to reach
                     # the main screen, so this waits rather than refusing a client that is
                     # simply not ready yet - but it does refuse eventually, because a
                     # client stuck at 94% on a Content Update never becomes still.

# The elixir bar's strip, and the fraction of it that must be pink for a board to be up.
# Measured across eleven frames: boards 17%-87%, and the lobby, a loading screen, two
# off-board captures and a result screen all 0% or 1%. The threshold is nearer the lower
# board reading than the higher non-board one because being wrong here should mean refusing
# to play a real board, not playing something that is not one.
ELIXIR_STRIP = (0.276, 0.968, 0.688, 0.022)
BAR_SHOWING = 0.08
# How long `require_board` will wait for the bar to appear before refusing. Five seconds,
# because the thing being waited out is the match's opening countdown - a real board refused
# a run at 2:53 on the clock, one look too early - and three seconds of countdown plus the
# margin for a slow load is what that costs. Refusing late is free; refusing wrongly is not.
BAR_TRIES, BAR_WAIT = 10, 0.5

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
# of out/battle-stuck.png at 787x1400. Kept, and no longer asked "was a card played" - it
# answers that question too slowly to be asked at all. See `deploy` for both wrong answers
# and the measurement that replaced them.
NEXT_CARD = (0.032, 0.921, 0.089, 0.065)
NEXT_COLS, NEXT_ROWS = 6, 4
NEXT_CELLS = NEXT_COLS * NEXT_ROWS

# A card is called played when the elixir bar reads at least this much lower on the pass
# *after* the drag than it did on the pass that sent it. One segment, because there is
# nothing to gain from a finer threshold: the cheapest card in any deck seen here is Goblins
# at 2, so every real spend clears this twice over.
#
# The direction is what makes one segment safe. Regeneration is the only other thing that
# moves the number and it moves it *up* - about 0.3 of an elixir across a 0.9s pass - so it
# can hide a spend but can never invent one. `hand.elixir_from` also under-reads a
# part-filled segment, consistently at both ends, which cancels in a difference.
SPEND_SEGMENTS = 1

GRAB_ROW = 0.873   # y of a card's own artwork, where a deploy picks it up

# --- where a card goes -------------------------------------------------------
# Five destinations per lane, one per purpose `plan.decide` can ask for. Written out rather
# than derived from a depth, because they are not five depths on one line: `deep` changes x
# as well as y, and `spell-ours` aims at a quadrant rather than a lane.
#
# The x figures are measured off out/battle-m1-t000.png at 393x700, checked against
# out/crop-upper-grid.png, which is that frame at 2x with a gridline every 0.05:
#
#   * the **bridges** at x 0.216 and 0.750, spanning 0.184..0.248 and 0.718..0.781.
#   * the **mown playfield** from x 0.127 to 0.878, so its outer margins are about 0.03
#     wide once the banks are excluded. The scenery either side is the same green - see
#     `arena.py` - so the edge was found by eye on the crop, not by colour.
#   * **their princess towers** centred at x 0.235 and 0.757, standing on ground that spans
#     y 0.161..0.244, and their **king tower** at x 0.50 spanning y 0.080..0.176.
#   * the **river** at y 0.432, agreeing with `arena.RIVER`.
#
# The y figures are what the strategy asks for, one purpose at a time:
#
# `attack` (0.470) is just inside our own half at the near end of the bridge, so a card
# walks straight across. This is the old `DEPTH` and the only destination this file had for
# most of its life.
#
# `push` (0.545) is a little further back, and it is for support *behind* a tank. A
# Musketeer dropped level with a Giant arrives beside it and dies first; dropped a body
# behind, it walks in the Giant's shadow. Only ever chosen when a tank actually went into
# this lane recently - see `plan.attack_purpose`, which will not drop support deep behind
# nothing.
#
# `defend` (0.600) is between the bridge and our own tower, so the card meets what is
# coming instead of walking past it. Our own princess towers' HP bars sit at y 0.620, so
# this is just in front of the thing being defended rather than on top of it.
#
# `deep` is rule 2 of the strategy, and the only destination in **their** half: x hard
# against the outer margin at 0.160 or 0.845. It is only ever asked for on a lane where
# their princess tower has already fallen, which is what unlocks the ground -
# `plan.attack_purpose` returns it on no other condition. Far side of the arena from their
# surviving tower (0.60 away in x) and walking at the king: "as far from the other castle,
# as close to the main castle as possible", which is what was asked for. If the ground
# turns out not to be unlocked the drag deploys nothing and the log says "not played",
# which is the safe direction to be wrong in.
#
# **The two sides are not at the same depth, and that is the safety gate's doing.** Left
# goes to y 0.230, level with the ground their princess tower stood on. Right cannot: the
# Pass Royale denylist box covers x 0.59..0.99, y 0.14..0.25 - a paid subscription offer
# that lives on the lobby screen, at coordinates that in a battle happen to be their right
# tower. The first version of this block put the right drop at y 0.230 and the startup gate
# refused the whole run, correctly: nothing here knows for certain that the lobby is gone,
# and a drag ending on that banner is a drag ending on a purchase. So the right drop sits
# at y 0.280, below the box by 0.03 and below the tower ground by about a tile and a half.
# It is the deepest that side can be sent without asking the gate to trust the clock. The
# asymmetry is roughly 2.5 tiles of walk-in, it is printed by the gate on every run, and it
# is not corrected for anywhere - only one lane is ever `deep` at a time, so the two are
# never compared inside a match, but a log that shows both across matches should show why
# the right one arrives later.
#
# `spell-ours` is the centroid of the arena quadrant that measured busy - x 0.270 or 0.730,
# y 0.628 - and it is aimed there because that is the box the reading came out of. Our half
# only: `arena`'s their-half numbers move with the red no-deploy overlay rather than with
# anything on the board, so a spell aimed by them would be aimed at our own card selection.
DROPS = {
    "attack":     {"left": (0.216, 0.470), "right": (0.750, 0.470)},
    "push":       {"left": (0.216, 0.545), "right": (0.750, 0.545)},
    "defend":     {"left": (0.216, 0.600), "right": (0.750, 0.600)},
    "deep":       {"left": (0.160, 0.230), "right": (0.845, 0.280)},
    "spell-ours": {"left": (0.270, 0.628), "right": (0.730, 0.628)},
}

# Kept under their old names because the rest of the file and its tests talk about them, and
# derived from `DROPS` rather than repeated, so a depth cannot be changed in one place only.
DEPTH = DROPS["attack"]["left"][1]
DEFEND_DEPTH = DROPS["defend"]["left"][1]

# Which x each slot's cards end up at, for `arena.slots_for`. Derived from `plan.REACH` and
# `DROPS` for the same reason: reachability is a fact about the denylist and it should be
# stated once. `plan.py` states it, having measured it; this is the same fact in the units
# `arena.slots_for` wants.
LANES = {slot: DROPS["attack"][lane][0] for slot, lane in plan.REACH.items()}

DRAG_HOVER = 0.08               # how long the pointer sits on a card before the press.
                                # `Controller.drag` defaults to 0.20, which is the right
                                # default for a UI nobody has measured: the pause exists
                                # so the press is hit-tested where the pointer now is
                                # rather than where it was, and 0.20 is generous enough
                                # to survive any frame rate. Here the target is a static
                                # card in a panel that has been dragged from thousands of
                                # times, so the margin can come down to about five frames
                                # at 60Hz - and it is 120ms off every attempt, which is
                                # the second largest saving available after the cadence.


@dataclass(frozen=True)
class Gesture:
    """One deploy: which slot, where to pick it up, where to put it, and how to tell.

    `purpose` is not a switch - what the gesture does is entirely in `drop`. It is the key
    the catalogue is looked up by and the word the log prints, because five gesture sets
    that differ in the third decimal of a coordinate are unreadable otherwise.
    """
    slot: int
    purpose: str
    grab: tuple[float, float]
    drop: tuple[float, float]
    box: tuple[float, float, float, float]


def catalogue() -> dict[tuple[int, str], Gesture]:
    """Every deploy this file can send: one per (reachable slot, purpose).

    Built once at startup and vetted in one place before anything is sent, which is the
    whole of this file's safety claim and the reason `plan.decide` returns a *purpose* and
    not a coordinate. The policy chooses from a fixed, pre-checked set; it cannot invent a
    drop point, and a purpose with no vetted gesture for that slot is a `KeyError` at the
    top of the run rather than a drag sent somewhere nobody looked at.

    The pairing of slot to lane is not a choice either - see `plan.REACH`. Slot 1 reaches
    left, slots 3 and 4 reach right, and slot 2 reaches nothing, because the Battle
    button's denylist box sits between the card row and the board.
    """
    book: dict[tuple[int, str], Gesture] = {}
    for slot, lane in plan.REACH.items():
        centre = SLOT_FIRST + (slot - 1) * SLOT_PITCH
        for purpose, sides in DROPS.items():
            book[(slot, purpose)] = Gesture(
                slot=slot, purpose=purpose,
                grab=(centre, GRAB_ROW),
                drop=sides[lane],
                box=(centre - SLOT_WIDTH / 2, SLOT_ROW_TOP, SLOT_WIDTH, SLOT_ROW_HEIGHT))
    return book


def lane_of(gesture: Gesture) -> str:
    """Which side of the board a gesture puts a card on.

    Read off the gesture's own drop coordinate rather than stored on it, so a lane is a
    consequence of where the card goes and cannot disagree with it.
    """
    return "left" if gesture.drop[0] < 0.5 else "right"


# --- how often to try -------------------------------------------------------

CADENCE = 0.9   # seconds between deploy attempts, flat, and flat on purpose.
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
                # **0.9s, down from 1.6s, and the number came from measuring the loop
                # rather than from nerve.** The floor is not a guess: the seven captures a
                # pass takes were timed through the same `grab_thumbnail` the run uses, at
                # the same pixel sizes, and they cost 6ms each for the small ones and 12ms
                # for the arena - 48ms in total, about 2% of a cycle. What the cycle is
                # actually made of is the drag: 0.08s of hover, 0.06s of grab, 0.14s of
                # glide and 0.10s of settle, so a pass cannot go below ~0.43s no matter
                # what this constant says. 0.9s leaves the loop about two thirds spent
                # waiting, which is the margin that keeps the interval meaningful.
                #
                # Faster is also better on the evidence rather than merely tolerable.
                # Across five matches the fraction of attempts that landed a card *rose*
                # with the attempt rate - 4% at the slowest, 20-21% at the fastest - which
                # an elixir-limited model forbids and which says the drag itself is
                # unreliable. Repetition, not patience, lands cards. Cutting the interval
                # buys reaction latency and landing rate at the same time.
                #
                # **The last paragraph is now known to be wrong about why**, and it is left
                # standing because the conclusion survives its own reasoning. Reading the
                # card panel showed that most attempts were bouncing off *greyed* cards:
                # 147s of Training Camp yields about 67 elixir, and 19 cards at ~3 each is
                # 57 of it, so the loop was already near the elixir ceiling rather than
                # losing drags. The drag is not unreliable; repetition helped because
                # asking more often catches each card sooner after it becomes affordable.
                # Same number, better reason - and now that `hand` can see which cards are
                # payable, the landing rate finally measures the drag rather than the deck.

HOLD_CADENCE = 0.35  # seconds between passes that send nothing at all.
                     #
                     # A pass that holds costs two small captures and no drag - about 20ms
                     # against the drag's 430 - so the reason to wait a full `CADENCE`
                     # after deciding not to play is gone. What waiting a full cadence
                     # *costs* is the whole point of holding: the driver holds for a card
                     # one elixir away, and elixir arrives on the game's clock rather than
                     # on ours, so a long hold interval is how a held Giant gets played
                     # most of a second after it became payable. Shorter here spends the
                     # saved drag time on looking again sooner, which is the only thing a
                     # holding pass can usefully do.


# --- how much of the match to record -----------------------------------------

FOLLOW_FOR = 6.0    # seconds a tank counts as still being in its lane, so support dropped
                    # after it goes *behind* it rather than to the bridge. A Giant walks
                    # from the bridge to a princess tower in something over five seconds and
                    # the whole point of support is to arrive while it is still soaking, so
                    # this is the length of the window where "behind the tank" is a real
                    # place. Longer and support trails a Giant that is already dead; the
                    # tank memory is a claim about the board, and claims about the board
                    # expire.

FRAME_EVERY = 60.0  # seconds between pictures. The record of what the match looked like,
                    # kept small: the PNG encoder is a Python loop over every pixel, and
                    # five matches' worth of full frames would spend more of the pass
                    # encoding than playing.
FRAME_LONGEST = 700
END_CONFIRM = 0.6   # seconds between the two panel readings that agree the match is over
DISMISS_TRIES = 3
DISMISS_SETTLE = 2.5
BETWEEN_MATCHES = 3.0


@dataclass(frozen=True)
class Pending:
    """A drag that has been sent and whose outcome is not known yet.

    Exists because the interface answers "did that land" about a second and a half late -
    see `deploy` - so the answer belongs to the *next* pass. Everything the resolution needs
    is captured here rather than looked up again, because by the time it resolves the hand
    has moved on: `elixir` is the reading to compare against, `role` is what was in the slot
    at the time, and `at` is when the card actually went down, which is what the lane memory
    and the tank memory must both be measured from rather than from the moment we found out.
    """
    gesture: "Gesture"
    elixir: int
    role: str | None
    at: float


@dataclass
class Match:
    """What one match did, in the terms this file can actually measure."""
    number: int
    attempts: int = 0
    played: int = 0
    unresolved: int = 0         # attempts the match ended before the next pass could judge
    slot_said: int = 0          # the same question asked at the slot, kept for comparison
    per_slot: dict[int, int] = field(default_factory=dict)
    per_purpose: dict[str, int] = field(default_factory=dict)
    defences: int = 0           # attempts sent to defend or to spell a busy lane of ours
    defended: int = 0           # ...of which this many actually put a card down
    holds: int = 0              # passes that deliberately sent nothing
    crowns_for: int = 0         # the last tower reading of the match, which is the score
    crowns_against: int = 0
    seconds: float = 0.0
    ended: str = ""             # why the loop stopped
    result: Path | None = None

    @property
    def judged(self) -> int:
        """Attempts the loop got to see the outcome of. The denominator for `rate`, because
        the last attempt of a match is never judged - the match ends before the pass that
        would have judged it - and counting it as a failure would report a rate that got
        worse the shorter the match was."""
        return self.attempts - self.unresolved

    @property
    def rate(self) -> float:
        return self.played / self.judged if self.judged else 0.0

    def line(self) -> str:
        slots = ", ".join(f"slot {s}: {n}" for s, n in sorted(self.per_slot.items()))
        purposes = ", ".join(f"{p}: {n}" for p, n in sorted(self.per_purpose.items()))
        unjudged = f", {self.unresolved} unjudged at the whistle" if self.unresolved else ""
        return (f"match {self.number}: {self.crowns_for}-{self.crowns_against} on the last "
                f"tower reading; {self.played} of {self.judged} cards played "
                f"({self.rate:.0%}) in {self.seconds:.0f}s and {self.holds} passes held"
                f"{unjudged}, {slots} (the slot reading, which over-reports, said "
                f"{self.slot_said}); as {purposes}; {self.defended} of {self.defences} "
                f"defensive attempts landed - {self.ended}")


# The run's own name, prefixed to every frame it photographs. A module-level value rather
# than a parameter threaded through four functions because it is a property of the process
# and not of any one call: one run, one label, chosen once in `main` and never changed.
RUN_LABEL = ""


def shoot(controller, name: str, longest: int = FRAME_LONGEST,
          label: str | None = None) -> Path:
    """Photograph the window into `out/`, under a name the run chose.

    The label is not decoration. Two runs of this file with the same `--matches` wrote the
    same `battle-m1-end.png`, and the second overwrote the first - which lost the control
    half of an A/B comparison whose whole point was the two scoreboards side by side. The
    result screen is the only place the crowns are recorded, so an overwritten frame is a
    match played and not measured.
    """
    label = RUN_LABEL if label is None else label
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"battle-{label + '-' if label else ''}{name}.png"
    width, height = controller.write_capture(path, controller.capture(longest=longest))
    log(f"  wrote {path.name} ({width}x{height})")
    return path


def vet_the_gestures(controller, book) -> None:
    """Refuse to start unless every gesture this file can send is clear of every box.

    Checked here, once, against the same `forbids`/`forbids_path` the send goes through,
    so a denylist that grows a box across one of these paths stops the run at the top
    rather than raising `PermissionError` out of the middle of a live match. The catalogue
    is a constant: if it passes here it passes every time, and `plan.decide` can only
    return keys that are in it.

    The margins printed are not decoration. Slot 3's paths clear the Battle button's box by
    between 0.001 and 0.004 of the window's width - four pixels at the top end - which is a
    coincidence of where that button sits rather than a designed clearance. Printing the
    number every run is how a re-measurement of the card row shows up as a shrinking margin
    instead of as a surprise.
    """
    for point, what in ((MENU, "the menu"), (TRAINING_CAMP, "the Training Camp item"),
                        (CONFIRM, "the confirm button"), (RESULT_OK, "the result OK")):
        why = controller.target.forbids(*point)
        if why:
            raise SystemExit(f"REFUSED before starting: {what} at {point} is denylisted "
                             f"- {why}")
    boxes = len(controller.target.denylist)
    for key in sorted(book):
        deploy = book[key]
        why = (controller.target.forbids(*deploy.grab)
               or controller.target.forbids(*deploy.drop)
               or controller.target.forbids_path(deploy.grab, deploy.drop))
        if why:
            raise SystemExit(f"REFUSED before starting: the {deploy.purpose} gesture from "
                             f"slot {deploy.slot}, {deploy.grab} -> {deploy.drop}, is "
                             f"denylisted - {why}")
        log(f"  slot {deploy.slot} {deploy.purpose:11} -> "
            f"({deploy.drop[0]:.3f}, {deploy.drop[1]:.3f}) {lane_of(deploy):5} "
            f"clear of all {boxes} boxes by {clearance(controller, deploy):.4f} "
            f"including the path between them")


def clearance(controller, deploy: Gesture) -> float:
    """How much room a drag's path has, as the nearest it comes to any denylisted box.

    A distance rather than a yes or no, and it is a *sampled* distance - the exact
    segment-rectangle test in `forbids_path` answers whether the line touches a box and
    cannot say how nearly it did. So this is reporting only: `forbids_path` decides, this
    describes. Sampling is safe for that job in a way it would not be for the decision.

    Per-axis rather than diagonal, which understates the clearance of a path that is outside
    a box on both axes at once. That is the direction to be wrong in for a number whose only
    job is to look alarming when it should.
    """
    nearest = 1.0
    (x0, y0), (x1, y1) = deploy.grab, deploy.drop
    for entry in controller.target.denylist:
        bx, by, bw, bh = entry["box"]
        for step in range(101):
            at = step / 100
            x, y = x0 + (x1 - x0) * at, y0 + (y1 - y0) * at
            gap = max(bx - x, x - (bx + bw), by - y, y - (by + bh))
            nearest = min(nearest, gap)
    return nearest


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


def settled_lobby(controller) -> bytes:
    """Wait until the window stops moving, then photograph it as the lobby.

    **Why this exists**, because it was learned the expensive way. A run was started while
    the client was still on its loading screen at 81%. Every later check compares against
    the picture taken here, so the run spent the whole match measuring against a loading
    screen: it tapped the three navigation coordinates into artwork, `require_board` saw the
    screen change - a percentage bar advances, so of course it changed - and the match-over
    detector compared two loading frames, agreed they had both changed, and declared a
    six-second match. Four gestures were sent at a picture of a barbarian. Nothing was lost
    because none of it was a board, but nothing about the run was true either.

    A loading screen is the one thing here that can be ruled out without a content test: it
    *moves*, and a lobby does not. So the reference is only taken once two grabs a second
    apart agree, and the run refuses rather than photographing something in motion. Note
    that this is a stillness test and not a lobby test - a result dialog is also still, and
    `require_lobby` is what catches that from the second match onward.
    """
    previous = controller.grab(GRID_COLS, GRID_ROWS)
    for attempt in range(1, SETTLE_TRIES + 1):
        time.sleep(SETTLE_WAIT)
        now = controller.grab(GRID_COLS, GRID_ROWS)
        moved = fraction_changed(previous, now, GRID_COLS * GRID_ROWS,
                                 controller.target.cell_delta)
        log(f"  the window moved {moved:.3f} in {SETTLE_WAIT}s "
            f"(attempt {attempt} of {SETTLE_TRIES}; under {STILL} is still enough to "
            f"photograph)")
        if moved < STILL:
            return now
        previous = now
    shoot(controller, "never-settled", longest=1400)
    raise SystemExit(
        f"REFUSED to start: after {SETTLE_TRIES} tries the window is still moving by more "
        f"than {STILL} every {SETTLE_WAIT}s, so there is nothing steady to measure against "
        f"and every later check would be comparing to a moving picture. The usual cause is "
        f"a loading screen - wait for the client to reach the main screen and run again. "
        f"Nothing was tapped. Read battle-never-settled.png.")


def elixir_showing(controller) -> float:
    """Fraction of the elixir bar's strip that is actually pink bar.

    The positive half of `require_board`, and the reason it is measured rather than assumed:
    across every board frame on disk this reads 17% to 87%, and across every frame that is
    *not* a board - the lobby, the loading screen, two off-board captures and a result
    screen - it reads 0% or 1%. The bar is the one piece of interface that is on a board and
    nowhere else, and unlike the HP bars or the card boxes it cannot be imitated by artwork
    that happens to be the right colour: a loading screen's own progress bar sits in the
    same place and is blue, which is why the test is for pink specifically.

    Nothing here counts *how much* elixir there is - `hand.elixir_from` does that, more
    carefully. This only asks whether the thing is present at all.
    """
    strip, _, _ = controller.capture(region=ELIXIR_STRIP, longest=1400)
    pink = seen = 0
    for index in range(0, len(strip), 4):
        blue, green, red = strip[index], strip[index + 1], strip[index + 2]
        seen += 1
        pink += red > 90 and blue > 90 and green < red - 25
    return pink / seen if seen else 0.0


def require_board(controller, reference: bytes) -> None:
    """Stop the run unless a board is actually up: it changed, *and* it has an elixir bar.

    The change test alone was not enough, and the way it failed is instructive. It says only
    that three taps changed something, which was meant to catch the taps missing - and it
    does. What it cannot catch is starting from a screen that was never the lobby, because a
    loading screen changes all by itself and so passes a change test every time. `settled_lobby`
    now makes that much harder to reach, but a change test still cannot tell a board from any
    other screen, and this is the file that sends drags at card slots.

    So the second half is a positive test: the elixir bar has to be there. If either half
    fails no gesture is sent at all - the alternative is what happened twice, drags aimed at
    card slots on a screen that has no cards on it.

    **The bar is waited for, not sampled once.** A single reading refused a real board - all
    four towers up, 2:53 on the clock, eight elixir plainly showing - because it landed on the
    match's opening countdown, a second or so before the bar is drawn. The frame the refusal
    saved to disk already had the bar in it, which is how obvious the timing was. Waiting
    changes nothing about what is being asserted and loses nothing when the screen is
    genuinely not a board: that case simply takes `BAR_TRIES` short sleeps to refuse instead
    of none. This is the fourth thing in this file to have been measured too early, and the
    pattern behind all four is in `deploy`.
    """
    agreement = looks_like(controller, reference)
    if agreement >= SAME_SCREEN:
        shoot(controller, "no-board", longest=1400)
        raise SystemExit(
            "REFUSED to play: the window still looks like the lobby, so the way in to "
            "Training Camp did not work and there is no board to play on. Nothing was "
            "deployed. Read battle-no-board.png and check the three coordinates at the "
            "top of this file against it.")

    bar = 0.0
    for attempt in range(1, BAR_TRIES + 1):
        bar = elixir_showing(controller)
        log(f"  the window agrees with the lobby by {agreement:.3f} "
            f"(under {SAME_SCREEN} means the way in worked) and the elixir bar reads "
            f"{bar:.0%} pink (over {BAR_SHOWING:.0%} means a board; attempt {attempt} of "
            f"{BAR_TRIES})")
        if bar >= BAR_SHOWING:
            return
        time.sleep(BAR_WAIT)
    shoot(controller, "no-elixir-bar", longest=1400)
    raise SystemExit(
        f"REFUSED to play: the screen changed but after {BAR_TRIES} looks over "
        f"{BAR_TRIES * BAR_WAIT:.0f}s its elixir bar still reads only {bar:.0%} pink, and "
        f"every board frame measured reads at least 17%. Whatever is up is not a board, so "
        f"no card could be deployed onto it and none was. Read battle-no-elixir-bar.png.")


def deploy(controller, gesture: Gesture) -> float:
    """Drag one card onto the board. Returns the slot reading, which is not the answer.

    Whether a card *landed* is deliberately not decided here, and that is the third design
    of this function rather than a simplification. The gesture being sent and a card being
    played are different events, and only the second is worth counting: an unaffordable card
    can be picked up and dragged and simply does not deploy.

    **Three places to ask, and the first two were both wrong.** The obvious one is the slot
    dragged from - a played card is replaced by the next in the cycle, so the artwork
    changes. The live log killed it immediately: twenty-one attempts in the first fifty
    seconds and twenty read as played, which no elixir budget allows. The confound is the
    selection highlight - a drag that fails to deploy leaves its card *selected*, drawn
    enlarged and lit, so the slot changes either way and stays changed.

    The second was the next-card thumbnail, which nothing but a played card advances. Sound
    reasoning, useless measurement, and the reason is the reason for the third design: it
    was asked too early. The thumbnail moves when the hand-cycle animation finishes, and
    this function grabbed the instant the drag returned. A whole live match read 0% on every
    attempt but two while its own next log line showed the cards gone.

    The third was the elixir bar, on the grounds that a spend is the game's own accounting
    and cannot be faked by a highlight. Correct, and *still too early*: the bar drains with
    an animation. A run measuring it across the drag reported 0 of 23 attempts landed in a
    match it won two towers in, with every reading between -1.0 and +0.1 elixir, while the
    next pass 1.4s later showed the slot empty and the elixir down by the card's exact cost.

    So the question is not asked here at all. It is asked on the **next pass**, by comparing
    the elixir this pass read with the elixir the next one reads - see `Pending` and `play`.
    That reading is taken anyway, so the answer is free, and it arrives at a delay the game
    has already been measured to be finished with. The lesson the first three share is that
    every fast signal here is an animation: the only honest way to watch this interface is
    to look after it has stopped moving.

    The slot reading is still taken and still logged, because it is the evidence for the
    second paragraph and it costs one small capture - 6ms, timed through the same path at
    the same size, against a drag that takes eighty times that.
    """
    slot_cells = SLOT_COLS * SLOT_ROWS
    slot_before = controller.grab(SLOT_COLS, SLOT_ROWS, region=gesture.box, verify=False)
    controller.drag(gesture.grab, gesture.drop, hover=DRAG_HOVER)
    slot_after = controller.grab(SLOT_COLS, SLOT_ROWS, region=gesture.box, verify=False)
    return fraction_changed(slot_before, slot_after, slot_cells,
                            controller.target.cell_delta)


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


def read_state(controller) -> tuple[hand.Hand, towers.Towers]:
    """The hand and the four towers, one small capture each.

    One function rather than two calls at the site so `play`'s tests can substitute a board
    state without also having to fake a card panel's pixels. The readers themselves are
    checked against saved frames, where the answer is known because it was read by eye -
    that is a different kind of test from "does the loop do the right thing with a Giant in
    slot 3", and running them through the same fake window would confuse the two.
    """
    return hand.read(controller), towers.read(controller)


def play(controller, match: Match, seconds: float, panel_ref: tuple[bytes, ...],
         cadence: float, book: dict[tuple[int, str], Gesture], watching: bool = True,
         hold_cadence: float = HOLD_CADENCE) -> Match:
    """Read the board, ask `plan` what to do about it, and do that - or deliberately not.

    Three ways to stop, in the order they are hoped for: the panel goes away, which means
    the match finished - and it can finish well short of three minutes, because a
    three-crown win ends it on the spot. Then the timer, which is the backstop rather than
    the plan. Then a keyboard interrupt, handled by the caller.

    **Three readings a pass, and they answer different questions.** `hand` says which cards
    can be paid for and what they are; `towers` says which of the four are standing, which
    is the whole of the strategy's first rule; `arena` says which lane is moving. The policy
    is in `plan.py` and nothing here duplicates it - this function's job is to take the
    pictures, look the chosen purpose up in the pre-vetted catalogue, and count what
    happened. A `Move` that came back `None` is a decision and is counted as one.

    **`following` is a lane and a time, not a flag.** Support belongs behind a tank, and a
    tank that went in twenty seconds ago is not there any more, so the memory expires after
    `FOLLOW_FOR`. Without the clock this would spend the rest of a match dropping Musketeers
    a body behind a Giant that died at 0:40.

    **The look happens once per pass, at the same point in the pass**, and that is a
    requirement rather than a convenience. `arena.Watch` compares this pass's picture of
    the board with the previous pass's, so anything the interface draws in step with the
    loop's own actions - the selected card's name across the middle of the board, a tower's
    HP bar - appears in both pictures and cancels. Two frames taken at *different* points
    in the loop do not cancel: the pair one second apart that this file has on disk reads
    25% and 27% activity in our own half on a board where nothing was attacking us. Moving
    the look would silently turn the detector into a detector of ourselves.

    The window is re-focused whenever it is not in front, because input here is sent to
    wherever the pointer is rather than to a window handle: a match played into a window
    that lost focus is input sent at somebody else's application - and, since every
    measurement in the loop is a picture of that same window, it is also every threshold
    here reading nonsense at once.
    """
    started = time.monotonic()
    next_frame = FRAME_EVERY
    watch = arena.Watch(controller.target.cell_delta)
    # Why there is no reading, when there is none - and the two reasons are different. Under
    # `--blind` there is nothing to say on every line of the log; watching, the first line of
    # a match genuinely has one frame and nothing to compare it with.
    seeing = "first look, nothing to compare" if watching else "not watching"
    followed: tuple[str, float] | None = None   # lane a tank went into, and when
    pending: Pending | None = None              # last pass's drag, not yet judged
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

        # `--blind` skips the look rather than taking one and discarding it: the control
        # condition has to be the loop as it was, including not spending the grab, or "does
        # watching help" is measured against a loop that also watches.
        threat = watch.see(controller, elapsed) if watching else None
        in_hand, standing = read_state(controller)
        match.crowns_for, match.crowns_against = standing.crowns_for, standing.crowns_against

        # The verdict on last pass's drag, now that the bar has finished draining. Everything
        # that depends on a card having landed happens here rather than at the drag, because
        # here is the first moment it is known - and both memories are dated from `at`, when
        # the card actually went down, not from now.
        if pending is not None:
            spent = pending.elixir - in_hand.elixir
            landed = spent >= SPEND_SEGMENTS
            match.played += landed
            match.per_slot[pending.gesture.slot] = (
                match.per_slot.get(pending.gesture.slot, 0) + landed)
            match.per_purpose[pending.gesture.purpose] = (
                match.per_purpose.get(pending.gesture.purpose, 0) + landed)
            if pending.gesture.purpose in ("defend", "spell-ours"):
                match.defended += landed
            # Only a card that actually left the hand taints its lane, or starts a push for
            # the next support card to trail. A drag that deployed nothing put no troops on
            # the board, so there is nothing of ours there to mistake for theirs - and
            # marking the lane anyway would blind us for `OURS_FOR` seconds every failed drag.
            if landed:
                watch.deployed_into(lane_of(pending.gesture), pending.at)
                if pending.role == "tank":
                    followed = (lane_of(pending.gesture), pending.at)
            log(f"  [{elapsed:5.1f}s]      -> {'landed' if landed else 'nothing landed':14} "
                f"{spent:+d}e since {pending.at:.1f}s "
                f"({pending.elixir}e then, {in_hand.elixir}e now)")
            pending = None

        following = (followed[0] if followed and elapsed - followed[1] < FOLLOW_FOR
                     else None)
        move, why = plan.decide(in_hand, standing, threat, match.attempts, following)

        if move is None:
            match.holds += 1
            log(f"  [{elapsed:5.1f}s]  -  held: {why:38} | {in_hand.line()} "
                f"| {standing.line()} | {threat.line() if threat else seeing}")
            time.sleep(hold_cadence)
            continue

        gesture = book[(move.slot, move.purpose)]
        slot_moved = deploy(controller, gesture)
        match.attempts += 1
        match.slot_said += slot_moved >= SLOT_PLAYED
        if gesture.purpose in ("defend", "spell-ours"):
            match.defences += 1
        pending = Pending(gesture=gesture, elixir=in_hand.elixir,
                          role=in_hand.slots[gesture.slot - 1].role, at=elapsed)
        log(f"  [{elapsed:5.1f}s] {match.attempts:3d} {why:38} "
            f"slot {gesture.slot} {gesture.purpose:10} -> "
            f"({gesture.drop[0]:.3f}, {gesture.drop[1]:.3f}): sent "
            f"(slot {slot_moved:3.0%}, panel {gone:3.0%}) "
            f"| {in_hand.line()} | {standing.line()} "
            f"| {threat.line() if threat else seeing}")

        if elapsed >= next_frame:
            shoot(controller, f"m{match.number}-t{int(elapsed):03d}")
            next_frame += FRAME_EVERY
        time.sleep(cadence)

    # A drag still in flight when the loop stopped, which cannot be judged: the pass that
    # would have judged it is the pass that broke out, and on the way out the panel it would
    # have read has already been replaced by a result screen. Counted rather than guessed at,
    # and kept out of `rate` - see `Match.judged`.
    if pending is not None:
        match.unresolved += 1
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
              book: dict[tuple[int, str], Gesture], lobby: bytes) -> Match:
    """Lobby -> board -> play -> dismiss -> lobby, measured at each of those joins."""
    log(f"\n--- match {number} of {args.matches} " + "-" * 40)
    if number > 1:
        require_lobby(controller, lobby, number)
    navigate(controller)
    require_board(controller, lobby)
    panel_ref = panel(controller)
    log(f"  photographed both ends of the card panel ({PANEL_COLS}x{PANEL_ROWS} cells "
        f"each); {PANEL_GONE:.0%} of *both* changing means the match is over")
    # The opening board, before a single drag - and therefore the only frame of a board this
    # file takes with **no card selected**. That is what makes it worth its own capture
    # rather than leaving the first picture until t060: every other in-match frame is taken
    # moments after a drag, when the game paints a red no-deploy overlay across enemy
    # territory, so red troops and red overlay cannot be told apart in any of them. See
    # `arena.py` on why that confound is the thing standing between a change detector and
    # one that knows whose troops it is looking at.
    shoot(controller, f"m{number}-t000")

    match = Match(number=number)
    try:
        play(controller, match, args.seconds, panel_ref, cadence, book,
             watching=not args.blind, hold_cadence=args.hold_cadence)
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
    parser.add_argument("--hold-cadence", type=float, default=HOLD_CADENCE,
                        help=f"seconds between passes that send nothing. {HOLD_CADENCE}s by "
                             f"default, shorter than --cadence because a pass that holds "
                             f"pays no drag and is waiting on elixir that arrives on the "
                             f"game's clock rather than on ours")
    parser.add_argument("--blind", action="store_true",
                        help="do not watch the arena at all. The policy still reads the "
                             "hand and the towers - it has to, to play at all - so this is "
                             "now the control condition for the arena watch alone")
    parser.add_argument("--label", default=None,
                        help="prefix for this run's frames in out/. Defaults to blind or "
                             "watch, so the two halves of an A/B cannot overwrite each "
                             "other's result screen - which is the only record of the crowns")
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

    global RUN_LABEL
    RUN_LABEL = args.label if args.label is not None else ("blind" if args.blind else "watch")

    cadence = float(args.cadence)
    book = catalogue()
    log(f"  a card at most every {cadence:.2f}s, {args.hold_cadence:.2f}s when holding, "
        f"from slots {'/'.join(str(s) for s in sorted(plan.REACH))} "
        f"({', '.join(f'{s} reaches {lane}' for s, lane in sorted(plan.REACH.items()))}; "
        f"slot 2 reaches neither and is never dragged)")
    log(f"  the plan: attack {plan.OPENING_LANE} until a tower falls, then {DROPS['deep']} "
        f"on the open side; defend with {'/'.join(plan.DEFENDERS)} in that order; "
        f"attack with {'/'.join(plan.ATTACKERS)}; spell only our own half above "
        f"{plan.SPELL_BUSY:.0%} busy")
    log(f"  frames go to out/battle-{RUN_LABEL}-*.png")
    if not args.blind:
        log(f"  watching the arena {arena.COLS}x{arena.ROWS} either side of the river at "
            f"y {arena.RIVER}; a lane {arena.BUSY:.0%} busy is defended from slot(s) "
            f"{'/'.join(str(s) for s in arena.slots_for('left', LANES))} on the left, "
            f"{'/'.join(str(s) for s in arena.slots_for('right', LANES))} on the right")
    else:
        log("  --blind: not watching the arena, so no lane is ever read as under attack")

    controller = attach(args.title)
    controller.focus()
    vet_the_gestures(controller, book)
    log(controller.ensure_readable(allow_restart=False))
    shoot(controller, "start", longest=FRAME_LONGEST)

    # Taken before anything is tapped, and the only thing this run knows for certain about
    # what the game looks like. Every screen check in every match is measured against it.
    lobby = settled_lobby(controller)

    if args.navigate_only:
        navigate(controller)
        require_board(controller, lobby)
        shoot(controller, "board", longest=1400)
        log("navigate-only: on the board, nothing deployed, nothing dismissed")
        return

    played: list[Match] = []
    try:
        for number in range(1, args.matches + 1):
            played.append(one_match(controller, number, args, cadence, book, lobby))
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
                f"({total / attempts:.0%}) at {cadence:.2f}s per attempt, "
                f"{sum(m.holds for m in played)} passes held")
        log("the crowns above are the last tower reading of each match, which is not the "
            "scoreboard - read the battle-*-m*-end.png frames for that")


if __name__ == "__main__":
    main()
