"""Own the whole lifecycle: launch the game cold, test it, shut it down.

    py game_session.py                 # launch, one shuffle cycle, close
    py game_session.py --keep-open     # leave it running afterwards
    py game_session.py --exe PATH      # skip discovery

Everything before this script assumed a human had already started the game and
would close it afterwards, which is fine for exploring and useless for anything
scheduled. This closes that loop: cold disk to result to no process.

Three things about launching a Steam game that the obvious version gets wrong:

- **The process you start may not be the process you get.** Steamworks titles
  commonly call `SteamAPI_RestartAppIfNecessary`, which re-launches the game
  through Steam and *exits the original*. So the PID from `Popen` can be dead
  while the game is very much running, and killing it later closes nothing. The
  authoritative PID is the one that owns the window, via
  `GetWindowThreadProcessId` - so that is what gets read, after the window
  appears, and what gets shut down at the end.
- **A visible window is not a ready window, and it is not even its final size.**
  Measured cold: the window appears at ~3s as a **windowed 1280x720**, then
  switches to **fullscreen 3840x2160** about 3.3s later. A harness that starts
  the moment the window has content therefore computes every coordinate against
  a rect that is about to be replaced, and each fraction lands somewhere
  arbitrary - which presents as "the clicks do nothing", not as "the geometry is
  wrong". So readiness is three conditions, not one: the rect has stopped
  changing, the window renders something with variance in it, and a screen the
  harness recognizes (main menu or board) is actually up.
- **`data.win` is 136 MB.** A cold-cache first launch is far slower than a warm
  one, so the timeout has to be sized for the cold case, and polling (rather
  than sleeping) means the warm case doesn't pay for it.

Shutdown is `WM_CLOSE` first, then `taskkill /F` only if the game ignores it -
never by clicking the in-game exit icon. That icon is off-limits for a different
reason (a run that clicks it reads as "the input did nothing" for the rest of its
life), and going through the OS makes shutdown independent of what is on screen,
which matters because the test deliberately ends on the game-over screen.
"""

from __future__ import annotations

import argparse
import ctypes
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import bench_shuffle as bench  # noqa: E402
import probe  # noqa: E402
from probe import set_dpi_aware  # noqa: E402

WM_CLOSE = 0x0010

STEAM_APPID = "2055270"
EXE_NAME = "tile_tale.exe"
INSTALL_DIR = "Tile Tale"

LAUNCH_TIMEOUT = 90.0     # cold cache, 136 MB of game data
UI_TIMEOUT = 60.0         # window up -> a screen the harness recognizes
CLOSE_TIMEOUT = 15.0


def log(message: str) -> None:
    print(message, flush=True)


# --- finding the install ----------------------------------------------------

def steam_libraries() -> list[Path]:
    """Every Steam library root on this machine, not just the default one.

    Games move between libraries when a drive fills up, so hardcoding
    `C:/Program Files (x86)/Steam` works right up until it doesn't. The roots are
    listed in `libraryfolders.vdf`; the format is Valve's own KeyValues, but the
    only field needed here is `path`, which a regex reads without pulling in a
    parser for a file with one interesting key."""
    roots: list[Path] = []
    for base in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
        vdf = base / "steamapps" / "libraryfolders.vdf"
        if not vdf.exists():
            continue
        roots.append(base)
        for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
            roots.append(Path(match.group(1).replace("\\\\", "\\")))
    seen, unique = set(), []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def find_exe(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"no such exe: {path}")
        return path
    for root in steam_libraries():
        candidate = root / "steamapps" / "common" / INSTALL_DIR / EXE_NAME
        if candidate.exists():
            return candidate
    raise SystemExit(f"could not find {EXE_NAME} in any Steam library; pass --exe")


# --- launching --------------------------------------------------------------

def window_pid(hwnd: int) -> int:
    probe.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                     ctypes.POINTER(ctypes.c_ulong)]
    probe.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    pid = ctypes.c_ulong(0)
    probe.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_foreground(hwnd: int) -> bool:
    probe.user32.GetForegroundWindow.restype = ctypes.c_void_p
    probe.user32.GetForegroundWindow.argtypes = []
    return probe.user32.GetForegroundWindow() == hwnd


