"""Prove whether clicking `shuffle` actually shuffles, by watching three
independent regions instead of one.

The trap this exists to avoid: on the tutorial's first beat, a single click
anywhere bundles four changes together - the tutorial text advances, the deck
counter drops, a tile gets staged, and the board looks different. Read as a
whole that is indistinguishable from a shuffle, and I called it one twice.

So fingerprint the board, the deck counter and the tutorial text separately.
A real shuffle is board-only: the 3x3 rearranges while the counter and the
tutorial text hold still. Anything that moves all three is the tutorial
script, not the button.

Run: py experiments/game-screen-probe/shuffle_verify.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import probe  # noqa: E402
from probe import (  # noqa: E402
    BUTTON_FLAGS,
    client_rect_on_screen,
    color_signature,
    grab_thumbnail,
    mouse_input,
    mouse_move_to,
    send_input,
    set_dpi_aware,
    write_png,
)
from shuffle_run import assert_alive, find_game  # noqa: E402

OUT = Path("C:/Users/pmarj/AppData/Local/Temp/tt/verify")

SHUFFLE = (0.2000, 0.9097)
BOARD = (0.2415, 0.3939, 0.1155, 0.2033)
COUNTER = (0.6900, 0.8900, 0.0700, 0.0600)   # the number bottom-right
TUTORIAL = (0.3000, 0.1750, 0.2100, 0.0900)  # the dashed text box

hwnd = 0
rect = (0, 0, 0, 0)


def log(message: str) -> None:
    print(message, flush=True)


def restore(timeout: float = 8.0) -> None:
    global rect
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe.user32.ShowWindow(hwnd, probe.SW_RESTORE)
        probe.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if client_rect_on_screen(hwnd)[2] > 0:
            break
    time.sleep(0.5)
    rect = client_rect_on_screen(hwnd)


def at(fx: float, fy: float) -> tuple[int, int]:
    left, top, width, height = rect
    return left + int(width * fx), top + int(height * fy)


def region_px(region) -> tuple[int, int, int, int]:
    left, top, width, height = rect
    fx, fy, fw, fh = region
    return (left + int(width * fx), top + int(height * fy),
            max(1, int(width * fw)), max(1, int(height * fh)))


def cells_of(region, cols: int, rows: int, size: int = 40):
    """Per-sub-cell mean colour of a region. Splitting a region into a grid
    rather than taking one mean matters: two boards with the same tile counts
    in different positions have identical overall means."""
    rx, ry, rw, rh = region_px(region)
    cw, ch = rw // cols, rh // rows
    return [
        color_signature(grab_thumbnail(rx + c * cw, ry + r * ch, cw, ch, size, size), size, size, 0.15)
        for r in range(rows) for c in range(cols)
    ]


def changed(before, after, tolerance: float = 6.0) -> int:
    return sum(1 for b, a in zip(before, after)
               if any(abs(x - y) > tolerance for x, y in zip(b, a)))


def fingerprint() -> dict:
    return {
        "board": cells_of(BOARD, 3, 3),
        "counter": cells_of(COUNTER, 2, 2),
        "tutorial": cells_of(TUTORIAL, 6, 2),
    }


def snapshot(name: str, size: tuple[int, int] = (1280, 720)) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w, h = size
    write_png(str(OUT / f"{name}.png"), grab_thumbnail(*rect, w, h), w, h)


def click(point, hold: float = 0.08, hover: float = 0.25) -> None:
    mouse_move_to(*point)
    time.sleep(hover)
    down, up = BUTTON_FLAGS["left"]
    send_input(mouse_input(down))
    time.sleep(hold)
    send_input(mouse_input(up))


def main() -> None:
    global hwnd, rect
    set_dpi_aware()
    OUT.mkdir(parents=True, exist_ok=True)
    hwnd = find_game()
    if not hwnd:
        raise SystemExit("Tile Tale is not running.")
    restore()
    rect_local = rect
    # assert_alive reads shuffle_run's module-level rect, so mirror ours over.
    import shuffle_run
    shuffle_run.rect = rect_local
    assert_alive("startup")
    log(f"client: {rect[2]}x{rect[3]}\n")
    snapshot("00_before")

    log(f"{'attempt':>8}  {'board':>7}  {'counter':>9}  {'tutorial':>9}   verdict")
    for attempt in range(1, 6):
        restore()
        shuffle_run.rect = rect
        assert_alive(f"attempt {attempt}")
        before = fingerprint()
        click(at(*SHUFFLE))
        time.sleep(2.2)
        restore()
        after = fingerprint()

        board = changed(before["board"], after["board"])
        counter = changed(before["counter"], after["counter"])
        tutorial = changed(before["tutorial"], after["tutorial"])
        if board >= 2 and counter == 0 and tutorial == 0:
            verdict = "SHUFFLE (board only)"
        elif board == 0 and counter == 0 and tutorial == 0:
            verdict = "ignored"
        elif tutorial or counter:
            verdict = "tutorial/deck advanced - not a shuffle"
        else:
            verdict = "board moved slightly"
        log(f"{attempt:>8}  {board:>5}/9  {counter:>7}/4  {tutorial:>7}/12   {verdict}")
        snapshot(f"{attempt:02d}_after")
        time.sleep(0.5)

    log(f"\nimages: {OUT}")


if __name__ == "__main__":
    main()
