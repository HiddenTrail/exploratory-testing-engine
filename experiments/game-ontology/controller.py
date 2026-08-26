"""A general controller for a native game window: own it, read it, poke it, and
survive it dying.

Nothing in this file knows what game it is driving. That is a design rule, not an
aspiration: every constant in `game-screen-probe` was game-specific and expensive
to find, and the point of this experiment is to *discover* those rather than ship
them. So the split is mechanics here, specifics in `target.py`, findings in the
generated ontology - and if a Tile Tale fact ever appears below, the experiment has
quietly stopped testing what it claims to test.

What it provides that a one-shot script does not:

- **Recovery.** A recon session runs unattended for minutes and the window will
  break: it self-minimizes on focus loss, it can end up occluded, and an explorer
  poking at an unknown UI will eventually find whatever quits the game. So every
  observation goes through `ensure_readable()`, which distinguishes the four ways a
  window stops being readable and applies the matching fix - up to and including
  relaunching the game and carrying on.
- **A readiness test with no game knowledge in it.** `game_session.py` could wait
  for "a screen the harness recognizes". Here there is nothing to recognize, so
  readiness is three general conditions: the client rect has stopped changing, the
  frame has variance in it, and consecutive frames are identical. The rect
  condition is not optional - a game measured here opens windowed 1280x720 and
  switches to fullscreen 3840x2160 about 3.3s later, so any quiet period short
  enough to be useful also fires before the switch, and every fraction then
  resolves against a rect the game has already discarded.

Capture and input are `probe.py`'s, unchanged - it is already fully general. The
one thing worth restating from its hard-won comments: capture reads the *screen* DC
clipped to the client rect, so an occluded window returns the windows on top of it
as a clean, plausible frame of the wrong application. That is why foreground is
asserted before a frame is trusted rather than after something downstream looks
wrong.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-screen-probe"))

import probe  # noqa: E402
from probe import (  # noqa: E402
    BUTTON_FLAGS,
    SW_RESTORE,
    VK_NAMES,
    client_rect_on_screen,
    grab_thumbnail,
    key_input,
    mouse_input,
    mouse_move_to,
    send_input,
    set_dpi_aware,
    write_png,
)

WM_CLOSE = 0x0010

LAUNCH_TIMEOUT = 90.0    # cold cache; a big game's data file may be hundreds of MB
READY_TIMEOUT = 60.0     # window exists -> settled and rendering
CLOSE_TIMEOUT = 15.0
FOCUS_TIMEOUT = 20.0

# How long the window must hold still before it is believed lives on the Target, as
# `startup_quiet` - it is a per-game measurement, not a universal constant.

# Below this, the frame is a flat fill: a dead or not-yet-rendering window. The
# specific failure this catches is the expensive one from the probe's notes - a
# whole measurement sweep once ran against a closed game and reported clean zeros,
# because "no variance" and "nothing happened" are the same reading downstream.
FLAT_VARIANCE = 3.0


def log(message: str) -> None:
    print(message, flush=True)


# --- windows ----------------------------------------------------------------

def find_window(title: str) -> int | None:
    """`probe.find_window` is CLI-shaped and raises `SystemExit` when nothing
    matches, which is right for a one-shot script and wrong for a watchdog that
    asks "is it still there?" several times a minute. Same enumeration, different
    contract."""
    try:
        hwnd, _ = probe.find_window(title)
        return hwnd
    except SystemExit:
        return None


def window_pid(hwnd: int) -> int:
    """The PID that owns the window - **not** the one `Popen` returned. Steamworks
    titles commonly call `SteamAPI_RestartAppIfNecessary`, which relaunches through
    Steam and exits the original process, so the spawned PID can be long dead while
    the game runs and killing it closes nothing."""
    probe.user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    probe.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    pid = ctypes.c_ulong(0)
    probe.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_foreground(hwnd: int) -> bool:
    probe.user32.GetForegroundWindow.restype = ctypes.c_void_p
    probe.user32.GetForegroundWindow.argtypes = []
    return probe.user32.GetForegroundWindow() == hwnd


def process_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True, check=False)
    return str(pid) in out.stdout


def steam_libraries() -> list[Path]:
    """Every Steam library root on this machine. Games move between libraries when
    a drive fills up, so a hardcoded path works right up until it doesn't."""
    roots: list[Path] = []
    for base in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
        vdf = base / "steamapps" / "libraryfolders.vdf"
        if not vdf.exists():
            continue
        roots.append(base)
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            roots.append(Path(match.group(1).replace("\\\\", "\\")))
    seen, unique = set(), []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def find_steam_exe(install_dir: str, exe_name: str) -> Path | None:
    for root in steam_libraries():
        candidate = root / "steamapps" / "common" / install_dir / exe_name
        if candidate.exists():
            return candidate
    return None


