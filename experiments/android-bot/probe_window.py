"""Read-only probe: is the Play Games game window something the harness can drive?

Nothing here clicks, types, launches or closes. It attaches to a window that is
already open, says what it found, and writes one PNG - which is the whole question
being asked. The Play Games emulator draws the game inside a window it owns and
decorates, so "the client area is the game" is a claim to be photographed rather
than assumed: any Play Games chrome caught inside the client rect would be mapped
as if it were part of the game.

Run from anywhere:  python experiments/android-bot/probe_window.py [title]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import (Controller, Target, process_image, readable_output,  # noqa: E402
                        set_dpi_aware, visible_windows, window_owner, window_pid)

DEFAULT_TITLE = "Clash Royale"
OUT = Path(__file__).resolve().parent / "out"


def matches(needle: str) -> list[tuple[int, str]]:
    """Every unowned visible window whose title contains `needle`.

    Owned windows are skipped for the same reason `Controller.running_window`
    skips them: those are dialogs belonging to something else. All matches are
    returned rather than the first, because "which of these is the game" is
    exactly what this probe exists to answer, and a probe that silently picked
    one would be hiding the ambiguity it was run to expose.
    """
    found = []
    for hwnd, title in visible_windows().items():
        if window_owner(hwnd):
            continue
        if needle.lower() in title.lower():
            found.append((hwnd, title))
    return found


def main() -> None:
    # Before any print: window titles are not ASCII either. A Play Games window title
    # carries a non-breaking hyphen, and cp1252 stdout raised on it rather than
    # dropping it, which killed this probe on its first run.
    readable_output()
    # And before any coordinate is read. This machine runs at 125% scaling, and an
    # unaware process is handed logical coordinates while the capture blits physical
    # ones: the first run of this probe reported a plausible 560x996 client area and
    # photographed a Chrome window sitting elsewhere on the desktop. Silent, and
    # wrong in the direction that looks like success.
    set_dpi_aware()
    needle = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TITLE
    found = matches(needle)
    if not found:
        print(f"no visible window with {needle!r} in its title; is the game open?")
        raise SystemExit(1)
    for hwnd, title in found:
        pid = window_pid(hwnd)
        image = process_image(pid)
        print(f"window {hwnd} {title!r}")
        print(f"  pid {pid}, image {image}")

    hwnd, title = found[0]
    if len(found) > 1:
        print(f"\n{len(found)} candidates; probing the first")

    # exe deliberately empty: the Start-menu shortcut for a Play Games title has no
    # filesystem target at all (TargetPath is blank - it launches through a shell
    # URI), so there is no executable to resolve and the title is the only evidence
    # available. Target with no exe is the honest description of that.
    target = Target(name=needle, window_title=title, exe="")
    controller = Controller(target)
    controller.hwnd, controller.pid = hwnd, window_pid(hwnd)

    left, top, width, height = controller.rect
    print(f"\nclient area {width}x{height} at ({left}, {top})")
    if width == 0 or height == 0:
        print("  client rect is empty - the window is minimized; restore it and re-run")
        raise SystemExit(1)

    # Foregrounding is not optional and not incidental: the capture is a GDI blit of
    # a screen rectangle, so anything overlapping the window is what gets
    # photographed. This is the one thing the probe does to the machine, and it
    # sends no input.
    if not controller.focus():
        print("  could not bring the window to the foreground; the capture may show "
              "whatever is on top of it")

    OUT.mkdir(parents=True, exist_ok=True)
    shot = OUT / "probe-client-area.png"
    w, h = controller.save_png(shot)
    print(f"wrote {shot} ({w}x{h})")


if __name__ == "__main__":
    main()