def focus(hwnd: int, timeout: float = 20.0) -> bool:
    """Make the game the foreground window, and keep asking until it is.

    This is the step whose absence is hardest to diagnose. A launched-from-a-
    background-process game comes up **behind** whatever was already on screen,
    with a perfectly valid client rect - and capture reads the *screen* DC
    clipped to that rect, so it returns the windows sitting on top instead. Not
    black, not an error: a clean, plausible frame of some other application. A
    detector asked "is the main menu up" then answers no, correctly, about a
    spreadsheet, and the run times out looking healthy the whole way.

    `bench.restore()` does not cover this: it retries only while the rect is
    *empty*, which catches the self-minimize case and not this one, so it fires a
    single `SetForegroundWindow` and moves on.

    One `SetForegroundWindow` is not enough anyway. Windows refuses the call from
    a process that does not own the foreground and has had no recent input, so
    the honest options are to retry, or to give this process a keystroke to hold
    - which is what the ALT tap does, and why it is a documented workaround
    rather than superstition. Retries come first because they are side-effect
    free; the tap is only reached if the polite version keeps being refused."""
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        if is_foreground(hwnd) and probe.client_rect_on_screen(hwnd)[2] > 0:
            bench.hwnd = hwnd
            bench.rect = probe.client_rect_on_screen(hwnd)
            return True
        attempts += 1
        if attempts > 3:
            probe.send_input(probe.key_input(0x12, keyup=False))   # VK_MENU
            probe.send_input(probe.key_input(0x12, keyup=True))
        probe.user32.ShowWindow(hwnd, probe.SW_RESTORE)
        probe.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
    return False


def wait_for(predicate, timeout: float, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def start(exe: Path) -> tuple[int, int, float]:
    """Start the process and return (hwnd, pid, t0) as soon as a window exists.

    Deliberately stops at "a window exists" and does no readiness work, so that
    the caller holds a window handle *before* anything can fail. A readiness
    check that raises from inside the launch function leaves nothing to shut
    down, and the run orphans a fullscreen game on the user's desktop.

    cwd is the exe's own directory, not ours: `data.win`, `Steamworks.dll` and
    `options.ini` are all resolved relative to it, and a GameMaker runtime
    started from elsewhere fails to find its data."""
    started = time.perf_counter()
    log(f"launching {exe}")
    subprocess.Popen([str(exe)], cwd=str(exe.parent),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    hwnd = wait_for(bench.find_game, LAUNCH_TIMEOUT)
    if not hwnd:
        raise SystemExit(f"no game window appeared within {LAUNCH_TIMEOUT:.0f}s")
    pid = window_pid(hwnd)
    left, top, width, height = probe.client_rect_on_screen(hwnd)
    log(f"  window {hwnd} after {time.perf_counter() - started:.1f}s (pid {pid}), "
        f"{width}x{height} at ({left}, {top})")
    return hwnd, pid, started


def wait_ready(hwnd: int, t0: float) -> float:
    """Block until the game is in a state this harness can act on.

    The rect is re-read on **every** poll rather than sampled once and trusted.
    Waiting for it to "settle" and then keeping that value is the trap: measured
    cold, the window is 1280x720 windowed for the first ~8 seconds and only then
    switches to 3840x2160 fullscreen, so any quiet-period threshold short enough
    to be useful also fires before the switch. Every fraction then resolves
    against a rect the game has discarded, and the symptom is not a geometry
    error - it is a run where nothing is ever recognized and no click lands.

    The authoritative signal is not a size or a timeout anyway; it is whether a
    screen the harness knows how to read is on display. So poll for that, and let
    the rect be whatever it currently is at the moment of the read."""
    bench.hwnd = hwnd
    seen = probe.client_rect_on_screen(hwnd)
    deadline = time.monotonic() + UI_TIMEOUT
    while time.monotonic() < deadline:
        current = probe.client_rect_on_screen(hwnd)
        if current[2] <= 0 or not is_foreground(hwnd):
            # Two distinct ways the window is unreadable, and both look the same
            # downstream. Minimized (rect 0x0) because fullscreen-exclusive games
            # self-minimize on focus loss; or simply *behind* something, which a
            # launch from a background process guarantees. Either way the capture
            # comes back as another application's window rather than as an error.
            if not focus(hwnd):
                raise SystemExit("could not bring the game to the foreground")
            current = bench.rect
        if current != seen:
            log(f"  resized to {current[2]}x{current[3]} at ({current[0]}, "
                f"{current[1]}) after {time.perf_counter() - t0:.1f}s")
            seen = current
        bench.hwnd, bench.rect = hwnd, current
        row = bench.highlighted_row()
        if row >= 0 or bench.on_game_screen():
            elapsed = time.perf_counter() - t0
            where = bench.MENU_ROWS[row] + " menu" if row >= 0 else "board"
            log(f"  ready after {elapsed:.1f}s: {current[2]}x{current[3]}, {where}")
            return elapsed
        time.sleep(0.3)
    raise SystemExit("no recognizable screen after launch; "
                     f"state dumped to {bench.dump('launch_unknown')}")


# --- closing ----------------------------------------------------------------

def close(hwnd: int, pid: int) -> str:
    """WM_CLOSE, then force. Reports which one was needed, because 'we asked
    nicely and it worked' and 'we killed it' are different facts about the game
    and only one of them is safe to assume next time."""
    probe.user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_void_p, ctypes.c_void_p]
    probe.user32.PostMessageW.restype = ctypes.c_int
    probe.user32.PostMessageW(hwnd, WM_CLOSE, None, None)

    if wait_for(lambda: not bench.find_game(), CLOSE_TIMEOUT):
        # The window is gone, but the process may still be tearing down; a
        # follow-on launch that races that teardown gets a second instance.
        wait_for(lambda: not process_alive(pid), 5.0)
        return "WM_CLOSE"

    log("  WM_CLOSE ignored; forcing")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not wait_for(lambda: not process_alive(pid), CLOSE_TIMEOUT):
        raise SystemExit(f"pid {pid} survived taskkill /F")
    return "taskkill /F"


def process_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True, check=False)
    return str(pid) in out.stdout


