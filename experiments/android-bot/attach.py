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

from controller import (Controller, Target, WindowLost, _squash,  # noqa: E402
                        process_image, visible_windows, window_owner, window_pid)
from target import DENYLISTS  # noqa: E402

# The emulator process that owns the window a Play Games title is drawn in. Both halves
# are checked: the file name alone would match any `crosvm.exe` anywhere on the machine.
EMULATOR = "crosvm.exe"
INSTALL = Path(r"C:\Program Files\Google\Play Games")


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

    target = Target(name=needle, window_title=title, exe="",
                    denylist=DENYLISTS.get(_squash(needle), []))
    if verbose:
        forbidden = len(target.denylist)
        print(f"  denylist: {forbidden} box(es)" if forbidden else
              "  denylist: EMPTY - nothing is forbidden by coordinate for this game")

    controller = Controller(target, verbose=verbose)
    # Bound directly rather than through `start()`, which would fall through to a launch.
    controller.hwnd, controller.pid = hwnd, pid
    return controller
