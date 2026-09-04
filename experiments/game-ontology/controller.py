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
  frame has variance in it, and consecutive frames agree to within the same
  tolerance that decides screen identity. That last one used to demand byte-equal
  frames, which starved forever on a game whose idle menu twitches a single cell -
  a gate strictly tighter than the test it protects is a gate that rejects frames
  the rest of the harness would have been happy with. The rect condition is not
  optional: a game measured here opens windowed 1280x720 and switches to fullscreen
  3840x2160 about 3.3s later, so any quiet period short enough to be useful also
  fires before the switch, and every fraction then resolves against a rect the game
  has already discarded.
- **Finding the game at all.** `--game Mitosis` is resolved to an install directory
  across every Steam library, to the executable that most resembles it, and after
  launch to whichever new window appeared - so a game nobody has calibrated can be
  run by name. All three are guesses, so all three are logged with their runners-up.

Capture and input are `probe.py`'s, unchanged - it is already fully general. The
one thing worth restating from its hard-won comments: capture reads the *screen* DC
clipped to the client rect, so an occluded window returns the windows on top of it
as a clean, plausible frame of the wrong application. That is why foreground is
asserted before a frame is trusted rather than after something downstream looks
wrong.
"""

from __future__ import annotations

import ctypes
import os
import re
import struct
import subprocess
import sys
import time
import winreg
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-screen-probe"))

import probe  # noqa: E402
from probe import (  # noqa: E402
    BUTTON_FLAGS,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_WHEEL,
    SW_RESTORE,
    VK_NAMES,
    WHEEL_DELTA,
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
# Below this, in either dimension, a new window is a splash, a launcher or an error
# dialog rather than the game - the launch discovery in `_launched_window` skips it.
MIN_GAME_WINDOW = 320
FOCUS_TIMEOUT = 20.0

# How long the window must hold still before it is believed lives on the Target, as
# `startup_quiet` - it is a per-game measurement, not a universal constant.

# The grid the readiness loop watches for movement. Finer than the identity grid on
# purpose: this one is looking for "is anything still happening", so it should see a
# transient that covers a small part of the screen. It is a fraction of the grid that
# decides, so the size does not have to agree with anything else.
READY_COLS, READY_ROWS = 64, 36

# The mouse buttons and the chord prefixes this harness can send, named here because
# `describe.py` has to offer exactly these to a model and `recon.py` has to record them.
# Derived from `probe.BUTTON_FLAGS` rather than restated, so a fourth button cannot be
# offered to a planner that the input layer would then fail to send.
MOUSE_BUTTONS = tuple(BUTTON_FLAGS)
MODIFIERS = ("shift", "ctrl", "alt")

# How a drag is shaped. These are input-shaping constants of the same kind as
# `click`'s hover and hold - general facts about how synthetic input has to look to be
# seen, not per-game measurements, which is why they are here rather than on `Target`.
DRAG_STEPS = 12          # moves between the two ends. Enough that a game integrating
                         # motion per frame gets several samples, at any frame rate a
                         # person would play at.
DRAG_GRAB = 0.06         # after the press, before the first move. A UI that decides
                         # what is being picked up does it on the press, and a move
                         # arriving in the same frame can be attributed to nothing.
DRAG_GLIDE = 0.012       # between moves: ~0.15s of travel in total, which reads as a
                         # brisk hand rather than a teleport.
DRAG_SETTLE = 0.10       # held still at the far end before the release, so a drop
                         # read on button-up is read at the position it was aimed at.
SCROLL_GAP = 0.03        # between wheel notches. A real wheel does not emit three
                         # messages in one frame, and a game that coalesces per frame
                         # would see one scroll where three were sent.

# Below this, the frame is a flat fill: a dead or not-yet-rendering window. The
# specific failure this catches is the expensive one from the probe's notes - a
# whole measurement sweep once ran against a closed game and reported clean zeros,
# because "no variance" and "nothing happened" are the same reading downstream.
FLAT_VARIANCE = 3.0


def log(message: str) -> None:
    print(message, flush=True)


def readable_output() -> None:
    """Make stdout able to carry what a model wrote. Call it first in every entry point.

    Windows hands a Python process a cp1252 stdout, and every log line in this experiment
    can contain a model's prose: the reason a mission was planned, the reason an action was
    refused, the label it gave a control. A model writes arrows and em dashes, cp1252 has
    no code point for either, and `print` raises rather than dropping the character. A live
    mission run died exactly there - between planning mission 2 and flying it, with the
    game already launched, on a `→` in a sentence explaining why.

    Process-wide rather than a guard inside `log`, because `log` is not the only thing here
    that prints model text: `engine/client.py` prints the validation errors it feeds back
    on a retry, and those quote the payload. One line at startup covers every print in the
    process, including the ones in code this experiment only borrows.

    `errors="replace"` as well as UTF-8, so a console that still cannot encode something
    loses that character and not the run - the whole point is that no sentence a model
    writes should be able to end a session that has a game open."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass  # not a reconfigurable stream (a pipe someone replaced, a test capture)


def segment_hits_box(start: tuple[float, float], end: tuple[float, float],
                     box: tuple[float, float, float, float]) -> bool:
    """Whether the straight line from `start` to `end` touches a fractional box.

    Liang-Barsky slab clipping: the segment enters the box's x-range over some span
    of the line and its y-range over another, and it touches the box exactly when
    those two spans overlap inside the segment. Exact and about ten lines, which is
    why `forbids_path` does not sample points along the line instead."""
    (x0, y0), (x1, y1) = start, end
    bx, by, bw, bh = box
    lo, hi = 0.0, 1.0
    for origin, delta, low, high in ((x0, x1 - x0, bx, bx + bw),
                                     (y0, y1 - y0, by, by + bh)):
        if delta == 0:
            if not low <= origin <= high:
                return False        # parallel to this slab and outside it
            continue
        first, second = (low - origin) / delta, (high - origin) / delta
        lo, hi = max(lo, min(first, second)), min(hi, max(first, second))
        if lo > hi:
            return False
    return True


def is_fraction(at) -> bool:
    """Whether `at` is a pair of fractions of the client area, and so a point on a window.

    Lives here because this file defines that coordinate system - everything the harness
    aims at is a fraction, so that a game which picks a different resolution at launch does
    not invalidate every coordinate anyone recorded. It is shared with `describe.py`, which
    refuses to write a non-fraction into a map, and `mission.py`, which refuses to aim at
    one an older map already holds; three copies of this rule would be three chances for
    one of them to be laxer than `point`.

    Tolerant of any shape rather than assuming a pair of numbers, because every caller is
    checking something a model chose: a string, a dict or a three-element list all have to
    come back False and be reported, not raise inside the check meant to catch them."""
    try:
        x, y = at
        return 0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0
    except (TypeError, ValueError):
        return False


# --- windows ----------------------------------------------------------------

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


def window_alive(hwnd: int) -> bool:
    """Whether this exact window still exists and is visible.

    Asked of a handle rather than of a title, because a title is a weak identity: two
    instances of a game share one, a game that appends a score to its own changes it,
    and a game whose window is not named after it never had one to search for. The
    handle is what was actually driven."""
    probe.user32.IsWindow.argtypes = [ctypes.c_void_p]
    probe.user32.IsWindow.restype = ctypes.c_int
    return bool(probe.user32.IsWindow(hwnd) and probe.user32.IsWindowVisible(hwnd))


