"""Benchmark, then optimize, the tightest possible shuffle loop.

The task is fixed so the numbers compare across stages:

    1. new game
    2. shuffle until the deck counter reads 0
    3. stop

Reaching 0 tiles ends the game and raises the CHALLENGES screen, so "counter is
0" and "CHALLENGES is up" are the same event - and the second is far cheaper to
detect, because the blue `shuffle` label vanishes with the board. One 24x8
capture decides it.

Every stage does exactly that and reports wall time plus the two things that
actually drive it: how many screen captures were taken, and how many bytes of
pixels were pulled through the pure-Python decision path. There is no LLM in
this loop, so bytes-per-decision is the local equivalent of context size - and
like context size, it is paid on every single iteration.

Stage 1 is an honest transcription of how the existing scripts already work:
restore() before every action, assert liveness, fingerprint 25 sub-regions each
iteration, then sleep a fixed 2.2s for the animation. Stages 2..6 each remove
one source of that cost. Debug PNG writes are excluded from stage 1 even though
shuffle_verify.py does one per attempt, because deleting a debug artifact is not
an optimization and would flatter every later stage.

    py bench_shuffle.py --stage 1
    py bench_shuffle.py --stage 6 --cycles 3
    py bench_shuffle.py --calibrate

The state machine, as measured rather than assumed:

    main menu  --enter on NEW GAME-->  board
    board      --deck hits 0-------->  CHALLENGES
    CHALLENGES --any mouse click---->  main menu (NEW GAME pre-highlighted)

ESC does *not* leave the board - it only advances the tutorial. Nor do enter,
esc or space dismiss CHALLENGES; only a click does. Never clicks the exit icon,
and never presses enter on the menu without first confirming by pixel that NEW
GAME is the highlighted row, because the menu wraps and ESC parks the highlight
on QUIT.
"""

from __future__ import annotations

import argparse
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
    key_input,
    mouse_input,
    mouse_move_to,
    send_input,
    set_dpi_aware,
    write_png,
)

# Fractions of the client area, measured off captures of a 3840x2160 client, so
# they hold at any resolution.
SHUFFLE_BUTTON = (0.2000, 0.9097)
SHUFFLE_LABEL = (0.1610, 0.8940, 0.0760, 0.0330)   # the blue "shuffle" text
COUNTER = (0.6875, 0.8556, 0.0720, 0.1280)         # dashed box, bottom right
COUNTER_DIGIT = (0.7060, 0.8890, 0.0380, 0.0620)   # just the numeral inside it
QUEUE = (0.7060, 0.0440, 0.0380, 0.7700)           # the tall tile column
BOARD = (0.2415, 0.3939, 0.1155, 0.2033)
TUTORIAL = (0.3000, 0.1750, 0.2100, 0.0900)
MENU_X, MENU_W, MENU_H = 0.4200, 0.1850, 0.0440
MENU_ROWS = ("NEW GAME", "RECORDS", "SETTINGS", "QUIT")
MENU_Y = (0.4820, 0.5820, 0.6700, 0.7600)
# Deliberately no exit-icon coordinate.

STAGES = {
    1: dict(label="baseline (existing habits)",
            restore_each=True, alive_check=True, settle="fixed",
            probe="fingerprint", hover=0.25, hold=0.08, reposition=True),
    2: dict(label="adaptive settle instead of a fixed sleep",
            restore_each=True, alive_check=True, settle="stable",
            probe="fingerprint", hover=0.25, hold=0.08, reposition=True),
    3: dict(label="restore once, cache the rect",
            restore_each=False, alive_check=True, settle="stable",
            probe="fingerprint", hover=0.25, hold=0.08, reposition=True),
    # Order matters, and it is not the order these were tried in. Shrinking the
    # reads and parking the cursor were measured *before* the loop was closed,
    # and both came out slower end to end: clicking sooner without knowing the
    # game is ready only spends clicks against its shuffle cooldown, and the
    # cheap reads buy latency the loop then wastes waiting. Closing the loop
    # first turns them back into wins.
    4: dict(label="closed loop on the counter",
            restore_each=False, alive_check=True, settle="counter",
            probe="fingerprint", hover=0.25, hold=0.08, reposition=True),
    5: dict(label="drop the 25-region fingerprint",
            restore_each=False, alive_check=False, settle="counter",
            probe="label", hover=0.25, hold=0.08, reposition=True),
    6: dict(label="park the cursor, drop the hover",
            restore_each=False, alive_check=False, settle="counter",
            probe="label", hover=0.02, hold=0.08, reposition=False),
}

