"""Play one Training Camp match: deploy cards on a timer until the clock runs out.

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

**Why only two of the four card slots.** The four cards sit in a row at the bottom of the
arena; the deploy gesture drags one up into the player's own half. Two of those four drags
are refused, and by the guard rather than by anything here - `Controller.drag` checks the
whole path, and the Battle button's denylist box (x 0.32-0.69, y 0.72-0.84) lies directly
between the middle two card slots and the board. Slots 1 and 4 clear it, one down each
side; slots 2 and 3 cannot leave the panel without crossing it, whatever they are aimed at.

That could have been an override - the box describes a control on the *main* screen, and
during a match those coordinates are grass. It is not one, because it does not have to be:
a played card is replaced in the slot it left, so slots 1 and 4 still turn over the whole
deck, just two cards at a time instead of four. What it costs is real and worth stating -
the push is split across both lanes rather than concentrated on one, which is weaker play
than a person would make - but it is bought with a worse attack, not with a hole in the
one guard that stands between this file and every other button in the game.

**How it knows there is a match at all.** By measurement, and this is the lesson of the
first run rather than a design instinct. That run sent its three taps into a window that
was not in front, opened nothing, and then deployed sixty-one gestures at the main screen -
which cost nothing, changed nothing, and looked exactly like a successful pass in the log.
So one frame is photographed before anything is tapped, and the same comparison against it
answers both questions worth asking: the board must *not* look like that frame before a
single gesture is sent, and when it looks like it again the match is over. A change test,
not a content test - "is there a magenta elixir bar here" is a claim about a bar, and one
more thing to be wrong about; "is this still the picture I took a moment ago" needs nothing
to be true about the game. The timer is the backstop, not the plan, and the screen a match
leaves behind is dismissed by hand, by whoever reads the last picture.

Run:  python experiments/android-bot/battle.py --allow-battle
      python experiments/android-bot/battle.py --allow-battle --seconds 60 --navigate-only
"""

from __future__ import annotations

import argparse
import sys
import time
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

# --- the two gestures --------------------------------------------------------
# Card slots along the bottom, and the point on this side of each bridge to drop them at.
# The pairing is not a choice: slot 1 is the left half of the panel and slot 4 the right,
# so each reaches its own side's bridge without the path sweeping across the board.
DEPLOY = (
    ((0.310, 0.873), (0.235, 0.470)),   # slot 1 -> this side of the left bridge
    ((0.858, 0.873), (0.760, 0.470)),   # slot 4 -> this side of the right bridge
)
CADENCE = 2.5       # seconds between deploy attempts. Elixir refills at one per 2.8s and
                    # the cards cost three to five, so most attempts cannot be paid for -
                    # which is the point. An unaffordable card does not deploy and costs
                    # nothing, so the cheapest correct elixir policy is to keep asking.
FRAME_EVERY = 30.0  # seconds between pictures. The record of what the match looked like,
                    # kept small: the PNG encoder is a Python loop over every pixel, and
                    # a full-resolution frame every half minute would spend more of the
                    # match encoding than playing.
FRAME_LONGEST = 800


def shoot(controller, name: str, longest: int = FRAME_LONGEST) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"battle-{name}.png"
    width, height = controller.write_capture(path, controller.capture(longest=longest))
    log(f"  wrote {path.name} ({width}x{height})")
    return path


def vet_the_gestures(controller) -> None:
    """Refuse to start unless every gesture this file can send is clear of every box.

    Checked here, once, against the same `forbids`/`forbids_path` the send goes through,
    so a denylist that grows a box across one of these paths stops the run at the top
    rather than raising `PermissionError` out of the middle of a live match. The two
    gestures are constants: if they pass here they pass every time they are sent.
    """
    for point, what in ((MENU, "the menu"), (TRAINING_CAMP, "the Training Camp item"),
                        (CONFIRM, "the confirm button")):
        why = controller.target.forbids(*point)
        if why:
            raise SystemExit(f"REFUSED before starting: {what} at {point} is denylisted "
                             f"- {why}")
    for slot, (start, end) in enumerate(DEPLOY, start=1):
        why = (controller.target.forbids(*start) or controller.target.forbids(*end)
               or controller.target.forbids_path(start, end))
        if why:
            raise SystemExit(f"REFUSED before starting: the deploy gesture {start} -> "
                             f"{end} is denylisted - {why}")
        log(f"  deploy {slot}: {start} -> {end}, clear of all "
            f"{len(controller.target.denylist)} boxes including the path between them")