def is_foreground(hwnd: int) -> bool:
    probe.user32.GetForegroundWindow.restype = ctypes.c_void_p
    probe.user32.GetForegroundWindow.argtypes = []
    return probe.user32.GetForegroundWindow() == hwnd


def process_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True, check=False)
    return str(pid) in out.stdout


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_image(pid: int) -> Path | None:
    """The executable behind a PID, or None if it cannot be read.

    Here to answer "did the program I launched produce this window?" for a launcher, and
    the reason it is the *image* rather than the process tree is a measurement. On the
    launcher-based game this was written for, the game's parent PID pointed at a launcher
    process that had already exited by the time the game had a window, so there is no
    chain left to walk from our own PID to the game's. The image path survives that: the
    game the launcher started sat inside the launcher's own install folder, which is a
    relation that can still be checked minutes later.

    `PROCESS_QUERY_LIMITED_INFORMATION` is the whole reason this works unelevated - the
    older `PROCESS_QUERY_INFORMATION` is refused for another user's or a protected
    process, and a WMI query for the same field came back with the path blank."""
    _kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        _kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong)]
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buf))
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return Path(buf.value)
    finally:
        _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        _kernel32.CloseHandle(handle)


GW_OWNER = 4


def window_owner(hwnd: int) -> int:
    """The window this one belongs to, or 0 if it stands on its own.

    A game's own dialogs, message boxes and popups are top-level windows and turn up in
    the same enumeration as the game, so counting windows cannot tell "the game opened a
    settings dialog" apart from "a launcher opened the game". The owner can: a dialog is
    owned by the window that raised it, and a program started by a launcher is not owned
    by anything."""
    probe.user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    probe.user32.GetWindow.restype = ctypes.c_void_p
    return probe.user32.GetWindow(hwnd, GW_OWNER) or 0


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen, unique = set(), []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def steam_roots() -> list[Path]:
    """Where Steam itself is installed, asked of the machine rather than assumed.

    The default location is a guess about somebody else's disk: Steam is routinely put on
    a second drive, and then a resolver that only knows `C:\\Program Files (x86)` reports
    that none of their games are installed. The registry is where Steam records the
    answer, under both hives because a per-user install writes one and a machine-wide
    install the other. The two usual paths stay on as a fallback for a machine whose
    registry entry has been cleaned up but whose install still works."""
    roots: list[Path] = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                for field in ("SteamPath", "InstallPath"):
                    try:
                        roots.append(Path(winreg.QueryValueEx(handle, field)[0]))
                    except OSError:
                        continue
        except OSError:
            continue
    roots += [Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")]
    return _unique_paths(roots)


def steam_libraries() -> list[Path]:
    """Every Steam library root on this machine. Games move between libraries when
    a drive fills up, so a hardcoded path works right up until it doesn't."""
    roots: list[Path] = []
    for base in steam_roots():
        # Both locations, because the file moved between Steam versions and an older
        # install still keeps its library list under `config/`.
        for vdf in (base / "steamapps" / "libraryfolders.vdf",
                    base / "config" / "libraryfolders.vdf"):
            if not vdf.exists():
                continue
            roots.append(base)
            text = vdf.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                roots.append(Path(match.group(1).replace("\\\\", "\\")))
    return _unique_paths(roots)


def steam_installs() -> list[Path]:
    """Every installed game directory across every library."""
    return sorted((d for root in steam_libraries()
                   for d in (root / "steamapps" / "common").glob("*") if d.is_dir()),
                  key=lambda d: d.name.lower())


def _squash(text: str) -> str:
    """Lowercase alphanumerics only, so 'Tile Tale', 'tile_tale' and 'TileTale' are
    one name. Punctuation and spacing are how the same title is written differently
    by a store page, a directory and an executable."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# The two Start menus, machine-wide and per-user. Not a substitute for the Steam scan but
# the other half of the same question: Steam knows what Steam installed, and the Start menu
# is where everything else on a Windows machine says what it is called. A game that came
# from its publisher's own launcher exists in exactly one of these places.
START_MENUS = (Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
               / "Microsoft/Windows/Start Menu/Programs",
               Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs")


def shortcut_target(link: Path) -> Path | None:
    """The executable a `.lnk` points at, or None if it does not resolve to a local one.

    Parsed rather than resolved through the shell, because the alternative is a COM call
    or a PowerShell subprocess per shortcut and there are a hundred of them. Only the two
    fields that matter are read: a shell link stores its target as a base path plus a
    suffix, and joining them is required rather than optional - a shortcut written on a
    machine with a network view of its own drive stores `C:\\Users\\` in the first and the
    rest of the path in the second, so reading the base alone finds a directory that is
    not a program and quietly concludes the game is not installed."""
    try:
        data = link.read_bytes()
    except OSError:
        return None
    if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C:
        return None
    flags = struct.unpack_from("<I", data, 20)[0]
    at = 0x4C
    if flags & 0x01:                                    # HasLinkTargetIDList
        at += 2 + struct.unpack_from("<H", data, at)[0]
    if not flags & 0x02 or at + 28 > len(data):         # HasLinkInfo
        return None
    header = struct.unpack_from("<I", data, at + 4)[0]
    # The Unicode pair exists only in the longer header; where it does, it is the one to
    # trust, because the ANSI fields are written in the machine's code page and a title
    # with a character outside it arrives mangled.
    wide = header >= 0x24
    base_at, suffix_at = ((at + 28, at + 32) if wide else (at + 16, at + 24))
    parts = []
    for field in (base_at, suffix_at):
        offset = struct.unpack_from("<I", data, field)[0]
        if not offset:
            parts.append("")
            continue
        start = at + offset
        if wide:
            end = data.index(b"\x00\x00", start)
            parts.append(data[start:end + 1].decode("utf-16-le", "replace"))
        else:
            parts.append(data[start:data.index(b"\x00", start)].decode("mbcs", "replace"))
    target = Path("".join(parts))
    return target if target.suffix.lower() == ".exe" and target.exists() else None


# Shortcut names that are about a program rather than being one. Every installer drops
# some of these beside what it installed, and they are worse than noise in the pool: they
# sit next to the game, they are named after it, and so they match the game's name as well
# as the game does. Matched on the squashed name (see `_squash`).
NOT_THE_PROGRAM = ("uninstall", "readme", "manual", "documentation", "changelog",
                   "releasenotes", "license", "eula", "website", "homepage", "support",
                   "troubleshoot")


def shortcut_games() -> list[tuple[str, Path]]:
    """Every Start-menu shortcut that plausibly starts a program, as (name, exe).

    Named by the shortcut rather than by the executable on purpose: the shortcut carries
    the title a person reads, which is the name they will type, while the binary is
    frequently named after the engine or abbreviated past recognition.

    Filtered at both ends - the shortcut's own name against `NOT_THE_PROGRAM`, its target
    against `NOT_THE_GAME` - because an uninstaller shares a name with the game it removes
    and would otherwise be a legitimate answer to being asked for that game by name."""
    found: list[tuple[str, Path]] = []
    for menu in START_MENUS:
        if not menu.exists():
            continue
        for link in menu.rglob("*.lnk"):
            if any(bad in _squash(link.stem) for bad in NOT_THE_PROGRAM):
                continue
            exe = shortcut_target(link)
            if exe is None or any(bad in _squash(exe.stem) for bad in NOT_THE_GAME):
                continue
            found.append((link.stem, exe))
    return found


def installed_games() -> list[tuple[str, str, Path]]:
    """Everything on this machine that might be a game, as (name, source, where).

    Two sources pooled into one list, because Windows has no single register of what is
    installed. Steam knows its own libraries and nothing else; the Start menu is where
    every other installer writes down what it put on the machine and what it is called.
    A game bought from its publisher rather than from Steam appears only in the second,
    and a resolver that reads only the first reports it as not installed - which is a
    much more misleading answer than "I cannot find it".

    `where` means different things per source and deliberately so: a directory to search
    for Steam, because a Steam install is a folder full of exes and picking one is a
    guess; the exe itself for a shortcut, because the shortcut already *is* somebody's
    answer to that question and second-guessing it would be strictly worse.

    Deduplicated by squashed name with Steam winning. A game installed both ways is one
    game, and the Steam copy is the one whose folder can be inspected."""
    found = [(d.name, "steam", d) for d in steam_installs() if has_game_exe(d)]
    seen = {_squash(name) for name, _, _ in found}
    for name, exe in shortcut_games():
        if _squash(name) not in seen:                   # both Start menus, and Steam first
            seen.add(_squash(name))
            found.append((name, "shortcut", exe))
    return found


# How many names an unmatched `--game` lists back. There are a hundred-odd Start-menu
# shortcuts on an ordinary machine and most are not games, so the full listing buries the
# answer rather than giving it.
LISTING_CAP = 40


def find_game(game: str) -> tuple[str, Path, list[Path]]:
    """What to launch for a game named loosely: its display name, its exe, the runners-up.

    Matching is deliberately forgiving - exact squashed name, then prefix, then
    substring - because the point is that a person types the name they know the game by.
    When it is ambiguous the error names every candidate and where each came from rather
    than picking one: launching the wrong program and driving it blind is worse than
    being asked again."""
    pool = installed_games()
    wanted = _squash(game)
    if not wanted:
        raise SystemExit("--game needs a name")
    for rank in (lambda n: n == wanted, lambda n: n.startswith(wanted),
                 lambda n: wanted in n):
        hits = [entry for entry in pool if rank(_squash(entry[0]))]
        if len(hits) == 1:
            name, source, where = hits[0]
            if source == "steam":
                exe, runners_up = find_game_exe(where)
                return name, exe, runners_up
            return name, where, []
        if len(hits) > 1:
            raise SystemExit(f"{game!r} matches {len(hits)}: "
                             + ", ".join(f"{n} ({'Steam' if s == 'steam' else 'Start menu'})"
                                         for n, s, _ in hits))
    listing = [f"{n} ({'Steam' if s == 'steam' else 'Start menu'})" for n, s, _ in pool]
    raise SystemExit(f"no installed game matches {game!r}. Found:\n  "
                     + "\n  ".join(sorted(listing, key=str.lower)[:LISTING_CAP])
                     + (f"\n  ... and {len(listing) - LISTING_CAP} more"
                        if len(listing) > LISTING_CAP else ""))


# Executables that ship next to a game and are not the game. Matched on the squashed
# name so `UnityCrashHandler64.exe` and `unitycrashhandler.exe` are the same entry.
NOT_THE_GAME = ("crashhandler", "crashreport", "unins", "vcredist", "dxsetup",
                "directx", "dotnet", "oalinst", "redist", "setup", "config",
                "benchmark", "server", "dedicated")


def plausible_exes(install: Path) -> Iterator[Path]:
    """Every exe under a directory that could be the game itself, lazily."""
    return (p for p in install.rglob("*.exe")
            if not any(bad in _squash(p.stem) for bad in NOT_THE_GAME))


def has_game_exe(install: Path) -> bool:
    """Whether a Steam directory holds anything that could be started.

    Measured on this machine: 23 directories under `steamapps/common`, of which 12 hold no
    exe at all - Steam leaves the folder behind when a game is uninstalled, and two of them
    ('Steam Controller Configs', 'Steamworks Shared') were never a game. Without this test
    the pool offers a dozen games that are not installed, and asking for one by name answers
    'no plausible executable under ...' instead of 'that is not installed, here is what is'.
    Cheap despite the recursive walk, because it stops at the first hit: the directories that
    have to be walked to the end are the empty ones."""
    return next(plausible_exes(install), None) is not None


def find_game_exe(install: Path) -> tuple[Path, list[Path]]:
    """The executable most likely to *be* the game, and the runners-up.

    Returned as a pair because this is a guess and a guess should be inspectable: the
    session log prints what was chosen and what it was chosen over, which is the only
    way a wrong pick is diagnosable rather than mysterious. Ranked by name resemblance
    to the directory first and size second - a game's own binary is usually named
    after it, and where it is not, the real game is rarely the smallest exe in the
    folder. Installers and crash handlers are excluded by name because they are the
    ones that resemble a game most: they sit in the same directory and some are large.
    """
    candidates = list(plausible_exes(install))
    if not candidates:
        raise SystemExit(f"no plausible executable under {install}")
    wanted = _squash(install.name)

    def rank(path: Path) -> tuple[int, int, int]:
        name = _squash(path.stem)
        resemblance = 2 if name == wanted else 1 if wanted in name or name in wanted else 0
        # Depth matters: a game's binary sits at the top of its install, while the
        # things that merely look like it live in subdirectories.
        return (resemblance, -len(path.relative_to(install).parts), path.stat().st_size)

    ordered = sorted(candidates, key=rank, reverse=True)
    return ordered[0], ordered[1:4]


def visible_windows() -> dict[int, str]:
    """Every visible titled top-level window, by handle. Used to tell which window a
    launch produced, which is the only general way to find a game's window: its title
    is frequently not its name, and requiring the caller to know it in advance is the
    per-game calibration this experiment exists to avoid."""
    found: dict[int, str] = {}

    @probe.WNDENUMPROC
    def callback(hwnd, _lparam):
        if probe.user32.IsWindowVisible(hwnd):
            length = probe.user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                probe.user32.GetWindowTextW(hwnd, buf, length + 1)
                found[hwnd] = buf.value
        return True

    probe.user32.EnumWindows(callback, 0)
    return found


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
    defaults that are honest starting points, not universal truths - and both are
    written back by `calibrate.py` from a session's own transitions, so a second sweep
    of the same game starts from measurements instead of from these.

    `window_title` is an *output* of the first launch, not an input to it. A game's
    window is frequently not titled its name, so requiring the title up front would
    make every new game a hand-editing job - which is the cost this experiment exists
    to remove. It is kept because it is the only way to re-attach to a game that is
    already running.
    """
    name: str
    window_title: str = ""
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

    # The process image a window MUST belong to for it to be this game, as
    # (file name, a folder it must sit under). Empty means "no such constraint".
    #
    # This exists for the target that has an owning process but no launchable exe:
    # a Google Play Games title is drawn by `crosvm.exe` inside the Play Games
    # install and started through a shell URI, so `exe` is necessarily empty (see
    # experiments/android-bot/attach.py). With `exe` empty, `_belongs` falls through
    # to comparing *titles*, and the title of a Play Games game is its own name -
    # which is also the name of any editor tab or browser tab that happens to have a
    # file about the game open. That is not hypothetical: a VS Code window showing
    # `clash-royale-wiki.html` qualified as a usurping window of Clash Royale and
    # was adopted, and an adopted window is one this harness sends drags into.
    #
    # Separate from `exe` on purpose, because the two answer different questions and
    # conflating them is what `attach.py` warns about: `exe` is "what to start", and
    # pointed at an emulator it would boot a bare VM. This is only ever "what to
    # believe", and nothing launches it.
    owner_image: tuple[str, str] = ("", "")

    def resolve_exe(self) -> Path | None:
        path = Path(self.exe) if self.exe else None
        return path if path and path.exists() else None

    def disowns(self, pid: int | None) -> str:
        """Why `pid` cannot be this game's process, or "".

        Fails closed: with a constraint set, a process whose image cannot be read at
        all is rejected rather than given the benefit of the doubt. The window this
        guards against is by definition somebody else's, and the cost of a wrong
        rejection is a refusal to hand over, while the cost of a wrong acceptance is
        input sent into another program.
        """
        wanted, under = self.owner_image
        if not wanted:
            return ""
        image = process_image(pid) if pid is not None else None
        if image is None:
            return "its process image cannot be read"
        if image.name.lower() != wanted.lower():
            return f"it belongs to {image.name}, not {wanted}"
        if under and Path(under) not in image.parents:
            return f"its {image.name} is not under {under}"
        return ""

    def forbids(self, fx: float, fy: float) -> str | None:
        """The reason this point is off limits, or None. Fractional so it survives
        the resolution change every launch of a fullscreen game performs."""
        for entry in self.denylist:
            x, y, w, h = entry["box"]
            if x <= fx <= x + w and y <= fy <= y + h:
                return entry.get("why", "denylisted")
        return None

    def forbids_path(self, start: tuple[float, float],
                     end: tuple[float, float]) -> str | None:
        """The reason a drag between these two points is off limits, or None.

        A drag is the one input that touches somewhere it was not aimed at. It holds
        the button down along a line, so a drag whose ends are both clear can still
        pass straight through a denylisted box with the button held - which on a game
        whose forbidden box is a quit button is the exact thing the box exists to
        prevent. Checking the ends only would leave the hard floor with a hole in the
        middle of it.

        An exact segment-rectangle test rather than samples along the line, because
        the sampling density would become the real safety limit: coarse enough to be
        cheap is coarse enough to step over a small box."""
        for entry in self.denylist:
            if segment_hits_box(start, end, entry["box"]):
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
        # What was on screen before this launch, so a window that appears later can be
        # told from one that was always there. Not a filter on its own - see
        # `successor_window`, which has to work when attaching to a game that is already
        # running and therefore predates everything this process knows about.
        self._before: set[int] = set()
        # Windows handed over from: a launcher this session has moved past. Kept so that
        # shutdown closes them, and so that the window being driven and the one it
        # replaced can never trade places back and forth.
        self.sidelined: list[int] = []
        # How many handovers have happened. Read by the session so that the action which
        # caused one can be credited with it - see `Recon.step`. A count rather than a
        # flag because nothing here knows when the session last looked.
        self.handovers = 0
        # Processes already reported as "named like the game but not the game", so the
        # note is printed once each rather than on every readiness check.
        self._disowned_said: set[int] = set()

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
        self.attach_or_launch()
        self.ensure_readable()

    def attach_or_launch(self) -> None:
        """Produce a window, without waiting for it to be ready.

        The half of `start` that `calibrate.py` needs on its own: how long a game takes
        to settle is precisely what the wait has to be told, so measuring it cannot
        happen behind the wait. Every other caller wants both halves and should use
        `start`."""
        existing = self.running_window()
        if existing:
            hwnd, title, how = existing
            self.hwnd, self.pid = hwnd, window_pid(hwnd)
            self.target.window_title = title or self.target.window_title
            # Everything except the window attached to counts as pre-existing, which for
            # this path is nearly the whole desktop. The successor check does not depend
            # on it: attaching can land on a launcher whose game is already up, and the
            # game window is then older than this process rather than newer.
            self._before = set(visible_windows()) - {hwnd}
            self.say(f"attached to {self.target.name}: window {hwnd}, pid {self.pid} "
                     f"({how})")
        else:
            self._launch()

    def running_window(self) -> tuple[int, str, str] | None:
        """A window of this game that is already open, with how it was recognized.

        Three ways, and the order matters because only the first is identity. A window
        whose process *is* the file that would have been launched is the game, whatever it
        calls itself - which is what makes attaching work for a game nobody has run here
        before, where there is no remembered title to search for and the alternative is
        launching a second copy over the first.

        The remembered title comes second and third, exact before substring. Substring is
        wanted (a game that appends a score or a level to its title still resolves) and is
        also how it goes wrong: one title is often a prefix of another on the same machine,
        so a remembered name can find a launcher instead of the game, or one instance of a
        series instead of the one asked for. Preferring an exact hit costs one pass over a
        list that is already in memory.

        A title match is additionally required to come from the game's own install, and
        that requirement is the most important line in this method. Without it, asking for
        Mitosis on a machine where an editor happened to be showing `mitosis-last-run.log`
        attached to the editor: the remembered title `Mitosis` is a substring of that
        window's, nothing downstream re-checks what it is driving, and a session then spent
        a minute sending clicks and keypresses into somebody's editor. Nothing about that
        is specific to editors - any window naming a file, a folder or a branch after the
        game matches - and none of the safety layers can catch it, because they are about
        which action is allowed on a screen and not about whether the screen is the game's.
        The check is the same relation `_belongs` uses: the window's process is the file
        that would have been launched, or lives under its folder, which keeps the case this
        fallback exists for - a launcher whose game window belongs to a differently-named
        executable beside it. When an exe could not be resolved at all there is nothing to
        check against and the title is the only evidence there is.

        Owned windows are skipped - those are dialogs belonging to something else - but
        size deliberately is not checked: a fullscreen game minimizes itself when it loses
        focus, reports a 0x0 client rect while it is down, and is exactly the running
        instance this is meant to find."""
        exe = self.target.resolve_exe()
        needle = self.target.window_title.lower()
        exact: tuple[int, str, str] | None = None
        loose: tuple[int, str, str] | None = None
        strangers: list[str] = []
        for hwnd, title in visible_windows().items():
            if window_owner(hwnd):
                continue
            if exe is not None and process_image(window_pid(hwnd)) == exe:
                return hwnd, title, f"already running {exe.name}"
            if needle and needle in title.lower():
                if exe is not None and not self._same_install(window_pid(hwnd), exe):
                    strangers.append(title)
                    continue
                # The same rejection for a target that names its owning process instead
                # of an exe; without it the title alone decides, and the title is a name
                # any window with a file about the game open also carries.
                disowned = self.target.disowns(window_pid(hwnd))
                if disowned:
                    self.note(f"{title!r} matches the remembered title but {disowned}; "
                              f"not attaching to it")
                    continue
                if title.lower() == needle and exact is None:
                    exact = (hwnd, title, f"the remembered title {title!r}")
                elif loose is None:
                    loose = (hwnd, title, f"a title containing {self.target.window_title!r}")
        for title in strangers:
            # Loud even though it is the safe outcome. The window it declined is the one a
            # person would have to be told about, and the alternative to saying so is a
            # launch that looks unexplained.
            self.note(f"{title!r} matches the remembered title but belongs to another "
                      f"program, not to {exe.name}; not attaching to it")
        return exact or loose

    @staticmethod
    def _same_install(pid: int | None, exe: Path | None) -> bool:
        """Whether a window's process is the game's own, or something beside it.

        Unreadable images count as false: a window whose owner cannot be established is
        not a window to start sending input to."""
        if pid is None or exe is None:
            return False
        image = process_image(pid)
        return image is not None and (image == exe or exe.parent in image.parents)

    def _launch(self) -> None:
        exe = self.target.resolve_exe()
        if exe is None:
            raise WindowLost(f"cannot find an executable for {self.target.name!r}")
        self._before = set(visible_windows())
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
            hwnd = self._launched_window(self._before)
            if hwnd:
                self.hwnd, self.pid = hwnd, window_pid(hwnd)
                title = visible_windows().get(hwnd, "")
                # Remembered, not required: this is how a later attach finds the game
                # again, and how the sweep report says what it drove.
                self.target.window_title = title or self.target.window_title
                self.say(f"  window {hwnd} {title!r} after "
                         f"{time.perf_counter() - started:.1f}s (pid {self.pid})")
                return
            time.sleep(0.25)

        # No new window in 90 seconds does not have to mean failure. A second copy of a
        # game commonly exits after handing the foreground to the copy already running, so
        # the launch "produced" a window that has been there all along.
        already = self.running_window()
        if already is not None:
            hwnd, title, how = already
            self.hwnd, self.pid = hwnd, window_pid(hwnd)
            self.target.window_title = title or self.target.window_title
            self.note(f"{exe.name} opened no window of its own; it was {how}, so this "
                      f"session is driving the copy that was already up")
            return
        raise WindowLost(f"{exe.name} opened no visible window within "
                         f"{LAUNCH_TIMEOUT:.0f}s")

    def _launched_window(self, before: set[int]) -> int | None:
        """The window this launch produced, or None yet.

        Identified as "visible now, was not visible before, and big enough to be a
        game" rather than by title. Title matching cannot do this job in general: a
        game's window is often not named after the game, and PID matching cannot
        either, because a Steamworks title relaunches itself through Steam and the
        process that owns the window is not the one that was started. What is always
        true is that a launch adds a window that was not there a moment ago.

        Among several new windows the largest wins, which is how a splash loses to the
        game itself; a tie prefers the one whose title resembles the game's name.

        It cannot pick the game over a *launcher*, and nothing here could: this returns
        as soon as the launch has produced any window at all, and the window a launcher
        opens the game in does not exist yet - it arrives when something in the launcher
        is clicked, which may be minutes later. That is `successor_window`'s job."""
        candidates = []
        for hwnd, title in visible_windows().items():
            if hwnd in before:
                continue
            rect = client_rect_on_screen(hwnd)
            if rect[2] < MIN_GAME_WINDOW or rect[3] < MIN_GAME_WINDOW:
                continue
            resembles = _squash(self.target.name) in _squash(title)
            candidates.append((rect[2] * rect[3], resembles, hwnd))
        if not candidates:
            return None
        return max(candidates)[2]

    # -- the game is somewhere else -----------------------------------------

    def _past_the_launcher(self, pid: int | None) -> bool:
        """Whether this process is something the launched program *started*, rather than
        the launched program itself.

        The one asymmetry that keeps a handover from oscillating. A launcher and the game
        it starts are both plausible windows of the same install, so a rule phrased as
        "adopt a related window" would walk from the launcher to the game and straight
        back again. This one only points forward: it is true of the game and false of the
        launcher, and unreadable images count as false, because a handover that cannot be
        justified should not happen."""
        launched = self.target.resolve_exe()
        if pid is None or launched is None:
            return False
        image = process_image(pid)
        return image is not None and image != launched

    def _belongs(self, pid: int, title: str) -> str:
        """Why a window plausibly belongs to what was launched, or "".

        Four relations, strongest first, and the reason is returned rather than a boolean
        because it ends up in the session notes: a handover is a guess about somebody's
        desktop and it should be readable afterwards which evidence made it."""
        launched = self.target.resolve_exe()
        # First, because it outranks all four relations below including title evidence:
        # a target that names its owning process has said which process is the game, and
        # no amount of title resemblance overrides that.
        disowned = self.target.disowns(pid)
        if disowned:
            # Said out loud, but only for the window that would otherwise have been
            # adopted on its title alone - that is the near miss a person needs to know
            # about, and the rest are just the desktop. Deduped by process, because this
            # runs once per visible window per readiness check.
            named = _squash(self.target.name) in _squash(title)
            if named and pid not in self._disowned_said:
                self._disowned_said.add(pid)
                self.note(f"not adopting {title!r} even though its title names the game: "
                          f"{disowned}")
            return ""
        if self.pid and pid == self.pid:
            return "the same process"
        image = process_image(pid)
        if launched is not None and image is not None:
            if image == launched:
                return "another window of the program that was launched"
            if launched.parent in image.parents:
                # The strong case, and the one measured here: a launcher keeps the games
                # it installs inside its own folder, so the game's exe is under the
                # launcher's. It is not universal - a launcher can install anywhere - but
                # where it holds it is unambiguous.
                return f"{image.name}, under the launcher's own folder"
            # Readable, and neither of those: this is a different program, and the title is
            # not allowed to argue with that. It would - `_squash` reduces a title to its
            # letters and asks whether the game's name is in there, which is true of every
            # window naming a file or a folder after the game. An editor showing
            # `mitosis-last-run.log` qualified as a *promoted* window of Mitosis on exactly
            # this line, and a promoted window is one this harness starts typing into.
            return ""
        wanted, seen = _squash(self.target.name), _squash(title)
        if seen and (wanted in seen or seen in wanted):
            # Only reachable with no exe resolved or an unreadable image - a protected or
            # another user's process, where there is no image relation to be had and the
            # title is the only evidence there is.
            return f"its title {title!r} is the name of the game"
        return ""

    def successor_window(self) -> tuple[int, str, str] | None:
        """A window that has taken over from the one being driven, and why - or None.

        What a person calls "the game" is sometimes a launcher, and then the thing being
        driven is not the game: the launcher opens it in a separate window, of a separate
        process, when something in the launcher is clicked. Left unhandled that costs the
        whole session rather than one branch, and silently - the harness keeps asserting
        the foreground for the window it knows, so it goes on reading and mapping the
        launcher while the game it was pointed at sits in front of it, unread, being
        played by nobody.

        A candidate has to be unowned (`window_owner`, so a dialog the game raised is not
        mistaken for the game), big enough to be a game, and related to what was launched
        (`_belongs`). Beyond that there are two ways to qualify, because there are two
        ways this happens:

        - **promoted** - the launched program started another program and that one has
          the window. Directional, so it cannot bounce back to the launcher.
        - **usurped** - a window that did not exist when we launched now holds the
          foreground. This is the case where the launcher opens the game in its own
          process, where there is no second image to compare and the only evidence is
          that something new took the screen.

        Deliberately not decided on size. Measured on the launcher this was written for,
        the game's window is *narrower* than the launcher's and larger only by area - so
        "bigger is the game" would have been a rule that happened to work on one machine
        at one resolution."""
        if self.hwnd is None and not self.sidelined and not self._before:
            return None
        skip = set(self.sidelined) | ({self.hwnd} if self.hwnd else set())
        ahead = self._past_the_launcher(self.pid)
        best: tuple[int, int, str, str] | None = None
        for hwnd, title in visible_windows().items():
            if hwnd in skip or window_owner(hwnd):
                continue
            rect = client_rect_on_screen(hwnd)
            if rect[2] < MIN_GAME_WINDOW or rect[3] < MIN_GAME_WINDOW:
                continue
            pid = window_pid(hwnd)
            why = self._belongs(pid, title)
            if not why:
                continue
            promoted = not ahead and self._past_the_launcher(pid)
            usurped = hwnd not in self._before and is_foreground(hwnd)
            if not (promoted or usurped):
                continue
            reason = f"{why}; " + ("what was launched started it"
                                   if promoted else "it appeared and took the foreground")
            area = rect[2] * rect[3]
            if best is None or area > best[0]:
                best = (area, hwnd, title, reason)
        return None if best is None else (best[1], best[2], best[3])

    def adopt(self, hwnd: int, title: str, why: str) -> None:
        """Drive a different window from now on, and remember the one it replaced.

        The old window is not closed: a launcher is frequently the game's parent process
        and closing it can take the game down with it, which would turn a successful
        handover into a restart. It is sidelined instead - never a candidate again, and
        closed at shutdown after the game."""
        if self.hwnd is not None:
            self.sidelined.append(self.hwnd)
        self.handovers += 1
        self.hwnd, self.pid = hwnd, window_pid(hwnd)
        # Remembered for the next pass, which is the real payoff: a sweep that has been
        # through the launcher once attaches straight to the game and spends its whole
        # budget in it.
        self.target.window_title = title or self.target.window_title
        self.note(f"the game is in another window: {title!r} ({why}) - driving that "
                  f"instead, and closing the launcher at the end")

    def close(self) -> str:
        """Close everything this session opened: the game, then whatever it came from.

        The order is not incidental. A launcher is often the game's parent process, so
        closing it first is a kill dressed up as a shutdown - the game loses whatever it
        was in the middle of writing. Game first, launcher after."""
        parts = []
        if self.hwnd:
            parts.append(self._close_window(self.hwnd, self.pid))
        self.hwnd = None
        for hwnd in self.sidelined:
            if window_alive(hwnd):
                parts.append(f"{self._close_window(hwnd, window_pid(hwnd))} (the launcher)")
        self.sidelined = []
        return ", ".join(parts) or "nothing to close"

    def _close_window(self, hwnd: int, pid: int | None) -> str:
        """`WM_CLOSE`, then force. Which one was needed is a fact about the game and
        only one of them is safe to assume next time. Never by clicking an in-game
        exit control: going through the OS makes shutdown independent of whatever
        screen the session happened to end on."""
        probe.user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                              ctypes.c_void_p, ctypes.c_void_p]
        probe.user32.PostMessageW.restype = ctypes.c_int
        probe.user32.PostMessageW(hwnd, WM_CLOSE, None, None)

        deadline = time.monotonic() + CLOSE_TIMEOUT
        while time.monotonic() < deadline:
            if not window_alive(hwnd):
                if pid:
                    # The window is gone but the process may still be tearing down,
                    # and a relaunch that races the teardown gets two instances.
                    end = time.monotonic() + 5.0
                    while time.monotonic() < end and process_alive(pid):
                        time.sleep(0.2)
                return "WM_CLOSE"
            time.sleep(0.25)

        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
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
        is why they are separated here rather than collapsed into "unhealthy".

        A fifth thing is checked first, and it is not a failure: the game may have moved
        to a window this session has not been driving. It comes before the gone-check on
        purpose, because a launcher that exits once the game is up presents as exactly
        that failure, and relaunching then closes the game that was just started."""
        successor = self.successor_window()
        if successor is not None:
            self.adopt(*successor)

        if self.hwnd is None or not window_alive(self.hwnd):
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

        # A second look, and it is the one that usually finds the game. The window a
        # launcher opens arrives a couple of seconds after the click that asked for it -
        # 2.8s measured here - which is *inside* the focus fight that same click provoked,
        # not before it. Checked only at the top, the handover lands one action too late
        # and the map credits the next action with opening the game, which is a route that
        # does not work when it is replayed.
        #
        # Recursion rather than a loop because every adoption sidelines a window and so
        # shrinks the candidate pool: it cannot run away, and each pass through re-earns
        # the foreground and settling for the window it just switched to.
        if self.successor_window() is not None:
            return self.ensure_readable(allow_restart)
        return "ok"

    def _restart(self, why: str) -> str:
        """Relaunch and carry on. The accumulated ontology is deliberately *not*
        discarded: what was learned about the game is still true, and a session that
        threw it away on every crash would never get past the first screen."""
        self.restarts += 1
        self.note(f"restart {self.restarts}: {why}")
        # Unconditionally, even when the window being driven is already gone: a launcher
        # sidelined earlier can still be running, and relaunching over it produces two of
        # them, or a second game window nobody is watching.
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
        that has not begun rendering.

        "Held still" is measured the way every other comparison in this harness
        measures it - cells that moved by more than `cell_delta` - and not as byte
        equality, which is what this loop originally asked for. Byte equality is a
        gate strictly tighter than the screen identity test it exists to protect, so
        it fails on games the rest of the machinery handles perfectly: a title screen
        with one pulsing element leaves consecutive thumbnails unequal forever, the
        clock never reaches `startup_quiet`, and the session dies at the readiness
        timeout reporting "never rendered a settled frame" about a window that
        rendered fine. The tolerance is `screen_match`, which is already the measured
        boundary between "the same place" and "somewhere else": a startup transient
        crosses it by construction, idle animation does not, and no new per-game
        constant is needed to tell them apart."""
        started = time.monotonic()
        deadline = started + READY_TIMEOUT
        quiet = self.target.startup_quiet
        tolerance = int((1.0 - self.target.screen_match) * READY_COLS * READY_ROWS)
        rect = self.rect
        calm_since = time.monotonic()
        previous: bytes | None = None
        rescues = 0
        busiest = 0
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

            frame = self.grab(READY_COLS, READY_ROWS, verify=False)
            moved = 0 if previous is None else changed_cells(
                previous, frame, self.target.cell_delta)
            busiest = max(busiest, moved)
            if variance(frame) < FLAT_VARIANCE:
                calm_since, previous = time.monotonic(), None
            elif previous is not None and moved > tolerance:
                calm_since = time.monotonic()
            previous = frame

            if time.monotonic() - calm_since >= quiet:
                if rescues:
                    self.say(f"  settled after {rescues} restore(s)")
                return time.monotonic() - started
            time.sleep(0.3)
        # The churn is in the message because without it this line cannot be acted on:
        # one cell over the line is a screen_match cut too tight, and half the grid
        # moving is a game that animates its whole window and needs a different answer.
        self.say(f"  gave up waiting after {READY_TIMEOUT:.0f}s: rect "
                 f"{rect[2]}x{rect[3]}, {rescues} restore(s) attempted, never quiet "
                 f"for {quiet:.1f}s (busiest frame moved {busiest} of "
                 f"{READY_COLS * READY_ROWS} cells, tolerating {tolerance})")
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

    def capture(self, region=(0.0, 0.0, 1.0, 1.0),
                longest: int = 1400) -> tuple[bytes, int, int]:
        """The pixels of a region now, at up to `longest` on the longest side.

        Split from `save_png` because the two halves cost wildly different amounts of
        time and only one of them is urgent. This half is a GDI blit - measured in
        milliseconds - while encoding the PNG is a Python loop over every pixel, measured
        at 43ms for a 600x480 crop and 172ms for a full window. A caller that has to
        photograph a moment (a button with the mouse still down, which lasts 80ms) grabs
        here and writes the file afterwards."""
        left, top, width, height = self.rect
        fx, fy, fw, fh = region
        rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
        scale = min(1.0, longest / max(rw, rh))
        ow, oh = max(1, int(rw * scale)), max(1, int(rh * scale))
        return grab_thumbnail(left + int(width * fx), top + int(height * fy),
                              rw, rh, ow, oh), ow, oh

    @staticmethod
    def write_capture(path: Path, frame: tuple[bytes, int, int]) -> tuple[int, int]:
        pixels, width, height = frame
        path.parent.mkdir(parents=True, exist_ok=True)
        write_png(str(path), pixels, width, height)
        return width, height

    def save_png(self, path: Path, region=(0.0, 0.0, 1.0, 1.0), longest: int = 1400) -> tuple[int, int]:
        """Full-resolution capture, scaled so its longest side is `longest`.

        Detection runs on tiny thumbnails; the record does not. A 4K client
        downsampled to 1280x720 shrinks a small UI element to a few pixels - enough
        to see that it changed, not enough for anything, human or model, to say what
        it became."""
        return self.write_capture(path, self.capture(region, longest))

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
        """A fraction of the client area as a screen coordinate.

        The range check is here because this is the one place every hover and every click
        passes through, and a fraction outside it is not a point on this window at all.
        The arithmetic below is happy to compute one - `0.5, 697` lands thousands of pixels
        below the game, `mouse_move_to` sends the cursor there, Windows clamps it to the
        edge of the desktop, and the click arrives on whatever is sitting at that edge.
        That is the editor bug again with a different first move: input leaving the game.

        Not hypothetical, and not the explorer's doing - the explorer builds its own
        fractions from a grid. The annotator wrote `at: [697, 190]` into a real map,
        pixels where fractions belong, and a mission that clicked that control by label
        would have sent it here. Both ends are fixed too: `describe.py` refuses the
        out-of-range coordinate when the map is written, and `mission.py` refuses to aim
        at one that an older map already contains. This is the guarantee under those, and
        it holds for a caller nobody has written yet."""
        if not is_fraction((fx, fy)):
            raise ValueError(f"({fx}, {fy}) is not a fraction of the client area; "
                             f"both must be between 0 and 1")
        left, top, width, height = self.rect
        return left + int(width * fx), top + int(height * fy)

    def hover(self, fx: float, fy: float, settle: float = 0.20) -> None:
        """Move the cursor and nothing else - the least state-changing input that
        can still provoke a visible reaction, which makes it the only probe safe to
        sweep across a UI nobody has mapped yet."""
        mouse_move_to(*self.point(fx, fy))
        time.sleep(settle)

    def click(self, fx: float, fy: float, button: str = "left",
              modifiers: tuple[str, ...] = (),
              hover: float = 0.20, hold: float = 0.08, during=None) -> None:
        """Move, wait, press, hold, release - deliberately slow.

        Both pauses are load-bearing. A press arriving in the same input frame as
        the move gets hit-tested against wherever the pointer used to be, and a
        down/up pair sent in one batch can be sampled by a game that polls once a
        frame as no click at all. Both failures look identical from outside: the
        click is simply ignored, which reads as "not a button".

        `during` is called with the button still down, which is the only moment a
        pressed control can be seen: the frame everything else reads is taken after the
        release, by which time the control has sprung back. Whatever it costs is taken
        *out* of the hold rather than added to it, so the 80ms a game may be polling
        for is still 80ms - a capture that silently tripled the hold would be measuring
        a click nobody else sends. It is the caller's job to keep it short; `capture`
        exists for that and takes single-digit milliseconds, where writing the file
        would take fifty."""
        why = self.target.forbids(fx, fy)
        if why:
            raise PermissionError(f"({fx:.3f}, {fy:.3f}) is denylisted: {why}")
        with self.holding(*modifiers):
            mouse_move_to(*self.point(fx, fy))
            time.sleep(hover)
            down, up = BUTTON_FLAGS[button]
            send_input(mouse_input(down))
            started = time.monotonic()
            if during is not None:
                during()
            time.sleep(max(0.0, hold - (time.monotonic() - started)))
            send_input(mouse_input(up))

    def drag(self, start: tuple[float, float], end: tuple[float, float],
             button: str = "left", modifiers: tuple[str, ...] = (),
             hover: float = 0.20, during=None) -> None:
        """Press at one point, travel to another with the button held, release.

        The travel is the reason this cannot be built out of `click` and `hover`. A
        drag that jumps straight from one point to the other sends a single move
        event, and almost nothing responds to it: a camera pans by integrating motion,
        a slider follows the pointer frame by frame, and a drag-and-drop UI decides
        what is being carried from the moves that arrive *after* the press. One jump
        looks to all three like a press and a release somewhere else.

        `DRAG_SETTLE` at the far end before the release is load-bearing for the
        opposite reason: a UI that drops what it is carrying on button-up reads the
        position it has, and releasing in the same input frame as the last move is
        how a drop lands one move short of where it was aimed.

        The denylist is checked against the whole path, not the two ends - see
        `Target.forbids_path`. Both ends are checked too, and separately, so the
        refusal message can say which end was the problem when it is one of them.

        `during` fires with the button still down at the far end, which is the drag's
        equivalent of a pressed control: the close-up is aimed at where the drag
        *started*, so what that frame shows is whether the thing being dragged has
        left its origin - the one question a before/after pair cannot answer, because
        by the after frame the drag has finished either way."""
        for label, (fx, fy) in (("start", start), ("end", end)):
            why = self.target.forbids(fx, fy)
            if why:
                raise PermissionError(
                    f"a drag {label} of ({fx:.3f}, {fy:.3f}) is denylisted: {why}")
        why = self.target.forbids_path(start, end)
        if why:
            raise PermissionError(
                f"a drag from ({start[0]:.3f}, {start[1]:.3f}) to "
                f"({end[0]:.3f}, {end[1]:.3f}) passes through a denylisted box: {why}")

        with self.holding(*modifiers):
            mouse_move_to(*self.point(*start))
            time.sleep(hover)
            down, up = BUTTON_FLAGS[button]
            send_input(mouse_input(down))
            time.sleep(DRAG_GRAB)
            for step in range(1, DRAG_STEPS + 1):
                fraction = step / DRAG_STEPS
                mouse_move_to(*self.point(
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction))
                time.sleep(DRAG_GLIDE)
            time.sleep(DRAG_SETTLE)
            if during is not None:
                during()
            send_input(mouse_input(up))

    def scroll(self, fx: float, fy: float, notches: int,
               horizontal: bool = False, modifiers: tuple[str, ...] = (),
               hover: float = 0.20) -> None:
        """Turn the wheel over a point. Positive is away from the user - up, or right.

        Sent as `notches` separate events rather than one event of `notches * 120`,
        because the two are not the same input. A list that advances one row per wheel
        message advances one row for either, so a single large delta is a scroll a game
        may round back down to one step - and the point of scrolling three notches is
        to be sure something moved at all.

        The cursor is moved first and given the same settle a click gets: a wheel
        message goes to whatever is under the pointer, so a wheel sent without the
        move scrolls whatever the game still thinks the pointer is over.

        The denylist applies, though nothing about a wheel is destructive on its own.
        A hand-written box means "do not put input into this part of the window", and
        the cost of reading it that broadly is a scroll nobody needed; the cost of
        reading it narrowly is discovering the exception the hard way."""
        why = self.target.forbids(fx, fy)
        if why:
            raise PermissionError(f"({fx:.3f}, {fy:.3f}) is denylisted: {why}")
        if not notches:
            raise ValueError("a scroll of no notches is not an input")
        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        step = WHEEL_DELTA if notches > 0 else -WHEEL_DELTA
        with self.holding(*modifiers):
            mouse_move_to(*self.point(fx, fy))
            time.sleep(hover)
            for index in range(abs(notches)):
                send_input(mouse_input(flag, data=step))
                if index + 1 < abs(notches):
                    time.sleep(SCROLL_GAP)

    @staticmethod
    def _vk(key: str) -> int:
        vk = VK_NAMES.get(key.lower()) or (ord(key.upper()) if len(key) == 1 else None)
        if vk is None:
            raise ValueError(f"unknown key {key!r}")
        return vk

    def press(self, key: str) -> None:
        """Scancode input, via `probe.key_input`: game runtimes routinely read the
        keyboard at a level where a virtual-key-only synthetic event is invisible,
        and the arrow cluster needs its extended flag or it arrives as the numpad."""
        vk = self._vk(key)
        send_input(key_input(vk, keyup=False), key_input(vk, keyup=True))

    def hold(self, key: str) -> None:
        """Send a key down and leave it down. Prefer `holding`."""
        send_input(key_input(self._vk(key), keyup=False))

    def release(self, key: str) -> None:
        send_input(key_input(self._vk(key), keyup=True))

    @contextmanager
    def holding(self, *keys: str) -> Iterator[None]:
        """Hold keys down for the duration of the block - how a chord is sent.

        `press` cannot express one: it sends down and up in a single batch, so nothing
        can arrive between them, and shift+scroll or ctrl+click are unreachable by
        construction rather than by omission.

        The `finally` is the whole reason this is a context manager and not two calls.
        A modifier left down does not fail visibly - it silently changes the meaning
        of every input for the rest of the session, so a keypress that raises in the
        middle of a chord would turn into a run whose remaining hundred actions were
        all secretly shift-something. Released in reverse order, and each release
        attempted even if an earlier one throws, because a half-released chord is the
        same failure."""
        unknown = [k for k in keys if k not in MODIFIERS]
        if unknown:
            # Refused rather than held, because anything can be held down and the failure
            # of holding the wrong thing is silent: `enter` held for the duration of a
            # block is a key repeat, not a chord.
            raise ValueError(f"{', '.join(unknown)} cannot be held as a modifier; "
                             f"this harness holds {', '.join(MODIFIERS)}")
        for key in keys:
            self.hold(key)
        try:
            yield
        finally:
            for key in reversed(keys):
                try:
                    self.release(key)
                except Exception as error:              # noqa: BLE001
                    self.note(f"could not release {key}: {error}")


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


