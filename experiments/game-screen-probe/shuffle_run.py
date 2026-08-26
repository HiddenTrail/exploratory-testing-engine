"""One-shot driver: get Tile Tale running and shuffle its board.

Exists because every separate shell invocation costs a permission prompt, and
answering one takes focus off a fullscreen-exclusive game - which minimizes it
and invalidates the next capture. So the whole cycle lives in one process.

Two hard rules learned the painful way:

  * NEVER click the exit icon. It quits the game outright, and every
    measurement after that reads a dead window - which looks exactly like
    "the input did nothing" rather than "there is nothing there". A whole
    10-strategy sweep once ran against a closed game and reported cleanly.
  * Assert the capture is live before trusting any result. `assert_alive`
    fails loudly on a flat frame instead of letting the sweep produce
    confident zeros.

Success is defined narrowly: the 3x3 board's per-cell mean colours must
change. Screen motion is not enough - a button repainting under the cursor and
a tutorial step advancing both produce plenty of motion while the board sits
untouched, and I read both as a successful shuffle once already.

Run: py experiments/game-screen-probe/shuffle_run.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import probe  # noqa: E402
from probe import (  # noqa: E402
    BUTTON_FLAGS,
    client_rect_on_screen,
    color_signature,
    diff_cells,
    grab_thumbnail,
    key_input,
    mouse_input,
    mouse_move_to,
    send_input,
    set_dpi_aware,
    write_png,
)

OUT = Path("C:/Users/pmarj/AppData/Local/Temp/tt/run")
STEAM_APPID = "2055270"

# Fractions of the client area, read off a 1280x720 capture of the game screen.
SHUFFLE = (0.2000, 0.9097)
BOARD = (0.2415, 0.3939, 0.1155, 0.2033)
STAGED_TILE = (0.2586, 0.7181)
# Deliberately no exit-icon coordinate. See the module docstring.

hwnd = 0
rect = (0, 0, 0, 0)


def log(message: str) -> None:
    print(message, flush=True)


def find_game() -> int:
    """Window handle, or 0. Does not raise - a missing window means 'launch
    it', not 'give up', so probe.find_window's SystemExit is wrong here."""
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


def launch() -> int:
    log("game is not running - launching via Steam")
    subprocess.run(["cmd", "/c", "start", "", f"steam://rungameid/{STEAM_APPID}"], check=False)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        time.sleep(2.0)
        handle = find_game()
        if handle:
            log("  window appeared; waiting for it to finish loading")
            time.sleep(8.0)
            return handle
    raise SystemExit("Tile Tale did not appear within 120s - start it manually and re-run.")


def restore(timeout: float = 8.0) -> None:
    """Bring the window back and wait for a non-zero client rect. Fullscreen
    exclusive means it self-minimizes whenever focus leaves."""
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


def assert_alive(where: str) -> None:
    """A dead or black window captures as a near-flat frame. Fail here rather
    than let every downstream reading come back a confident zero."""
    if rect[2] <= 0 or rect[3] <= 0:
        raise SystemExit(f"[{where}] client rect is {rect[2]}x{rect[3]} - the game is gone.")
    buf = grab_thumbnail(*rect, 32, 18)
    values = [buf[i] for i in range(0, len(buf), 4)]
    spread = max(values) - min(values)
    if spread < 12:
        raise SystemExit(
            f"[{where}] captured frame is flat (spread {spread}) - the window is dead or "
            f"occluded. Refusing to measure anything against it."
        )


def at(fx: float, fy: float) -> tuple[int, int]:
    left, top, width, height = rect
    return left + int(width * fx), top + int(height * fy)


def press_key(name: str, settle: float = 0.9) -> None:
    vk = probe.VK_NAMES[name]
    send_input(key_input(vk, keyup=False))
    time.sleep(0.05)
    send_input(key_input(vk, keyup=True))
    time.sleep(settle)


def snapshot(name: str, size: tuple[int, int] = (1280, 720)) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w, h = size
    write_png(str(OUT / f"{name}.png"), grab_thumbnail(*rect, w, h), w, h)


def board_state() -> list[tuple[float, float, float]]:
    """Per-cell mean colour of the 3x3 board - a fingerprint of the layout."""
    left, top, width, height = rect
    fx, fy, fw, fh = BOARD
    rx, ry = left + int(width * fx), top + int(height * fy)
    rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
    cw, ch = rw // 3, rh // 3
    return [
        color_signature(grab_thumbnail(rx + col * cw, ry + row * ch, cw, ch, 48, 48), 48, 48, 0.22)
        for row in range(3) for col in range(3)
    ]


def board_changed(before, after, tolerance: float = 6.0) -> int:
    return sum(1 for b, a in zip(before, after)
               if any(abs(x - y) > tolerance for x, y in zip(b, a)))


def on_game_screen() -> bool:
    """The game screen has the shuffle button bottom-left; the menu has bare
    background there. Measured: 198 mean brightness in game, 241 on the menu."""
    buf = grab_thumbnail(*at(0.15, 0.86), int(rect[2] * 0.14), int(rect[3] * 0.09), 16, 16)
    return sum(color_signature(buf, 16, 16)) / 3 < 220


def watch(seconds: float, threshold: int = 6) -> tuple[int, int]:
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
    return moving, peak


# --- click strategies -------------------------------------------------------

def click_plain(point, button="left", hold=0.08, hover=0.25):
    mouse_move_to(*point)
    time.sleep(hover)
    down, up = BUTTON_FLAGS[button]
    send_input(mouse_input(down))
    time.sleep(hold)
    send_input(mouse_input(up))


def click_long(point):
    click_plain(point, hold=0.35, hover=0.45)


def click_very_long(point):
    click_plain(point, hold=1.2, hover=0.6)


def click_jiggle(point):
    """Approach through intermediate positions. A game that tracks the mouse
    by delta, or only re-runs its hit test when the pointer actually moves,
    can miss a single teleport onto the button."""
    x, y = point
    for offset in (80, 55, 34, 18, 6, 0):
        mouse_move_to(x - offset, y - offset)
        time.sleep(0.07)
    time.sleep(0.35)
    send_input(mouse_input(BUTTON_FLAGS["left"][0]))
    time.sleep(0.3)
    send_input(mouse_input(BUTTON_FLAGS["left"][1]))


def click_double(point):
    click_plain(point, hold=0.12, hover=0.3)
    time.sleep(0.1)
    click_plain(point, hold=0.12, hover=0.05)


def click_repeat(point):
    """Five presses in a row. Covers a runtime that samples the button once
    per frame and can drop an isolated press to timing."""
    mouse_move_to(*point)
    time.sleep(0.35)
    for _ in range(5):
        send_input(mouse_input(BUTTON_FLAGS["left"][0]))
        time.sleep(0.14)
        send_input(mouse_input(BUTTON_FLAGS["left"][1]))
        time.sleep(0.14)


def click_right(point):
    click_plain(point, button="right", hold=0.3, hover=0.35)


def click_legacy(point):
    """mouse_event instead of SendInput - an older API taking a different path
    into the driver stack. Some runtimes filter one and not the other."""
    probe.user32.SetCursorPos(*point)
    time.sleep(0.35)
    probe.user32.mouse_event(probe.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.3)
    probe.user32.mouse_event(probe.MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


def click_drag_in_place(point):
    """Press, wiggle a pixel while held, release. A button bound to
    mouse-release on a still-hovered control needs the move event that a
    static press never generates."""
    mouse_move_to(*point)
    time.sleep(0.3)
    send_input(mouse_input(BUTTON_FLAGS["left"][0]))
    time.sleep(0.2)
    mouse_move_to(point[0] + 3, point[1] + 2)
    time.sleep(0.15)
    mouse_move_to(*point)
    time.sleep(0.2)
    send_input(mouse_input(BUTTON_FLAGS["left"][1]))


def key_space(_point):
    press_key("space", settle=0.3)


def key_enter(_point):
    press_key("enter", settle=0.3)


def key_s(_point):
    vk = ord("S")
    send_input(key_input(vk, keyup=False))
    time.sleep(0.08)
    send_input(key_input(vk, keyup=True))
    time.sleep(0.3)


def key_tab_then_enter(_point):
    press_key("tab", settle=0.35)
    press_key("enter", settle=0.3)


STRATEGIES = [
    ("plain click 80ms", click_plain),
    ("long click 350ms", click_long),
    ("very long click 1200ms", click_very_long),
    ("approach then click", click_jiggle),
    ("double click", click_double),
    ("five rapid clicks", click_repeat),
    ("press-wiggle-release", click_drag_in_place),
    ("right click", click_right),
    ("mouse_event legacy", click_legacy),
    ("key: space", key_space),
    ("key: enter", key_enter),
    ("key: s", key_s),
    ("key: tab then enter", key_tab_then_enter),
]


def try_shuffle(round_label: str) -> str | None:
    for name, strategy in STRATEGIES:
        restore()
        assert_alive(f"{round_label}/{name}")
        before = board_state()
        strategy(at(*SHUFFLE))
        moving, peak = watch(2.5)
        after = board_state()
        changed = board_changed(before, after)
        log(f"  {name:24s} motion {moving:2d} frames (peak {peak:3d})   "
            f"board cells changed {changed}/9")
        if changed >= 2:
            snapshot(f"99_shuffled_{name.replace(' ', '_').replace(':', '')}")
            return name
        time.sleep(0.4)
    return None


def main() -> None:
    global hwnd
    set_dpi_aware()
    OUT.mkdir(parents=True, exist_ok=True)

    hwnd = find_game() or launch()
    log(f"window: hwnd 0x{hwnd:X}")
    restore()
    assert_alive("startup")
    log(f"client: {rect[2]}x{rect[3]} at ({rect[0]}, {rect[1]})")
    snapshot("00_startup")

    # --- make sure we are on the game screen --------------------------------
    if on_game_screen():
        log("already on the game screen")
    else:
        log("on a menu - walking to the top (NEW GAME) and starting a game")
        probe.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        for _ in range(6):
            press_key("up", settle=0.3)
        snapshot("01_new_game_selected", (800, 450))
        press_key("enter", settle=3.0)
        restore()
        assert_alive("after starting a game")
        if not on_game_screen():
            snapshot("01b_unexpected")
            log("WARNING: still not on the game screen; continuing anyway")
    snapshot("02_game_screen")

    # --- shuffle ------------------------------------------------------------
    # Up to three rounds: if nothing shuffles, advance the tutorial one step
    # and retry, since shuffle may simply be locked during a tutorial beat.
    log("\n== shuffling ==")
    for round_index in range(3):
        label = f"round {round_index + 1}"
        log(f"{label}:")
        winner = try_shuffle(label)
        if winner:
            restore()
            snapshot("99_shuffled")
            log(f"\nSHUFFLED via '{winner}'. Board moved.")
            log(f"images: {OUT}")
            return
        if round_index < 2:
            log(f"{label} found nothing - advancing the tutorial one step and retrying")
            restore()
            press_key("esc", settle=1.5)
            restore()
            snapshot(f"tutorial_step_{round_index + 2}", (800, 450))

    log("\nNo strategy moved the board in three rounds.")
    log(f"images: {OUT}")


if __name__ == "__main__":
    main()