# --- what a target is -------------------------------------------------------

@dataclass
class Target:
    """Everything the controller needs to know about one game, and no more.

    `denylist` is the hard safety floor: fractional boxes that must never be
    clicked whatever anything else decides, for actions known to end the session or
    to be destructive. It is a list rather than a single box because the reasons
    differ and each one deserves its own note.

    The two tuning values are here rather than as constants in the general modules
    because they are genuinely per-game measurements, and burying a measurement as a
    global default is how one game's timing ends up deciding another's. Both have
    defaults that are honest starting points, not universal truths.
    """
    name: str
    window_title: str
    install_dir: str = ""
    exe_name: str = ""
    exe: str = ""
    denylist: list[dict] = field(default_factory=list)

    # How long the window must be completely quiet - rect unchanged AND pixels
    # unchanged - before it counts as past its startup transient. There is no way to
    # know a game has finished starting without waiting, so this parameter cannot be
    # eliminated; what it can be is *declared*, and cheap to be wrong about. A game
    # that switches resolution after this expires no longer breaks the session,
    # because `Controller.rect` reads live - the cost is a spurious extra screen
    # rather than a run where no input ever lands.
    startup_quiet: float = 4.0

    # Fraction of a screen's stable cells that must agree for two frames to be the
    # same screen. Calibrate from a session's own transitions: `report.md` prints the
    # changed-cell count for every one, and the threshold belongs between the counts
    # for "the highlight moved" and "this is somewhere else".
    screen_match: float = 0.94

    # How far a grid cell's mean must move to count as changed, per channel.
    cell_delta: int = 10

    def resolve_exe(self) -> Path | None:
        if self.exe:
            path = Path(self.exe)
            return path if path.exists() else None
        if self.install_dir and self.exe_name:
            return find_steam_exe(self.install_dir, self.exe_name)
        return None

    def forbids(self, fx: float, fy: float) -> str | None:
        """The reason this point is off limits, or None. Fractional so it survives
        the resolution change every launch of a fullscreen game performs."""
        for entry in self.denylist:
            x, y, w, h = entry["box"]
            if x <= fx <= x + w and y <= fy <= y + h:
                return entry.get("why", "denylisted")
        return None


# --- the controller ---------------------------------------------------------

class WindowLost(RuntimeError):
    """The window could not be made readable, even by relaunching."""