# --- finding the edges of one control ---------------------------------------
#
# Everything above this line measures *change*: two frames compared, and the cells that
# differ. That answers "did something happen here" and it cannot answer "how big is this
# button", because a button that is not being pressed does not change and a button that
# is changes only where its highlight fell.
#
# So this reads a single frame, and the only thing it knows is that a control sits on a
# background: a plate, a bar, a panel, whatever the game draws behind it. Given a patch
# with some margin around the control, the margin is the background, and the control is
# whatever in the patch is not that colour. That is a weak assumption stated plainly
# rather than a strong one hidden - it holds for a button on a panel and a line of text on
# a plate, and it fails for a control drawn in its own background colour or one flush
# against a neighbour of the same shade. Both failures are detectable from the result
# (nothing found, or content edge to edge), and the caller reports them rather than
# quietly shipping a rectangle nobody measured.

INK_DELTA = 18           # per-channel-mean distance from the background that counts as
                         # part of the control. Below a dozen this picks up JPEG-ish
                         # gradient noise in a panel; far above it, dark text on a dark
                         # plate stops registering. Measured on this game's own crops:
                         # its button plates sit 40-90 from their panels.
INK_FRACTION = 0.06      # of a row's length, before that row counts as containing the
                         # control. Not one pixel: an antialiased edge, a drop shadow or
                         # a single stray highlight would otherwise set the bound, and
                         # the bound is what a tap is aimed at.