def looks_like(controller, reference: bytes) -> float:
    """How much of the window still agrees with `reference`, as a fraction of cells.

    One measurement, asked twice for opposite reasons. Before playing: the board must
    *not* agree with the main screen the run started on, or the way in did not work.
    While playing: when it agrees again, the match is over and the main screen is back.

    A change test rather than a content test, and deliberately - "is there a magenta
    elixir bar at these coordinates" is a claim about a bar, breakable by a layout that
    moves it, and wrong in both directions when it breaks. "Is this still the picture I
    photographed a moment ago" needs nothing to be true about the game at all.
    """
    cells = GRID_COLS * GRID_ROWS
    now = controller.grab(GRID_COLS, GRID_ROWS)
    moved = changed_cells(reference, now, controller.target.cell_delta)
    return 1.0 - moved / cells


def navigate(controller, reference: bytes) -> None:
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
        shoot(controller, f"{name}-before", longest=700)
        if not is_foreground(controller.hwnd):
            log("  window is not in front - focusing before tapping")
            controller.focus()
        log(f"  tapping {name} at ({point[0]:.3f}, {point[1]:.3f})")
        controller.click(*point)
        time.sleep(1.2)
    shoot(controller, "confirm-after", longest=700)
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
    log(f"  the window agrees with the main screen it started on by {agreement:.3f} "
        f"(under {SAME_SCREEN} means the way in worked)")
    if agreement >= SAME_SCREEN:
        shoot(controller, "no-board", longest=1400)
        raise SystemExit(
            "REFUSED to play: the window still looks like the screen this started on, so "
            "the way in to Training Camp did not work and there is no board to play on. "
            "Nothing was deployed. Read battle-no-board.png and check the three "
            "coordinates at the top of this file against it.")


def play(controller, seconds: float, reference: bytes) -> int:
    """Alternate the two deploy gestures until the match ends or `seconds` are up.

    Returns the count sent. Two ways to stop, and the timer is the second of them: the
    match ends by itself, and what it leaves behind eventually returns to the screen this
    run started on - which `reference` is a picture of. Checked on the same beat as the
    frames rather than every gesture, because it costs a capture and the answer cannot
    change between two gestures three seconds apart in a way that matters.

    The window is re-focused whenever it is not in front, because input here is sent to
    wherever the pointer is rather than to a window handle: a match played into a window
    that lost focus is input sent at somebody else's application.
    """
    started = time.monotonic()
    next_check = FRAME_EVERY
    sent = 0
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= seconds:
            log(f"  {seconds:.0f}s up after {sent} deploy attempts")
            return sent
        if not is_foreground(controller.hwnd):
            log("  window is not in front - focusing before sending anything")
            controller.focus()
        start, end = DEPLOY[sent % len(DEPLOY)]
        controller.drag(start, end)
        sent += 1
        log(f"  [{elapsed:5.1f}s] deploy {sent}: ({start[0]:.3f}, {start[1]:.3f}) -> "
            f"({end[0]:.3f}, {end[1]:.3f})")
        if elapsed >= next_check:
            shoot(controller, f"t{int(elapsed):03d}")
            agreement = looks_like(controller, reference)
            if agreement >= SAME_SCREEN:
                log(f"  [{elapsed:5.1f}s] back on the screen this started on "
                    f"(agreement {agreement:.3f}) - the match is over, stopping after "
                    f"{sent} deploy attempts")
                return sent
            next_check += FRAME_EVERY
        time.sleep(CADENCE)


def main() -> None:
    readable_output()
    set_dpi_aware()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--title", default="Clash Royale")
    parser.add_argument("--seconds", type=float, default=185.0,
                        help="how long to keep deploying. A match is three minutes; the "
                             "default overruns it deliberately, because stopping early "
                             "leaves the last half-minute unplayed and stopping late "
                             "sends drags at a result screen that ignores them")
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

    controller = attach(args.title)
    controller.focus()
    vet_the_gestures(controller)
    log(controller.ensure_readable(allow_restart=False))

    shoot(controller, "start", longest=700)
    # Taken before anything is tapped, and the only thing this run knows for certain
    # about what the game looks like. Everything after this is measured against it.
    reference = controller.grab(GRID_COLS, GRID_ROWS)
    navigate(controller, reference)
    require_board(controller, reference)
    if args.navigate_only:
        shoot(controller, "board")
        log("navigate-only: on the board, nothing deployed")
        return

    sent = 0
    try:
        sent = play(controller, args.seconds, reference)
    except KeyboardInterrupt:
        log("\ninterrupted mid-match")
    finally:
        shoot(controller, "end", longest=1400)
        log(f"{sent} deploy attempts sent; left the game open on whatever the match "
            f"left behind - read battle-end.png and dismiss it with drive.py")


if __name__ == "__main__":
    main()