class Controller:
    """One live game window, kept readable.

    `restarts` and `notes` are part of the output, not diagnostics: a session that
    relaunched the game four times explored a different thing than one that did
    not, and a report that hides that is claiming more coverage than it measured.
    """

    def __init__(self, target: Target, verbose: bool = True):
        self.target = target
        self.verbose = verbose
        self.hwnd: int | None = None
        self.pid: int | None = None
        self._last_good: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.restarts = 0
        self.notes: list[str] = []
        self.launched_here = False

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """The client area on screen, read from the OS on every access.

        Never cached, and that is the point. A game can change resolution at any
        moment - fullscreen games do it seconds after launch, and some do it again on
        a settings change - and a cached rect turns that into a silent, total failure:
        every fractional coordinate resolves against geometry the game has discarded,
        so nothing lands and nothing errors. Reading live costs a `GetClientRect` per
        access, which is microseconds against the 61ms a capture takes, and it demotes
        "predict when the game stops resizing" from a correctness requirement to an
        optimisation."""
        if not self.hwnd:
            return self._last_good
        current = client_rect_on_screen(self.hwnd)
        if current[2] > 0:
            self._last_good = current
        return current

    @property
    def last_good_rect(self) -> tuple[int, int, int, int]:
        """The last non-empty rect seen. For reporting after the window is gone,
        where `rect` would correctly return zeros."""
        return self._last_good

    # -- lifecycle ----------------------------------------------------------

    def say(self, message: str) -> None:
        if self.verbose:
            log(message)

    def note(self, message: str) -> None:
        self.notes.append(message)
        self.say(f"  ! {message}")

    def start(self) -> None:
        """Attach to a running instance or launch one, then wait until readable."""
        existing = find_window(self.target.window_title)
        if existing:
            self.hwnd, self.pid = existing, window_pid(existing)
            self.say(f"attached to {self.target.name}: window {self.hwnd}, pid {self.pid}")
        else:
            self._launch()
        self.ensure_readable()

    def _launch(self) -> None:
        exe = self.target.resolve_exe()
        if exe is None:
            raise WindowLost(f"cannot find an executable for {self.target.name!r}")
        started = time.perf_counter()
        self.say(f"launching {exe}")
        # cwd is the exe's own directory: a game runtime resolves its data file,
        # its DLLs and its options next to itself, and started from elsewhere it
        # simply fails to find them.
        subprocess.Popen([str(exe)], cwd=str(exe.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.launched_here = True

        deadline = time.monotonic() + LAUNCH_TIMEOUT
        while time.monotonic() < deadline:
            hwnd = find_window(self.target.window_title)
            if hwnd:
                self.hwnd, self.pid = hwnd, window_pid(hwnd)
                self.say(f"  window {hwnd} after {time.perf_counter() - started:.1f}s "
                         f"(pid {self.pid})")
                return
            time.sleep(0.25)
        raise WindowLost(f"no window titled {self.target.window_title!r} "
                         f"within {LAUNCH_TIMEOUT:.0f}s")

    def close(self) -> str:
        """`WM_CLOSE`, then force. Which one was needed is a fact about the game and
        only one of them is safe to assume next time. Never by clicking an in-game
        exit control: going through the OS makes shutdown independent of whatever
        screen the session happened to end on."""
        if not self.hwnd:
            return "nothing to close"
        probe.user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                              ctypes.c_void_p, ctypes.c_void_p]
        probe.user32.PostMessageW.restype = ctypes.c_int
        probe.user32.PostMessageW(self.hwnd, WM_CLOSE, None, None)

        deadline = time.monotonic() + CLOSE_TIMEOUT
        while time.monotonic() < deadline:
            if not find_window(self.target.window_title):
                if self.pid:
                    # The window is gone but the process may still be tearing down,
                    # and a relaunch that races the teardown gets two instances.
                    end = time.monotonic() + 5.0
                    while time.monotonic() < end and process_alive(self.pid):
                        time.sleep(0.2)
                self.hwnd = None
                return "WM_CLOSE"
            time.sleep(0.25)

        if self.pid:
            subprocess.run(["taskkill", "/PID", str(self.pid), "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.hwnd = None
        return "taskkill /F"

    # -- keeping it readable ------------------------------------------------

    def focus(self, timeout: float = FOCUS_TIMEOUT) -> bool:
        """Bring the window forward and keep asking until it is actually there.

        One `SetForegroundWindow` is not enough: Windows refuses the call from a
        process that does not own the foreground and has had no recent input, and it
        fails silently. Retries come first because they are side-effect free; the
        ALT tap is only reached if the polite version keeps being refused, and it
        works by giving this process a keystroke to hold."""
        if not self.hwnd:
            return False
        deadline = time.monotonic() + timeout
        attempts = 0
        while time.monotonic() < deadline:
            if is_foreground(self.hwnd) and self.rect[2] > 0:
                return True
            attempts += 1
            if attempts > 3:
                send_input(key_input(0x12, keyup=False))   # VK_MENU
                send_input(key_input(0x12, keyup=True))
            probe.user32.ShowWindow(self.hwnd, SW_RESTORE)
            probe.user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.3)
        return False

    def ensure_readable(self, allow_restart: bool = True) -> str:
        """Make the window trustworthy to capture, and say what had to be done.

        Four distinct failures that all look identical to anything downstream:

        - **gone** - the process exited. Every later capture reads the desktop.
        - **minimized** - rect 0x0, which fullscreen-exclusive games do to
          themselves the moment they lose focus.
        - **occluded** - a valid rect with the wrong pixels in it, because capture
          reads the screen DC clipped to that rect. No error, just another
          application's window presented as a plausible game frame.
        - **flat** - a rect and the foreground, but a uniform fill: dying, or not
          yet rendering.

        Only the first needs a relaunch and the others must not trigger one, which
        is why they are separated here rather than collapsed into "unhealthy"."""
        if self.hwnd is None or not find_window(self.target.window_title):
            if not allow_restart:
                raise WindowLost("window is gone")
            return self._restart("window is gone")

        if not self.focus():
            if not allow_restart:
                raise WindowLost("window will not come to the foreground")
            return self._restart("window would not come to the foreground")

        settled = self._wait_settled()
        if settled is None:
            if not allow_restart:
                raise WindowLost("window never rendered a settled frame")
            return self._restart("window never rendered a settled frame")
        return "ok"

    def _restart(self, why: str) -> str:
        """Relaunch and carry on. The accumulated ontology is deliberately *not*
        discarded: what was learned about the game is still true, and a session that
        threw it away on every crash would never get past the first screen."""
        self.restarts += 1
        self.note(f"restart {self.restarts}: {why}")
        if self.hwnd and find_window(self.target.window_title):
            self.close()
        time.sleep(1.0)
        self.hwnd = None
        self._launch()
        if not self.focus():
            raise WindowLost("relaunched, but the window will not take the foreground")
        if self._wait_settled() is None:
            raise WindowLost("relaunched, but the window never rendered a settled frame")
        return "restarted"

    def _wait_settled(self) -> float | None:
        """Wait for the window to stop changing on its own. Seconds waited, or None.

        Quiet means *both* the rect and the pixels have held still for
        `target.startup_quiet`, and any change to either restarts the clock. That is
        what removes the need to know when a game finishes resizing: a resolution
        switch resets the timer rather than needing to be predicted, so the only thing
        the parameter has to exceed is the longest gap *between* startup transients,
        not their total duration.

        Waiting matters beyond geometry. If exploration begins during the startup
        transient, the splash-to-menu change arrives on its own and gets attributed to
        whatever input happened to be in flight - recording "pressing down opened the
        main menu", which is worse than a slow start because it is a false edge in the
        graph rather than a missing one.

        The frame must also have variance, or it is a flat fill: a dying window, or one
        that has not begun rendering."""
        started = time.monotonic()
        deadline = started + READY_TIMEOUT
        quiet = self.target.startup_quiet
        rect = self.rect
        calm_since = time.monotonic()
        previous: bytes | None = None
        rescues = 0
        while time.monotonic() < deadline:
            current = self.rect
            if current != rect:
                self.say(f"  rect -> {current[2]}x{current[3]} at ({current[0]}, {current[1]})")
                rect, calm_since, previous = current, time.monotonic(), None

            # A fullscreen-exclusive window minimizes itself the instant it loses the
            # foreground, and startup is when that is most likely: the game takes the
            # foreground, then something else briefly does, and it parks itself at
            # (-32000, -32000) with a 0x0 client rect. Nothing here will ever settle
            # after that, so restoring belongs *inside* this loop - waiting out the
            # timeout and reporting "never rendered" describes the symptom and throws
            # away the one fix that works.
            if current[2] == 0 or not is_foreground(self.hwnd):
                rescues += 1
                if rescues > 20:
                    self.say("  window keeps losing the foreground; giving up on it")
                    return None
                probe.user32.ShowWindow(self.hwnd, SW_RESTORE)
                probe.user32.SetForegroundWindow(self.hwnd)
                calm_since, previous = time.monotonic(), None
                time.sleep(0.4)
                continue

            frame = self.grab(64, 36, verify=False)
            if variance(frame) < FLAT_VARIANCE:
                calm_since, previous = time.monotonic(), None
            elif previous is not None and frame != previous:
                calm_since = time.monotonic()
            previous = frame

            if time.monotonic() - calm_since >= quiet:
                if rescues:
                    self.say(f"  settled after {rescues} restore(s)")
                return time.monotonic() - started
            time.sleep(0.3)
        self.say(f"  gave up waiting after {READY_TIMEOUT:.0f}s: rect "
                 f"{rect[2]}x{rect[3]}, {rescues} restore(s) attempted, never quiet "
                 f"for {quiet:.1f}s")
        return None

    # -- perception ---------------------------------------------------------

    def grab(self, cols: int, rows: int, region=(0.0, 0.0, 1.0, 1.0),
             verify: bool = True) -> bytes:
        """A downsampled BGRA buffer of a fractional region of the client area.

        `verify` asserts the window is still the foreground *before* the frame is
        used rather than after something downstream looks wrong. Turned off only
        inside the readiness loop, which is the one caller whose job is to find out
        whether that is true yet."""
        if verify and not is_foreground(self.hwnd):
            self.ensure_readable()
        left, top, width, height = self.rect
        fx, fy, fw, fh = region
        return grab_thumbnail(left + int(width * fx), top + int(height * fy),
                              max(1, int(width * fw)), max(1, int(height * fh)),
                              cols, rows)

    def save_png(self, path: Path, region=(0.0, 0.0, 1.0, 1.0), longest: int = 1400) -> tuple[int, int]:
        """Full-resolution capture, scaled so its longest side is `longest`.

        Detection runs on tiny thumbnails; the record does not. A 4K client
        downsampled to 1280x720 shrinks a small UI element to a few pixels - enough
        to see that it changed, not enough for anything, human or model, to say what
        it became."""
        left, top, width, height = self.rect
        fx, fy, fw, fh = region
        rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
        scale = min(1.0, longest / max(rw, rh))
        ow, oh = max(1, int(rw * scale)), max(1, int(rh * scale))
        path.parent.mkdir(parents=True, exist_ok=True)
        write_png(str(path), grab_thumbnail(left + int(width * fx), top + int(height * fy),
                                            rw, rh, ow, oh), ow, oh)
        return ow, oh

    def wait_stable(self, cols: int = 32, rows: int = 18, threshold: int = 6,
                    quiet: float = 0.25, timeout: float = 3.0) -> float:
        """Block until the screen stops changing; return how long that took.

        Adaptive rather than a fixed sleep, because the settle time is the useful
        measurement: an action that visibly does nothing returns in one poll, and an
        action that opens a screen takes several. That difference is recorded on
        every transition, and it is the cheapest signal available for "this action
        did something substantial"."""
        started = time.monotonic()
        previous = self.grab(cols, rows)
        calm_since = time.monotonic()
        while time.monotonic() - started < timeout:
            time.sleep(0.05)
            current = self.grab(cols, rows)
            if changed_cells(previous, current, threshold):
                calm_since = time.monotonic()
            previous = current
            if time.monotonic() - calm_since >= quiet:
                break
        return time.monotonic() - started

    # -- action -------------------------------------------------------------

    def point(self, fx: float, fy: float) -> tuple[int, int]:
        left, top, width, height = self.rect
        return left + int(width * fx), top + int(height * fy)

    def hover(self, fx: float, fy: float, settle: float = 0.20) -> None:
        """Move the cursor and nothing else - the least state-changing input that
        can still provoke a visible reaction, which makes it the only probe safe to
        sweep across a UI nobody has mapped yet."""
        mouse_move_to(*self.point(fx, fy))
        time.sleep(settle)

    def click(self, fx: float, fy: float, button: str = "left",
              hover: float = 0.20, hold: float = 0.08) -> None:
        """Move, wait, press, hold, release - deliberately slow.

        Both pauses are load-bearing. A press arriving in the same input frame as
        the move gets hit-tested against wherever the pointer used to be, and a
        down/up pair sent in one batch can be sampled by a game that polls once a
        frame as no click at all. Both failures look identical from outside: the
        click is simply ignored, which reads as "not a button"."""
        why = self.target.forbids(fx, fy)
        if why:
            raise PermissionError(f"({fx:.3f}, {fy:.3f}) is denylisted: {why}")
        mouse_move_to(*self.point(fx, fy))
        time.sleep(hover)
        down, up = BUTTON_FLAGS[button]
        send_input(mouse_input(down))
        time.sleep(hold)
        send_input(mouse_input(up))

    def press(self, key: str) -> None:
        """Scancode input, via `probe.key_input`: game runtimes routinely read the
        keyboard at a level where a virtual-key-only synthetic event is invisible,
        and the arrow cluster needs its extended flag or it arrives as the numpad."""
        vk = VK_NAMES.get(key.lower()) or (ord(key.upper()) if len(key) == 1 else None)
        if vk is None:
            raise ValueError(f"unknown key {key!r}")
        send_input(key_input(vk, keyup=False), key_input(vk, keyup=True))


# --- small pixel helpers ----------------------------------------------------

def variance(bgra: bytes) -> float:
    """Standard deviation of the green channel. Green rather than a luma mix
    because it is the channel with the most contrast in almost every palette, and
    one channel is a third of the work for the same yes/no answer."""
    values = [bgra[i + 1] for i in range(0, len(bgra), 4)]
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def changed_cells(before: bytes, after: bytes, threshold: int) -> int:
    """How many thumbnail cells moved by more than `threshold` on the mean of the
    three channels. Mean over channels so a flash in one channel does not count the
    same as a real content change; the alpha byte is skipped because GDI leaves it
    undefined here."""
    count = 0
    for i in range(0, min(len(before), len(after)), 4):
        delta = (abs(before[i] - after[i])
                 + abs(before[i + 1] - after[i + 1])
                 + abs(before[i + 2] - after[i + 2])) // 3
        if delta > threshold:
            count += 1
    return count


if __name__ == "__main__":
    # Smoke test with no game knowledge and no exploration: can this thing take
    # ownership of a window, read it, and put it back?
    import argparse

    parser = argparse.ArgumentParser(description="Launch a target, read it, close it.")
    parser.add_argument("--target", default=None)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    import target as targets

    set_dpi_aware()
    controller = Controller(targets.load(args.target))
    controller.start()
    log(f"client {controller.rect[2]}x{controller.rect[3]} at "
        f"({controller.rect[0]}, {controller.rect[1]})")
    log(f"variance {variance(controller.grab(64, 36)):.1f}, "
        f"settled in {controller.wait_stable():.2f}s")
    if args.keep_open:
        log("leaving it running (--keep-open)")
    else:
        log(f"closed via {controller.close()}")
