"""Attach to a game running inside the Google Play Games emulator, and refuse otherwise.

Why this exists rather than `targets.resolve`: a Play Games title has no executable to
resolve. Its Start-menu shortcut has a blank TargetPath - it starts through a shell URI -
so `controller.find_game` reports the game as not installed, and the whole discovery
path that every earlier target used is unavailable here.

What replaces it is deliberately narrower. Two facts are checked before anything is
driven, and both have to hold:

- exactly one unowned visible window carries the name, so the Chrome tab titled
  `Clash Royale - Google Play -sovellukset` cannot be mistaken for the game;
- that window's process is `crosvm.exe` inside the Play Games install, which is the
  emulator itself.

Both are then recorded on the Target as `owner_image`, because checking them once at
attach time guards the window this binds to and nothing afterwards. `successor_window`
re-decides what "the game" is on every readiness check, and with no exe to compare
against its only evidence is the title - which for a Play Games title is the game's own
name, and so is also the title of any editor or browser window with a file about the game
open. A VS Code window showing `clash-royale-wiki.html` was adopted on exactly that basis,
and an adopted window is one this harness sends drags into.

`Target.exe` is then left **empty on purpose**, and that is the most important line here.
The window's real owning process is the emulator, which hosts every Play Games title, so
it is not identity - it cannot tell this game from any other one. Worse, an `exe` is what
`Controller._launch` and `Controller._restart` start: pointed at `crosvm.exe` they would
run a bare virtual machine, and pointed at the client they would open a second copy of
the launcher. With no exe both paths raise `WindowLost` instead, which is the outcome
wanted - a session whose window dies should end, not reach for something to start.

The cost is honest: this cannot launch the game, so the game must already be open.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

import calibrate  # noqa: E402
from controller import (Controller, Target, WindowLost, _squash,  # noqa: E402
                        process_image, visible_windows, window_owner, window_pid)
from target import DENYLISTS  # noqa: E402

# The emulator process that owns the window a Play Games title is drawn in. Both halves
# are checked: the file name alone would match any `crosvm.exe` anywhere on the machine.
EMULATOR = "crosvm.exe"
INSTALL = Path(r"C:\Program Files\Google\Play Games")

# The measurements a calibration pass writes that a Target can carry. Kept as a tuple here
# rather than repeated at each call site, which is how three copies of this loop came to
# exist and a fourth caller came to have none.
CALIBRATED = ("startup_quiet", "screen_match", "cell_delta")


def candidates(needle: str) -> list[tuple[int, str, int]]:
    """Unowned visible windows whose title contains `needle`, as (hwnd, title, pid)."""
    found = []
    for hwnd, title in visible_windows().items():
        if window_owner(hwnd):
            continue
        if needle.lower() in title.lower():
            found.append((hwnd, title, window_pid(hwnd)))
    return found


def emulator_window(needle: str) -> tuple[int, str, int]:
    """The one Play Games window for this game, or raise saying what was rejected.

    Rejections are named rather than silently filtered. A window that carries the
    game's name and is not the game is the thing a person has to be told about - it is
    the failure that ends with input going somewhere nobody meant.
    """
    mine, strangers = [], []
    for hwnd, title, pid in candidates(needle):
        image = process_image(pid)
        if image is not None and image.name.lower() == EMULATOR and INSTALL in image.parents:
            mine.append((hwnd, title, pid))
        else:
            strangers.append((title, image))
    for title, image in strangers:
        print(f"  ignoring {title!r} - {image.name if image else 'unreadable process'}, "
              f"not the Play Games emulator")
    if not mine:
        raise WindowLost(
            f"no Play Games window named {needle!r} is open. This cannot launch the "
            f"game - open it from the Play Games client first.")
    if len(mine) > 1:
        raise WindowLost(f"{len(mine)} Play Games windows match {needle!r}: "
                         + ", ".join(repr(t) for _, t, _ in mine))
    return mine[0]


def attach(needle: str, verbose: bool = True) -> Controller:
    """A Controller already bound to the game's window. Sends no input."""
    hwnd, title, pid = emulator_window(needle)
    if verbose:
        print(f"attached to {title!r} (window {hwnd}, pid {pid})")

    # `owner_image` carries the same two-part check `emulator_window` just applied, so
    # that it keeps applying. Checking it only here would guard the window this attaches
    # to and nothing after: `successor_window` re-decides what the game is on every
    # readiness check, and with `exe` empty its only evidence is the title - which is the
    # game's own name, and therefore also the name of any editor or browser window with a
    # file about the game open. One of those was adopted, and adoption means input.
    target = Target(name=needle, window_title=title, exe="",
                    owner_image=(EMULATOR, str(INSTALL)),
                    denylist=DENYLISTS.get(_squash(needle), []))
    if verbose:
        forbidden = len(target.denylist)
        print(f"  denylist: {forbidden} box(es)" if forbidden else
              "  denylist: EMPTY - nothing is forbidden by coordinate for this game")

    controller = Controller(target, verbose=verbose)
    # Bound directly rather than through `start()`, which would fall through to a launch.
    controller.hwnd, controller.pid = hwnd, pid
    return controller


def apply_calibration(controller: Controller, game: str,
                      fields: tuple[str, ...] = CALIBRATED) -> dict[str, float]:
    """Overlay what a previous pass measured for this game. Returns what it changed.

    This has to be a separate call rather than something `attach` does, and the reason is
    worth stating because it looks like an oversight. `attach` builds its own `Target` instead
    of going through `targets.resolve`, so nothing loads the calibration file unless a caller
    asks - and three callers grew their own copy of this loop while a fourth had none, which
    is the trap `README.md` lists first: a script reading `controller.target.screen_match`
    after `attach` scores against the class default of 0.94 (tolerance 138 of 2304) while the
    measured value on disk is 0.974 (tolerance 59), a bar 2.3x looser than the recon gate.

    It is still not folded into `attach` itself. Doing that would tighten `screen_match` for
    every existing caller, and `wait_stable`/`_wait_settled` get *stricter* as it rises - so
    the animated lobby that already fails the readiness gate at 0.94 would fail harder. The
    seam is the fix; changing the default is a separate decision with its own measurement, and
    `run_recon.py --screen-match` exists because that decision has not been made.

    Returns the values it set, so a caller can report them in its own voice. An empty dict
    means there is no calibration for this game, which is a fact worth printing rather than a
    silent fall-through to defaults.
    """
    remembered = calibrate.load(game) or {}
    applied = {}
    for measured in fields:
        if measured in remembered:
            setattr(controller.target, measured, remembered[measured])
            applied[measured] = remembered[measured]
    return applied