def background_colour(bgra: bytes, width: int, height: int) -> tuple[int, int, int]:
    """The commonest colour in the outermost ring of a patch, as BGR to 16 levels.

    The ring rather than the whole patch, because the middle of the patch is meant to be
    the thing being measured. The mode rather than the mean, because the mean of a button
    on a gradient is a colour that appears nowhere in the picture and sits about equally
    far from both."""
    tally: dict[tuple[int, int, int], int] = {}
    ring = [(x, y) for x in range(width) for y in (0, height - 1)]
    ring += [(x, y) for y in range(1, height - 1) for x in (0, width - 1)]
    for x, y in ring:
        i = (y * width + x) * 4
        key = (bgra[i] // 16, bgra[i + 1] // 16, bgra[i + 2] // 16)
        tally[key] = tally.get(key, 0) + 1
    b, g, r = max(tally, key=lambda k: tally[k])
    return b * 16 + 8, g * 16 + 8, r * 16 + 8


def _span(counts: list[int], least: int) -> tuple[int, int] | None:
    """First and last index whose count reaches `least`, as a half-open span."""
    hits = [i for i, n in enumerate(counts) if n >= least]
    return (hits[0], hits[-1] + 1) if hits else None


def content_box(bgra: bytes, width: int, height: int, delta: int = INK_DELTA,
                fraction: float = INK_FRACTION) -> tuple[int, int, int, int] | None:
    """The bounding box of whatever is not the background, in pixels of this patch.

    Half-open, `(left, top, right, bottom)`. `None` when the patch is uniform enough that
    no row and no column reaches the ink threshold - which is not an error but the
    measurement "there is no control here", and is how a box aimed at empty panel is told
    apart from one aimed at a button.

    A span that runs the full width or the full height of the patch is returned as such,
    and it means the opposite: the thing overflows the patch, so the patch was too small
    to have measured its edge. Only the caller knows how much margin it asked for, so only
    the caller can tell those apart - see `Recon.snap_box`."""
    if width < 3 or height < 3:
        return None
    b, g, r = background_colour(bgra, width, height)
    rows, cols = [0] * height, [0] * width
    for y in range(height):
        base = y * width * 4
        for x in range(width):
            i = base + x * 4
            if (abs(bgra[i] - b) + abs(bgra[i + 1] - g)
                    + abs(bgra[i + 2] - r)) // 3 > delta:
                rows[y] += 1
                cols[x] += 1
    vertical = _span(rows, max(1, int(fraction * width)))
    horizontal = _span(cols, max(1, int(fraction * height)))
    if vertical is None or horizontal is None:
        return None
    return horizontal[0], vertical[0], horizontal[1], vertical[1]


if __name__ == "__main__":
    # Smoke test with no game knowledge and no exploration: can this thing take
    # ownership of a window, read it, and put it back?
    import argparse

    parser = argparse.ArgumentParser(description="Launch a target, read it, close it.")
    parser.add_argument("--game", required=True,
                        help="the game's name, as a person would write it")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    import target as targets

    set_dpi_aware()
    controller = Controller(targets.resolve(args.game))
    controller.start()
    log(f"client {controller.rect[2]}x{controller.rect[3]} at "
        f"({controller.rect[0]}, {controller.rect[1]})")
    log(f"variance {variance(controller.grab(64, 36)):.1f}, "
        f"settled in {controller.wait_stable():.2f}s")
    if args.keep_open:
        log("leaving it running (--keep-open)")
    else:
        log(f"closed via {controller.close()}")
