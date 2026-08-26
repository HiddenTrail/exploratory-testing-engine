"""Target definitions: the only file in this experiment that may name a game.

Everything here is either something the operating system needs (what to launch,
what the window is called) or a safety rule someone had to decide (what must never
be clicked). Explicitly *not* here: anything about how the game works, what its
screens are, or where its buttons live. Those are the experiment's output. Putting
a board rectangle in this file would make the recon session grade its own homework.

The denylist is the hard floor, checked inside `Controller.click` so no policy above
it can route around it. It exists because exploration is not free: a session runs
unattended and an explorer that pokes at an unmapped UI will eventually find the
control that ends the run, and by then it has taken the whole remaining budget with
it. Coordinates are fractions of the client area, which is what makes them survive
the resolution change a fullscreen game performs on every launch.

What a coordinate denylist cannot protect is a keyboard-driven menu, where the
dangerous action is `enter` on a row whose position is not known in advance. That
gap is closed in `recon.py` by the vetting pass, which reads each new screen before
the explorer is allowed to commit to anything on it - see `SAFETY_BRIEF`.
"""

from __future__ import annotations

from controller import Target

TARGETS: dict[str, dict] = {
    "tile-tale": {
        "window_title": "Tile Tale",
        "install_dir": "Tile Tale",
        "exe_name": "tile_tale.exe",
        "denylist": [
            {
                "box": (0.86, 0.87, 0.10, 0.09),
                "why": "the lower-right exit icon - two clicks here quit the game, "
                       "which ends the session and forfeits the rest of its budget",
            },
        ],
        # Measured, not guessed: this game opens windowed 1280x720 and switches to
        # fullscreen 3840x2160 about 3.3s later. Anything under that returns a rect
        # the game is about to discard.
        "startup_quiet": 4.0,
        # Also measured, from sessions' own transitions - and the measurement says no
        # value is right. "Same place, different appearance" ran 11 to 41 changed cells
        # of 576 (main menu highlight 11, hover 16, settings menu highlight 41) while
        # "different place" ran 42 to 89 (main menu -> settings 42, settings -> the
        # board 89). The populations abut at 42/41, so a threshold cut anywhere either
        # files the settings menu as the main menu or files each settings row as its
        # own screen. Both happened. So this is cut loose enough to admit the widest
        # same-place move (41 cells, 0.929) and the naming disagreement separates what
        # that also lets in - see `Recon.split_screen`.
        "screen_match": 0.92,
    },
}


def load(name: str | None = None) -> Target:
    name = name or default_name()
    if name not in TARGETS:
        raise SystemExit(f"unknown target {name!r}; known: {', '.join(sorted(TARGETS))}")
    return Target(name=name, **TARGETS[name])


def default_name() -> str:
    """The target to use when the command line does not say.

    Resolved from the registry rather than written as a default in each script's
    argparse: a literal there would put a game's name in two general-purpose modules
    to save one word of typing."""
    if len(TARGETS) == 1:
        return next(iter(TARGETS))
    raise SystemExit(f"--target is required; known: {', '.join(sorted(TARGETS))}")


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
