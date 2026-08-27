"""Targets: the only file in this experiment that may name a game.

It used to be a registry, and a registry was the thing that made "point this at a
game it has never seen" untrue. Adding a game meant writing down its window title,
its executable, how long it takes to start and how much of a frame has to agree for
two frames to be one screen - four facts, three of them measurable, and every one of
them a reason a new game could not simply be run. Those are now produced: the
executable is found from the game's name (`controller.find_game`), the window title
is whatever the launch turned out to open, and the two numbers are measured and written
back by `calibrate.py`.

What is left here is the part measurement cannot produce: a safety rule a person
decided. `DENYLISTS` is the hard floor, enforced inside `Controller.click` so no policy
above it can route around it. It is keyed loosely by name and it is empty for a game
nobody has watched yet - which is honest rather than convenient, and it is why the
other two safety layers exist. An unmapped game is protected by modality gating and by
the vetting call that reads a screen before anything may be committed on it; a denylist
can only be written *after* a session has found the control that deserves one, and its
coordinates are the one thing a report cannot re-cut on its own.

Explicitly *not* here, and never: what a game's screens are, where its buttons live, or
what any input does. Those are the output. Putting a board rectangle in this file would
make a recon session grade its own homework.
"""

from __future__ import annotations

from controller import Target, _squash, find_game, log

# Fractional boxes that must never be clicked, per game, because someone looked at the
# game and decided. Keyed on the squashed name discovery settled on (see `_squash` and
# `find_game`) - a Steam directory or a Start-menu shortcut - so "Tile Tale" and
# "tile_tale" find the same entry.
#
# Fractions rather than pixels because a fullscreen game picks its resolution at launch
# and a coordinate in pixels is wrong the first time it picks a different one.
DENYLISTS: dict[str, list[dict]] = {
    "tiletale": [
        {
            "box": (0.86, 0.87, 0.10, 0.09),
            "why": "the lower-right exit icon - two clicks here quit the game, "
                   "which ends the session and forfeits the rest of its budget",
        },
    ],
}


def resolve(game: str, calibration: dict | None = None) -> Target:
    """A Target for a game named the way a person would name it.

    Everything about the game itself is discovered; everything remembered is passed in
    through `calibration`, which is a file written by a previous session and not code.
    The alternatives the executable was chosen over are logged, because that choice is
    a guess and a guess nobody can see is a guess nobody can correct."""
    name, exe, runners_up = find_game(game)
    # Relative to the executable's own folder, not to an install root: a game found
    # through the Start menu has no install root to be relative to, and the folder is
    # what the names need to be read against either way.
    log(f"{name}: {exe.name} in {exe.parent}"
        + (f" (over {', '.join(p.name for p in runners_up)})" if runners_up else ""))

    remembered = calibration or {}
    target = Target(name=name, exe=str(exe),
                    window_title=remembered.get("window_title", ""),
                    denylist=DENYLISTS.get(_squash(name), []))
    for measured in ("startup_quiet", "screen_match", "cell_delta"):
        if measured in remembered:
            setattr(target, measured, remembered[measured])
    if remembered:
        log(f"  calibration: startup_quiet {target.startup_quiet}s, "
            f"screen_match {target.screen_match}"
            + (f", re-attaching to {target.window_title!r}" if target.window_title else ""))
    else:
        log(f"  no calibration for this game yet; measuring it this pass")
    if not target.denylist:
        log("  no coordinate denylist: nothing has been forbidden by hand for this "
            "game, so safety rests on modality gating and vetting")
    return target


# Handed to the model on every vetting call. Phrased as categories rather than as a
# list of specific labels because the explorer meets screens nobody has seen, and a
# rule that only recognizes the wording someone thought of in advance is not a rule.
#
# The asymmetry is deliberate and stated to the model directly: a control wrongly
# called dangerous costs one unexplored branch, while a control wrongly called safe
# can cost the session and destroy save data. Those are not comparable, so the
# instruction is to resolve uncertainty toward "dangerous" rather than to be
# accurate on average.
SAFETY_BRIEF = """\
Treat an action as DANGEROUS if it could plausibly do any of:

- quit, exit, or close the game
- reset, erase, wipe, restart or overwrite progress, a save, a profile, or any other
  state the game has recorded about the player
- spend real money, or reach anything outside the game (a store, a browser, a link)
- confirm a dialog whose consequence you cannot read

Treat an action as SAFE only when you can see what it does and it is reversible:
moving a highlight, opening a screen that has a visible way back, toggling a
setting you could toggle again.

When you are unsure, it is dangerous. The costs are not symmetrical: calling a safe
control dangerous loses one branch of exploration, while calling a dangerous control
safe can end the session and destroy data that cannot be recovered. Do not try to be
right on average - try to never be wrong in the expensive direction.
"""