SETTLE_SECONDS = 2.2      # stage 1's fixed animation wait
STABLE_QUIET = 0.12       # "stable" == two consecutive equal reads this far apart
SETTLE_TIMEOUT = 4.0
RETRY_WINDOW = 0.7        # how long to wait for the counter before re-clicking
MAX_SHUFFLES = 60         # backstop: a shuffle that lands a match refills the deck


class Metrics:
    """Captures and pixel bytes are counted, not estimated. Both scale with the
    loop, so a stage that only shuffles sleeps around has nowhere to hide."""

    def __init__(self) -> None:
        self.captures = 0
        self.pixel_bytes = 0
        self.restores = 0

    def capture(self, w: int, h: int) -> None:
        self.captures += 1
        self.pixel_bytes += w * h * 4


M = Metrics()
hwnd = 0
rect = (0, 0, 0, 0)


def log(message: str) -> None:
    print(message, flush=True)


def grab(region, w: int, h: int) -> bytes:
    left, top, width, height = rect
    fx, fy, fw, fh = region
    M.capture(w, h)
    return grab_thumbnail(left + int(width * fx), top + int(height * fy),
                          max(1, int(width * fw)), max(1, int(height * fh)), w, h)


def grab_full(w: int, h: int) -> bytes:
    M.capture(w, h)
    return grab_thumbnail(*rect, w, h)


def at(fx: float, fy: float) -> tuple[int, int]:
    left, top, width, height = rect
    return left + int(width * fx), top + int(height * fy)


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
    M.restores += 1
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


# --- pixel readers ----------------------------------------------------------

def blueness(region, w: int = 24, h: int = 8) -> float:
    """Mean (blue - red). The game marks the active menu row and the shuffle
    button in blue on a cream background where red always exceeds blue, so the
    sign of this alone separates 'highlighted' from 'not'."""
    buf = grab(region, w, h)
    return sum(buf[i] - buf[i + 2] for i in range(0, len(buf), 4)) / (w * h)


def counter_ink(w: int = 24, h: int = 24) -> int:
    """Count of dark pixels in the deck counter's numeral.

    Two things this got wrong first. The box has a dashed tan border whose
    red-minus-blue clears any sane threshold, so a region including the border
    counts ~270 border pixels and the numeral vanishes into the noise - the
    reading stayed flat while the deck drained. And the numeral is not reliably
    red: it renders grey at higher counts and red only when the deck runs low,
    so redness is the wrong channel. Darkness inside a box tight enough to
    exclude the border catches both."""
    buf = grab(COUNTER_DIGIT, w, h)
    return sum(1 for i in range(0, len(buf), 4) if buf[i + 1] < 210)


def queue_ink(w: int = 16, h: int = 64) -> int:
    """Count of tile pixels in the queue column - proportional to the deck. Note
    it reaches zero at one tile remaining, not zero, because the column shows
    the tiles *behind* the staged one. Useful as a trace, not as the stop."""
    buf = grab(QUEUE, w, h)
    return sum(1 for i in range(0, len(buf), 4) if buf[i + 1] < 200)


def digit_frame(size: int = 16) -> bytes:
    return grab(COUNTER_DIGIT, size, size)


def digit_moved(before: bytes, after: bytes, size: int = 16) -> bool:
    """Compare the numeral as pixels rather than as an ink count. Two different
    digits can share an ink total - 6 and 5 are close - and a scalar collision
    there would stall the poll until its timeout, which is exactly the cost this
    is meant to avoid."""
    differing = sum(1 for i in range(0, len(before), 4)
                    if abs(before[i + 1] - after[i + 1]) > 24)
    return differing >= 4


def on_game_screen() -> bool:
    return blueness(SHUFFLE_LABEL) > 4.0


def highlighted_row() -> int:
    """Index of the blue menu row, or -1. Read rather than assumed: ESC parks
    the highlight on QUIT, so 'press up a few times' is not safe on a menu that
    wraps."""
    scores = [blueness((MENU_X, y - MENU_H / 2, MENU_W, MENU_H)) for y in MENU_Y]
    best = max(range(len(scores)), key=lambda i: scores[i])
    return best if scores[best] > 4.0 else -1


def alive() -> None:
    if rect[2] <= 0:
        raise SystemExit("client rect is empty - the game is gone.")
    buf = grab_full(32, 18)
    values = [buf[i] for i in range(0, len(buf), 4)]
    if max(values) - min(values) < 12:
        raise SystemExit("captured frame is flat - refusing to measure against it.")


# --- acting -----------------------------------------------------------------

def press(name: str, settle: float = 0.35) -> None:
    vk = probe.VK_NAMES[name]
    send_input(key_input(vk, keyup=False))
    time.sleep(0.04)
    send_input(key_input(vk, keyup=True))
    time.sleep(settle)


