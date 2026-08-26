"""Run a short script of actions against the live game, capturing as it goes.

Each shell invocation costs a permission prompt, and answering one takes focus
off a fullscreen-exclusive game - which minimizes it. So instead of one call
per input, this takes a whole sequence and replays it in one process:

    py play.py snap:00 key:enter wait:2 snap:01 click:0.34,0.34 wait:1.5 snap:02

Actions (all coordinates are fractions of the client area):
    snap:NAME[@WxH]   write a PNG
    click:FX,FY       move, hover, press, hold, release
    move:FX,FY        move the cursor only
    key:NAME          press and release (space enter esc tab left up right down)
    char:C            press and release a single character key
    wait:SECONDS      sleep
    watch:SECONDS     report motion frames over that window
    restore           re-raise the window (done automatically before each action
                      that needs focus, but useful to force a settle)

Never has an "exit" action, and never clicks the bottom-right exit icon: that
quits the game outright, after which every capture reads a dead window and
looks exactly like "the input did nothing".
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
    diff_cells,
    grab_thumbnail,
    key_input,
    mouse_input,
    mouse_move_to,
    send_input,
    set_dpi_aware,
    write_png,
)

OUT = Path("C:/Users/pmarj/AppData/Local/Temp/tt/play")

hwnd = 0
rect = (0, 0, 0, 0)


def log(message: str) -> None:
    print(message, flush=True)


def find_game() -> int:
    found = []

    @probe.WNDENUMPROC
    def callback(handle, _lparam):
        if not probe.user32.IsWindowVisible(handle):
            return True
        length = probe.user32.GetWindowTextLengthW(handle)
        if not length:
            return True
        buf = probe.ctypes.create_unicode_buffer(length + 1)
        probe.user32.GetWindowTextW(handle, buf, length + 1)
        if "tile tale" in buf.value.lower():
            found.append(handle)
            return False
        return True

    probe.user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def restore(timeout: float = 8.0) -> None:
    global rect
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe.user32.ShowWindow(hwnd, probe.SW_RESTORE)
        probe.user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        if client_rect_on_screen(hwnd)[2] > 0:
            break
    time.sleep(0.4)
    rect = client_rect_on_screen(hwnd)
    if rect[2] <= 0:
        raise SystemExit("client rect is empty - the game is gone.")


def at(fx: float, fy: float) -> tuple[int, int]:
    left, top, width, height = rect
    return left + int(width * fx), top + int(height * fy)


def snap(name: str, size: tuple[int, int] = (1280, 720)) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w, h = size
    write_png(str(OUT / f"{name}.png"), grab_thumbnail(*rect, w, h), w, h)
    log(f"  snap {name} ({w}x{h})")


def crop(name: str, fx: float, fy: float, fw: float, fh: float, longest: int = 600) -> None:
    """Save one region at native-ish resolution.

    Snapping the whole 4K client down to 1280x720 shrinks a board tile to ~50px,
    which is enough to see that a tile changed but not always enough to tell
    which *kind* it changed to - and the whole game turns on that distinction.
    A region crop keeps the detail without paying the pure-Python PNG writer
    for four million pixels."""
    OUT.mkdir(parents=True, exist_ok=True)
    left, top, width, height = rect
    rx, ry = left + int(width * fx), top + int(height * fy)
    rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
    scale = min(1.0, longest / max(rw, rh))
    ow, oh = max(1, int(rw * scale)), max(1, int(rh * scale))
    write_png(str(OUT / f"{name}.png"), grab_thumbnail(rx, ry, rw, rh, ow, oh), ow, oh)
    log(f"  crop {name} ({ow}x{oh} of {rw}x{rh} at {rx},{ry})")


def click(fx: float, fy: float, hold: float = 0.08, hover: float = 0.25) -> None:
    point = at(fx, fy)
    mouse_move_to(*point)
    time.sleep(hover)
    down, up = BUTTON_FLAGS["left"]
    send_input(mouse_input(down))
    time.sleep(hold)
    send_input(mouse_input(up))
    log(f"  click {fx:.4f},{fy:.4f} -> {point}")


def press(name: str) -> None:
    vk = probe.VK_NAMES[name] if name in probe.VK_NAMES else ord(name.upper())
    send_input(key_input(vk, keyup=False))
    time.sleep(0.06)
    send_input(key_input(vk, keyup=True))
    log(f"  key {name}")


def watch(seconds: float, threshold: int = 6) -> None:
    tw, th = 64, 36
    previous = grab_thumbnail(*rect, tw, th)
    started, moving, peak = time.monotonic(), 0, 0
    while time.monotonic() - started < seconds:
        time.sleep(0.1)
        current = grab_thumbnail(*rect, tw, th)
        moved = diff_cells(previous, current, tw, th, threshold)
        if moved:
            moving += 1
            peak = max(peak, max(m[2] for m in moved))
        previous = current
    log(f"  watch {seconds}s -> {moving} moving frames, peak {peak}")


def main() -> None:
    global hwnd
    set_dpi_aware()
    hwnd = find_game()
    if not hwnd:
        raise SystemExit("Tile Tale is not running.")
    restore()
    log(f"client: {rect[2]}x{rect[3]} at ({rect[0]}, {rect[1]})")

    for action in sys.argv[1:]:
        verb, _, arg = action.partition(":")
        if verb == "snap":
            name, _, size = arg.partition("@")
            dims = tuple(int(v) for v in size.split("x")) if size else (1280, 720)
            restore()
            snap(name, dims)
        elif verb == "crop":
            spec, _, longest = arg.partition("@")
            name, *box = spec.split(",")
            restore()
            crop(name, *(float(v) for v in box), int(longest) if longest else 600)
        elif verb == "click":
            restore()
            click(*(float(v) for v in arg.split(",")))
        elif verb == "move":
            restore()
            point = at(*(float(v) for v in arg.split(",")))
            mouse_move_to(*point)
            log(f"  move -> {point}")
        elif verb == "key":
            restore()
            press(arg)
        elif verb == "char":
            restore()
            press(arg)
        elif verb == "wait":
            time.sleep(float(arg))
            log(f"  wait {arg}s")
        elif verb == "watch":
            restore()
            watch(float(arg))
        elif verb == "restore":
            restore()
            log("  restore")
        else:
            raise SystemExit(f"unknown action {action!r}")

    log(f"images: {OUT}")


if __name__ == "__main__":
    main()