# --- the test ---------------------------------------------------------------

def shuffle_test(hwnd: int, stage: int) -> tuple[float, int, int]:
    """One measured cycle of the benchmark's fastest configuration: new game,
    shuffle until the deck reads 0, stop. Reused rather than reimplemented so
    this and the benchmark cannot drift apart in what they call a shuffle."""
    bench.hwnd = hwnd
    bench.M.__init__()
    if not focus(hwnd):
        raise SystemExit("game will not take the foreground; refusing to measure")
    cfg = bench.STAGES[stage]
    log(f"\nshuffle test - stage {stage}: {cfg['label']}")
    elapsed, clicks, landed = bench.run_cycle(cfg, verify=True)
    log(f"  {elapsed:.2f}s, {clicks} clicks, {landed} landed "
        f"({100 * landed / max(1, clicks):.0f}%), "
        f"{bench.M.captures} captures, {bench.M.pixel_bytes / 1024:.0f} KiB")
    return elapsed, clicks, landed


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the game, test it, close it.")
    parser.add_argument("--exe", help="path to tile_tale.exe (default: find via Steam)")
    parser.add_argument("--stage", type=int, default=6, choices=sorted(bench.STAGES))
    parser.add_argument("--keep-open", action="store_true",
                        help="skip shutdown, leave the game running")
    parser.add_argument("--no-test", action="store_true",
                        help="launch and close without playing")
    args = parser.parse_args()

    set_dpi_aware()
    exe = find_exe(args.exe)

    existing = bench.find_game()
    if existing:
        # Attaching is right rather than launching a second copy, but say so:
        # the timings below would otherwise be reported as a cold start.
        hwnd, pid, t0 = existing, window_pid(existing), 0.0
        log(f"already running: window {hwnd}, pid {pid} - attaching, not launching")
    else:
        hwnd, pid, t0 = start(exe)

    # Everything from here is inside the guard, so a readiness failure still
    # shuts the game down instead of orphaning a fullscreen window.
    startup = 0.0
    try:
        if t0:
            startup = wait_ready(hwnd, t0)
        if not args.no_test:
            shuffle_test(hwnd, args.stage)
    except BaseException as exc:
        # Say what went wrong *before* the shutdown lines. `finally` otherwise
        # runs first and the failure surfaces underneath "closed via WM_CLOSE",
        # which reads as though the close were the thing that failed.
        log(f"\nFAILED: {exc}")
        raise
    finally:
        if args.keep_open:
            log("\nleaving the game running (--keep-open)")
        else:
            how = close(hwnd, pid)
            log(f"\nclosed via {how}; pid {pid} is gone")
            if startup:
                log(f"cold start to measurable: {startup:.1f}s")


if __name__ == "__main__":
    main()