def click(point, hover: float, hold: float, reposition: bool = True) -> None:
    if reposition:
        mouse_move_to(*point)
    time.sleep(hover)
    down, up = BUTTON_FLAGS["left"]
    send_input(mouse_input(down))
    time.sleep(hold)
    send_input(mouse_input(up))


def dump(name: str) -> Path:
    shot = Path(f"C:/Users/pmarj/AppData/Local/Temp/tt/{name}.png")
    shot.parent.mkdir(parents=True, exist_ok=True)
    write_png(str(shot), grab_full(800, 450), 800, 450)
    return shot


def wait_for(predicate, timeout: float, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def ensure_menu() -> None:
    """Get to the main menu from wherever we are, without ever pressing exit.

    Only three states exist and only one is stuck-ish: mid-board, whose sole
    keyless way out is to spend the remaining tiles. That is the same action the
    benchmark measures, so recovering costs only time and keeps the harness
    runnable from any starting state.

    Every wait here polls rather than sleeps a guessed constant. A fixed 0.9s
    after the dismissing click was not enough for the CHALLENGES panel to slide
    out, so the next iteration saw no menu, assumed the click had missed, and
    clicked again - into a menu that was still animating in."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if wait_for(lambda: highlighted_row() >= 0, 1.0):
            return
        if on_game_screen():
            click(at(*SHUFFLE_BUTTON), 0.25, 0.08)
            wait_stable()
        else:
            # CHALLENGES, or any other overlay: only a click dismisses it -
            # enter, esc and space are all ignored. Deliberately not the exit
            # icon; anywhere harmless will do, and this point is well clear of
            # both the icon and every menu row.
            click(at(0.30, 0.96), 0.15, 0.08)
            wait_for(lambda: highlighted_row() >= 0, 4.0)
    raise SystemExit(f"could not reach the main menu; state dumped to {dump('bench_stuck')}")


def new_game() -> None:
    """Main menu -> a fresh board. Refuses to press enter unless NEW GAME is
    proven by pixel to be the highlighted row."""
    ensure_menu()
    row = highlighted_row()
    for _ in range(row):
        press("up", settle=0.18)
    row = highlighted_row()
    if row != 0:
        raise SystemExit(f"expected NEW GAME highlighted, got {MENU_ROWS[row]} - aborting.")
    press("enter", settle=0.4)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if on_game_screen():
            return
        time.sleep(0.15)
    raise SystemExit(f"new game never reached the board; state dumped to {dump('bench_nogame')}")


def wait_stable(timeout: float = SETTLE_TIMEOUT) -> None:
    """Poll a tiny thumbnail of the board until two reads agree. A fixed sleep
    has to be sized for the worst case and then pays it every iteration;
    polling pays the actual case."""
    previous = grab(BOARD, 12, 12)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(STABLE_QUIET)
        current = grab(BOARD, 12, 12)
        if current == previous:
            return
        previous = current


def wait_digit(before: bytes, timeout: float = SETTLE_TIMEOUT) -> bytes:
    """Poll only the numeral until it moves. The counter is the one signal the
    loop actually consumes; waiting for the board animation to finish is waiting
    for something nothing downstream reads."""
    deadline = time.monotonic() + timeout
    current = before
    while time.monotonic() < deadline:
        current = digit_frame()
        if digit_moved(before, current):
            return current
        time.sleep(0.02)
    return current


# --- the measured loop ------------------------------------------------------

def run_cycle(cfg, verify: bool = False) -> tuple[float, int, int]:
    """Returns (seconds, clicks, effective shuffles).

    `verify` costs two extra 16x16 reads per iteration, so it is off during
    timed runs. It exists because a click that fails to register is *fast*: it
    animates nothing, so the settle poll returns at once and the iteration looks
    like a cheap success. Trimming the press until clicks start dropping would
    therefore show up as an improvement in seconds-per-shuffle while actually
    doing less work per click. Counting how many clicks moved the counter is the
    only way to tell those apart."""
    new_game()
    started = time.perf_counter()
    clicks = effective = 0
    point = at(*SHUFFLE_BUTTON)
    if not cfg["reposition"]:
        mouse_move_to(*point)     # park once; every later click reuses the position
        time.sleep(0.15)
    track = verify or cfg["settle"] == "counter"

    while clicks < MAX_SHUFFLES:
        if cfg["restore_each"]:
            restore()
            point = at(*SHUFFLE_BUTTON)
        if cfg["alive_check"]:
            alive()

        before = digit_frame() if track else b""
        click(point, cfg["hover"], cfg["hold"], cfg["reposition"])
        clicks += 1

        if cfg["settle"] == "fixed":
            time.sleep(SETTLE_SECONDS)
        elif cfg["settle"] == "stable":
            wait_stable()
        else:
            # Closed loop: watch the one value that says the shuffle happened,
            # and give up quickly if it does not move. A click that never landed
            # is indistinguishable from a slow one until the counter says so, and
            # the cheapest recovery is simply the next iteration's click.
            wait_digit(before, RETRY_WINDOW)

        if cfg["probe"] == "fingerprint":
            fingerprint()
        board = on_game_screen()
        if track and (not board or digit_moved(before, digit_frame())):
            effective += 1
        if not board:              # CHALLENGES is up: the deck reached 0
            break

    return time.perf_counter() - started, clicks, effective


def fingerprint() -> list:
    """Stage 1's state read: 25 sub-region mean colours, as shuffle_verify does."""
    out = []
    for region, cols, rows in ((BOARD, 3, 3), (COUNTER, 2, 2), (TUTORIAL, 6, 2)):
        left, top, width, height = rect
        fx, fy, fw, fh = region
        rx, ry = left + int(width * fx), top + int(height * fy)
        rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
        cw, ch = rw // cols, rh // rows
        for r in range(rows):
            for c in range(cols):
                M.capture(40, 40)
                out.append(color_signature(
                    grab_thumbnail(rx + c * cw, ry + r * ch, cw, ch, 40, 40), 40, 40, 0.15))
    return out


def calibrate() -> None:
    """Walk a fresh deck down and print the ink series, so the stop condition
    rests on observed numbers rather than on what the digits ought to look
    like."""
    new_game()
    log(f"{'shuffle':>7}  {'digit ink':>9}  {'queue ink':>9}  {'on board':>8}")
    log(f"{0:>7}  {counter_ink():>9}  {queue_ink():>9}  {str(on_game_screen()):>8}")
    for i in range(1, MAX_SHUFFLES):
        click(at(*SHUFFLE_BUTTON), 0.25, 0.08)
        wait_stable()
        board = on_game_screen()
        log(f"{i:>7}  {counter_ink():>9}  {queue_ink():>9}  {str(board):>8}")
        if not board:
            log("  -> CHALLENGES: the deck reached 0")
            return


def main() -> None:
    global hwnd
    parser = argparse.ArgumentParser(description="Benchmark the shuffle loop.")
    parser.add_argument("--stage", type=int, default=1, choices=sorted(STAGES))
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--verify", action="store_true",
                        help="also report how many clicks actually spent a tile")
    args = parser.parse_args()

    set_dpi_aware()
    hwnd = find_game()
    if not hwnd:
        raise SystemExit("Tile Tale is not running.")
    restore()

    if args.calibrate:
        calibrate()
        return

    cfg = STAGES[args.stage]
    log(f"stage {args.stage}: {cfg['label']}")
    log(f"client {rect[2]}x{rect[3]}\n")
    log(f"{'cycle':>5}  {'seconds':>8}  {'clicks':>6}  {'landed':>6}  {'s/click':>8}  "
        f"{'captures':>8}  {'KiB':>7}")

    times, counts, landed = [], [], []
    for cycle in range(1, args.cycles + 1):
        M.__init__()
        elapsed, clicks, effective = run_cycle(cfg, args.verify)
        times.append(elapsed)
        counts.append(clicks)
        landed.append(effective)
        log(f"{cycle:>5}  {elapsed:>8.2f}  {clicks:>6}  "
            f"{(effective if args.verify else '-'):>6}  "
            f"{elapsed / max(1, clicks):>8.3f}  {M.captures:>8}  "
            f"{M.pixel_bytes / 1024:>7.0f}")

    total, clicks = sum(times), sum(counts)
    log(f"\nstage {args.stage} ({cfg['label']})")
    log(f"  mean cycle       {total / len(times):.2f}s over {len(times)} cycles")
    log(f"  mean per click   {total / max(1, clicks):.3f}s  ({clicks} clicks)")
    hits = sum(landed)
    if hits:
        # The metric that cannot be gamed by dropping clicks: a click that never
        # spent a tile is cheap, so per-click time improves while less work gets
        # done. Per *landed* shuffle counts only clicks that moved the counter.
        log(f"  per landed shuffle {total / hits:.3f}s")
        log(f"  landed           {hits}/{clicks} clicks spent a tile "
            f"({100 * hits / max(1, clicks):.0f}%)")
    log(f"  last cycle       {M.captures} captures, {M.pixel_bytes / 1024:.0f} KiB "
        f"of pixels, {M.restores} restores")


if __name__ == "__main__":
    main()
