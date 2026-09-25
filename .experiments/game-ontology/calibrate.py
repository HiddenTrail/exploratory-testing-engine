"""Producing the per-game numbers instead of paying for them.

Two numbers decide whether a recon session works at all, and both used to be typed
into `target.py` by a person who had watched the game:

- `startup_quiet` - how long the window must hold still before the game is believed
  to have finished starting. Too small and the splash-to-menu change lands on its own
  and is attributed to whatever key was in flight, which writes a false edge into the
  graph. Too large and every launch and every recovery pays for it.
- `screen_match` - how much of a frame must agree for two frames to be the same place.
  Too tight and every highlight move invents a screen; too loose and one screen
  absorbs its neighbours.

The claim this experiment is testing is that both can be *measured*, so here they are
measured. `startup_quiet` comes from watching a cold launch and taking the longest gap
between transients - not the total startup time, because the wait resets its clock on
every change and so only has to outlast the quietest moment *inside* startup. That
distinction is the whole reason the number can be small: a game measured here shows a
splash holding perfectly still for 2.8s before its menu arrives, and anything under
that settles on the splash and blames the first keypress for the menu.

`screen_match` comes from the previous pass's own transitions. A pass records, for
every action, how many cells changed; the same-place moves and the went-somewhere-else
moves are two populations, and the threshold belongs between them. Nothing about the
game is assumed - if a pass never left its first screen there is nothing to cut with
and the number is left alone, which is honest rather than a guess dressed as a
measurement.

Written to `calibration/<game>.json` as data, not code. It is committed, because a
measurement someone's machine made is worth keeping, and `out/` is ignored.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from controller import (
    FLAT_VARIANCE,
    READY_COLS,
    READY_ROWS,
    Controller,
    _squash,
    changed_cells,
    is_foreground,
    log,
    variance,
)

HOME = Path(__file__).parent / "calibration"

# --- startup ----------------------------------------------------------------

# Resolution of the churn timeline. Fine enough to separate a splash from a menu,
# coarse enough that the sampling itself is not most of the work.
SAMPLE_GAP = 0.25
# Quiet needed before startup is believed over. Necessarily longer than the answer
# being looked for: the thing being measured is the longest still moment *inside*
# startup, so the proof of the end has to outlast it, or the measurement stops at the
# first splash and reports its own impatience as a result.
STARTUP_PROOF = 9.0
# Total time to watch. A game that has not finished starting by now is telling us
# something the default handles better than a number cut from a truncated timeline.
STARTUP_HORIZON = 40.0
# Added to the longest interior gap. One sample of slack plus a margin for a launch
# that is slower on a cold disk than it was when measured.
STARTUP_MARGIN = 1.5
STARTUP_FLOOR = 2.0
# The readiness loop's own grid, imported rather than restated, so that "moved" means
# the same thing to the measurement and to the wait it is measuring for.
WATCH_COLS, WATCH_ROWS = READY_COLS, READY_ROWS


def measure_startup(controller: Controller, screen_match: float) -> dict:
    """Watch a cold launch and derive `startup_quiet` from what it does.

    Expects a window that exists but has *not* been waited for - see
    `Controller.attach_or_launch`. Waiting first would use the number being measured
    to measure itself.

    Returns the derived value alongside the timeline it came from, because a number
    with no timeline behind it cannot be argued with, and this one is a judgement about
    a game nobody has watched."""
    tolerance = int((1.0 - screen_match) * WATCH_COLS * WATCH_ROWS)
    started = time.monotonic()
    events: list[float] = []          # when the window changed, since launch
    previous: bytes | None = None
    last_change = 0.0
    rescues = 0

    while time.monotonic() - started < STARTUP_HORIZON:
        now = time.monotonic() - started
        # Not being visible yet is itself churn: a fullscreen game minimizes itself the
        # instant it loses focus during startup, and calling that stillness would end
        # the measurement on a window that has not drawn anything.
        if controller.rect[2] == 0 or not is_foreground(controller.hwnd):
            rescues += 1
            controller.focus(timeout=2.0)
            previous, last_change = None, now
            continue

        frame = controller.grab(WATCH_COLS, WATCH_ROWS, verify=False)
        if variance(frame) < FLAT_VARIANCE:
            previous, last_change = None, now       # a flat fill is not a screen yet
        elif previous is not None:
            if changed_cells(previous, frame, controller.target.cell_delta) > tolerance:
                events.append(round(now, 2))
                last_change = now
        previous = frame

        if now - last_change >= STARTUP_PROOF:
            break
        time.sleep(SAMPLE_GAP)

    watched = time.monotonic() - started
    settled = bool(events) and watched - last_change >= STARTUP_PROOF
    # The gaps *between* transients, plus the gap from the last one to the moment
    # things went quiet - a startup whose only pause is at the end still has to be
    # outlasted.
    gaps = [b - a for a, b in zip(events, events[1:])]
    longest = max(gaps, default=0.0)
    quiet = max(STARTUP_FLOOR, round(longest + STARTUP_MARGIN, 1))

    result = {
        "startup_quiet": quiet,
        "watched_seconds": round(watched, 1),
        "change_at": events,
        "longest_interior_gap": round(longest, 2),
        "settled": settled,
        "restores_needed": rescues,
    }
    if not settled:
        # Reported rather than acted on. A window that never goes quiet is not a
        # measurement problem, and cutting a number from a timeline that never ended
        # would present impatience as evidence.
        result["startup_quiet"] = controller.target.startup_quiet
        result["why"] = (f"never quiet for {STARTUP_PROOF:.0f}s within "
                         f"{STARTUP_HORIZON:.0f}s, so the default was kept")
    log(f"  startup: {len(events)} changes over {watched:.1f}s"
        + (f" (at {', '.join(f'{e:.1f}s' for e in events[:8])}"
           + (" ..." if len(events) > 8 else "") + ")" if events else "")
        + f"; longest still moment inside startup {longest:.1f}s"
        + f" -> startup_quiet {result['startup_quiet']}s"
        + ("" if settled else " (kept the default: it never went quiet)"))
    return result


# --- screen identity --------------------------------------------------------

# Bounds on the recut. Below the floor a screen has to reproduce so little of itself
# that anything matches anything; above the ceiling nothing survives a single frame of
# animation. Both are properties of the measure, not of any game.
MATCH_FLOOR, MATCH_CEILING = 0.80, 0.99
# Cells of slack past the widest same-place move seen. A pass sees the widest move it
# happened to make, not the widest one that exists, and a threshold cut exactly at the
# observed maximum splits the first slightly wider one into a screen of its own.
SLACK_CELLS = 2


def recut_screen_match(ontology: dict) -> dict:
    """Re-derive `screen_match` from a pass's own recorded transitions.

    The two populations are the transitions a pass labelled `variant` (the same place,
    a different appearance) and `screen` (somewhere else). Their changed-cell counts
    bracket the threshold: it must be loose enough to keep the widest same-place move
    together and tight enough to let the smallest screen change through.

    Note what is circular here and why it is not fatal: those labels were assigned
    *by* the threshold being recut. What breaks the circle is the model - a `screen`
    edge that the geometry had merged only exists because a vetting call contradicted
    it, and those splits are exactly the evidence that the old number was too loose.
    A pass whose populations overlap is the one to be careful with, so when they abut
    the widest same-place move is admitted rather than split: leaving two screens
    merged is what the previous pass already did, while splitting a screen that does
    not exist invents structure and every later pass inherits it."""
    ncells = (ontology.get("session", {}).get("grid") or [32, 18])
    ncells = ncells[0] * ncells[1]
    same = [t["changed_cells"] for t in ontology["transitions"] if t["effect"] == "variant"]
    # A screen change of zero cells is not evidence about any threshold: the picture did
    # not move, so nothing travelled anywhere, and one of them drags `smallest` to 0 and
    # makes every game look like a game whose geometry cannot tell its screens apart.
    # `Recon._record` no longer produces these, but a resumed map carries whatever an
    # earlier pass recorded, and a single such edge from pass 1 would otherwise govern
    # every recut for the rest of the sweep.
    other = [t["changed_cells"] for t in ontology["transitions"]
             if t["effect"] == "screen" and t["changed_cells"] > 0]
    current = ontology["session"]["screen_match_threshold"]

    if not same or not other:
        missing = "same-place moves" if not same else "screen changes"
        return {"screen_match": current, "kept": True,
                "why": f"this pass recorded no {missing}, so there is nothing to cut between"}

    widest, smallest = max(same), min(other)
    # Expressed as the fraction of cells that must still agree, which is what
    # `agreement` compares against. Measured against a whole frame, while `agreement`
    # judges only the stable cells, so a real score is always at least this generous -
    # the cut errs toward "the same place", which is the cheap direction.
    #
    # The cut sits at the *tight* end of the admissible range - as demanding as it can
    # be while still holding the widest same-place move together - and not in the
    # middle of the gap between the populations. The gap is not evidence about where
    # the boundary is, and a game whose screens differ wildly has a huge one: Mitosis
    # brackets [0.44, 0.90] and the midpoint of that, 0.67, is a threshold under which
    # a frame need only reproduce two thirds of a screen to be filed as it. The two
    # errors are not comparable. Too tight invents a screen per highlight move, which
    # is a cluttered map; too loose lets one screen absorb its neighbours, and then its
    # volatile mask grows over the cells that would have told them apart and no later
    # pass can undo it.
    loosest = 1.0 - (widest + SLACK_CELLS) / ncells   # holds same-place moves together
    tightest = 1.0 - smallest / ncells                # lets screen changes through
    overlap = loosest <= tightest
    value = round(min(MATCH_CEILING, max(MATCH_FLOOR, loosest)), 3)
    return {
        "screen_match": value,
        "kept": False,
        "widest_same_place": widest,
        "smallest_screen_change": smallest,
        "cells": ncells,
        "populations_overlap": overlap,
        "admissible_range": [round(max(0.0, tightest), 3), round(loosest, 3)],
        "why": (f"the widest same-place move changed {widest} of {ncells} cells and the "
                f"smallest screen change {smallest}"
                + (", which overlap - no threshold separates them, so this game's "
                   "screens are told apart by the model's naming and not by geometry"
                   if overlap else "")),
    }


# --- the file ---------------------------------------------------------------

def path(game: str) -> Path:
    return HOME / f"{_squash(game)}.json"


def load(game: str) -> dict:
    """What a previous pass measured, or nothing. Missing is the normal case for a game
    this has never been pointed at, and the caller's job is to measure rather than to
    fail."""
    file = path(game)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log(f"  ignoring unreadable calibration {file.name}: {error}")
        return {}


def save(game: str, data: dict) -> Path:
    file = path(game)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return file
