"""Smallest possible perceive/act probe against a live native game window:
touch the game with one synthetic input, and print whenever anything moves
on its screen.

This is the zero-infrastructure floor under the vision-driven option for a
GameMaker SUT (Tile Tale is `tile_tale.exe` + `data.win`, a native DirectX
window - no DOM, no accessibility tree, so Playwright and every
WebDriver-shaped tool are out). Before building any of the ontology/adapter
wiring, the two questions worth answering cheaply are: can we read pixels out
of that window at all, and does synthetic input reach it. Nothing here knows
about test cases, claims, or the engine.

Deliberately stdlib-only (ctypes over user32/gdi32) - adding mss/numpy/
pillow/pydirectinput to the user's environment isn't worth it to answer two
yes/no questions.

Two implementation choices worth knowing about:

  * Capture reads the *screen* DC clipped to the window's client rect, not
    the window DC. BitBlt/PrintWindow against a GPU-composited DirectX
    surface commonly returns solid black; compositing output does not. The
    tradeoff is that the window must be visible - anything occluding it gets
    captured instead, so --watch reports foreground state on every frame.

  * StretchBlt downsamples to a small thumbnail (default 64x36) inside GDI,
    with HALFTONE so each thumbnail pixel is an average of its source block
    rather than a point sample. That makes frame diffing a few thousand
    pure-Python byte comparisons instead of megabytes, and it doubles as a
    coarse motion map - which region moved, not just whether something did.

Run (detect only, touches nothing):
    py experiments/game-screen-probe/probe.py --watch

Run (touch, then watch what it did):
    py experiments/game-screen-probe/probe.py --touch move --watch
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
import zlib
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
HALFTONE = 4
DIB_RGB_COLORS = 0
SW_RESTORE = 9

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

# Keys whose scancode collides with the numeric keypad unless the extended
# flag rides along: arrows, the navigation cluster, numlock.
EXTENDED_VKS = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x90})

# Only what a first touch plausibly needs; extend as the game demands.
VK_NAMES = {
    "space": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("value", _INPUTUNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Explicit prototypes are not optional here: ctypes defaults every unknown
# return type to C int, which silently truncates the 64-bit HDC/HBITMAP
# handles these return, and the resulting capture fails or reads garbage.
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
# Superseded by SendInput, kept as a second path into the driver stack: a
# runtime that filters injected SendInput events may still accept these.
user32.mouse_event.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.StretchBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]


def set_dpi_aware() -> None:
    """Without this, a scaled display hands back logical coordinates while
    the screen DC is in physical pixels - the capture rect lands in the wrong
    place and silently grabs part of the desktop instead of the game."""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except (OSError, AttributeError):
        user32.SetProcessDPIAware()


def find_window(fragment: str) -> tuple[int, str]:
    """First top-level visible window whose title contains `fragment`
    (case-insensitive). Substring rather than FindWindowW's exact match so a
    game that appends a level or score to its title still resolves."""
    needle = fragment.lower()
    found: list[tuple[int, str]] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if needle in buf.value.lower():
            found.append((hwnd, buf.value))
            return False
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        raise SystemExit(f"No visible window with a title containing {fragment!r}.")
    return found[0]


def client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    """(left, top, width, height) of the client area in screen coordinates -
    client rather than window rect so the title bar and borders don't count
    as game screen and drag the motion map off-centre."""
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right, rect.bottom


def grab_thumbnail(left: int, top: int, width: int, height: int, tw: int, th: int) -> bytes:
    """Downsample the given screen region to tw x th and return it as raw
    top-down BGRA bytes."""
    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    # From screen_dc, NOT mem_dc: a fresh compatible DC holds a 1x1 monochrome
    # default bitmap, so asking it for a compatible bitmap yields 1-bpp black
    # and white and every frame diff collapses to two values.
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, tw, th)
    gdi32.SelectObject(mem_dc, bitmap)
    try:
        gdi32.SetStretchBltMode(mem_dc, HALFTONE)
        gdi32.SetBrushOrgEx(mem_dc, 0, 0, None)
        ok = gdi32.StretchBlt(mem_dc, 0, 0, tw, th, screen_dc, left, top, width, height, SRCCOPY)
        if not ok:
            raise OSError(f"StretchBlt failed (error {ctypes.get_last_error()})")

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = tw
        info.bmiHeader.biHeight = -th  # negative => top-down rows
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(tw * th * 4)
        rows = gdi32.GetDIBits(mem_dc, bitmap, 0, th, buf, ctypes.byref(info), DIB_RGB_COLORS)
        if rows != th:
            raise OSError(f"GetDIBits returned {rows} of {th} rows")
        return buf.raw
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


def write_png(path: str, bgra: bytes, width: int, height: int) -> None:
    """Minimal RGB PNG writer, so a frame can be eyeballed (or handed to a
    vision model) without pulling in Pillow for a format that zlib + struct
    already cover."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # per-row filter type 0 (None)
        row = bgra[y * width * 4:(y + 1) * width * 4]
        for x in range(0, len(row), 4):
            rows += bytes((row[x + 2], row[x + 1], row[x]))  # BGRA -> RGB

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)  # 8-bit, truecolour RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )
    Path(path).write_bytes(png)


def paste_bgra(dst: bytearray, dst_width: int, x: int, y: int,
               src: bytes, src_width: int, src_height: int) -> None:
    for row in range(src_height):
        start = (y + row) * dst_width * 4 + x * 4
        dst[start:start + src_width * 4] = src[row * src_width * 4:(row + 1) * src_width * 4]


def contact_sheet(cells: list[bytes], cell_width: int, cell_height: int,
                  cols: int, gap: int = 6) -> tuple[bytes, int, int]:
    """Tile the captured cell buffers into one image. Built from the buffers
    already in memory rather than by re-reading the PNGs back off disk, so it
    needs no decoder - and it makes a grid slice checkable at a glance instead
    of one file at a time."""
    rows = (len(cells) + cols - 1) // cols
    width = cols * cell_width + (cols + 1) * gap
    height = rows * cell_height + (rows + 1) * gap
    sheet = bytearray(b"\x28\x28\x28\xff" * (width * height))  # dark grey gutter
    for index, cell in enumerate(cells):
        x = gap + (index % cols) * (cell_width + gap)
        y = gap + (index // cols) * (cell_height + gap)
        paste_bgra(sheet, width, x, y, cell, cell_width, cell_height)
    return bytes(sheet), width, height


def diff_cells(before: bytes, after: bytes, tw: int, th: int, threshold: int) -> list[tuple[int, int, int]]:
    """Thumbnail pixels whose mean BGR change exceeds `threshold`, as
    (col, row, delta). Mean over the three channels keeps a bright flash in
    one channel from counting the same as a real content change, and the
    alpha byte is skipped - GDI leaves it undefined here."""
    moved = []
    for row in range(th):
        base = row * tw * 4
        for col in range(tw):
            i = base + col * 4
            delta = (
                abs(before[i] - after[i])
                + abs(before[i + 1] - after[i + 1])
                + abs(before[i + 2] - after[i + 2])
            ) // 3
            if delta > threshold:
                moved.append((col, row, delta))
    return moved


def cluster_cells(moved: list[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    """Split changed cells into 8-connected clusters, so two things moving in
    different places become two crops instead of one bounding box spanning
    the gap between them (which on a 4K screen is most of the screen)."""
    remaining = {(col, row): delta for col, row, delta in moved}
    clusters = []
    while remaining:
        seed = next(iter(remaining))
        stack, cluster = [seed], []
        del remaining[seed]
        while stack:
            col, row = stack.pop()
            cluster.append((col, row, 0))
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    neighbour = (col + dc, row + dr)
                    if neighbour in remaining:
                        del remaining[neighbour]
                        stack.append(neighbour)
        clusters.append(cluster)
    return clusters


def cells_to_rect(cluster, tw: int, th: int, width: int, height: int, pad: int) -> tuple[int, int, int, int]:
    """Bounding box of a cluster, in client pixels. Padded by whole cells
    because the thumbnail quantizes position - a sprite's edge is somewhere
    inside the boundary cell, not neatly on it, so an unpadded box clips it."""
    cols = [c for c, _, _ in cluster]
    rows = [r for _, r, _ in cluster]
    x0, x1 = max(0, min(cols) - pad), min(tw - 1, max(cols) + pad)
    y0, y1 = max(0, min(rows) - pad), min(th - 1, max(rows) + pad)
    scale_x, scale_y = width / tw, height / th
    return (
        int(x0 * scale_x), int(y0 * scale_y),
        max(1, int((x1 - x0 + 1) * scale_x)), max(1, int((y1 - y0 + 1) * scale_y)),
    )


def parse_region(text: str) -> tuple[float, float, float, float]:
    try:
        fx, fy, fw, fh = (float(part) for part in text.split(","))
    except ValueError:
        raise SystemExit(f"--region wants four comma-separated fractions, got {text!r}")
    return fx, fy, fw, fh


def fit_within(width: int, height: int, longest: int) -> tuple[int, int]:
    """Scale a crop down so its longest side is at most `longest`. The PNG
    writer is pure Python, so a full-resolution 4K crop would dominate the
    run's wall clock for no added information."""
    if max(width, height) <= longest:
        return width, height
    scale = longest / max(width, height)
    return max(1, int(width * scale)), max(1, int(height * scale))


def ahash_buffer(data: bytes, width: int, height: int, inset: float = 0.0) -> int:
    """Per-channel 8x8 average hash of a BGRA buffer already in memory.
    Same idea as crop_hash but without a second trip to GDI, so a set of
    captured cells can be grouped without recapturing any of them.

    `inset` trims that fraction off each edge before hashing. Grid slicing is
    never pixel-perfect, so every cell carries a sliver of its neighbours at
    the border - and a spatial hash weights those slivers as heavily as the
    subject, which makes identical tiles hash differently purely from what
    leaked in around the edge. Measured on this game's board: three visually
    identical tiles came out as two kinds at inset 0."""
    x0, y0 = int(width * inset), int(height * inset)
    x1, y1 = width - x0, height - y0
    inner_w, inner_h = max(8, x1 - x0), max(8, y1 - y0)
    block_w, block_h = max(1, inner_w // 8), max(1, inner_h // 8)
    bits = 0
    for channel in range(3):
        blocks = []
        for by in range(8):
            for bx in range(8):
                total = count = 0
                for y in range(y0 + by * block_h, min(y0 + (by + 1) * block_h, y1)):
                    row = y * width * 4
                    for x in range(x0 + bx * block_w, min(x0 + (bx + 1) * block_w, x1)):
                        total += data[row + x * 4 + channel]
                        count += 1
                blocks.append(total / max(1, count))
        average = sum(blocks) / len(blocks)
        for block in blocks:
            bits = (bits << 1) | (1 if block > average else 0)
    return bits


def color_signature(data: bytes, width: int, height: int, inset: float = 0.0) -> tuple[float, float, float]:
    """Mean per channel over the inset region.

    This, not the spatial average hash, is the right similarity metric for
    pixel-art tiles. An average hash thresholds each block against the image
    mean, so on near-uniform content - a dirt tile is a flat orange field with
    a few dots - every block sits at the mean and half the resulting bits are
    coin flips. Measured here: nine cells covering three visually distinct
    kinds hashed as nine kinds at every tolerance tried, while their mean
    colours separate cleanly."""
    x0, y0 = int(width * inset), int(height * inset)
    x1, y1 = width - x0, height - y0
    totals = [0, 0, 0]
    count = 0
    for y in range(y0, y1):
        row = y * width * 4
        for x in range(x0, x1):
            offset = row + x * 4
            totals[0] += data[offset]
            totals[1] += data[offset + 1]
            totals[2] += data[offset + 2]
            count += 1
    count = max(1, count)
    return totals[0] / count, totals[1] / count, totals[2] / count


def group_by_color(buffers: list[bytes], width: int, height: int, tolerance: float,
                   inset: float = 0.0) -> list[list[int]]:
    """Group buffer indices whose mean colours are within `tolerance` on every
    channel. A tile game repeats the same sprite across many cells, so the
    interesting output is the set of distinct kinds, not one file per cell."""
    signatures = [color_signature(buf, width, height, inset) for buf in buffers]
    groups: list[list[int]] = []
    for index, signature in enumerate(signatures):
        for group in groups:
            reference = signatures[group[0]]
            if all(abs(a - b) <= tolerance for a, b in zip(signature, reference)):
                group.append(index)
                break
        else:
            groups.append([index])
    return groups


def group_by_hash(buffers: list[bytes], width: int, height: int, tolerance: int,
                  inset: float = 0.0) -> list[list[int]]:
    """Group buffer indices whose average hashes are within `tolerance`.
    Kept for detailed, high-variance art; see color_signature for why it is
    the wrong choice on flat pixel-art tiles."""
    hashes = [ahash_buffer(buf, width, height, inset) for buf in buffers]
    groups: list[list[int]] = []
    for index, digest in enumerate(hashes):
        for group in groups:
            if bin(digest ^ hashes[group[0]]).count("1") <= tolerance:
                group.append(index)
                break
        else:
            groups.append([index])
    return groups


def crop_hash(left: int, top: int, width: int, height: int) -> int:
    """Per-channel 8x8 average hash of a screen region, for dropping repeat
    crops of the same thing. GDI does the block averaging during the
    downsample, so this costs one tiny StretchBlt rather than a Python loop.
    Per channel, not greyscale: two sprites can share a brightness pattern
    and differ only in colour."""
    data = grab_thumbnail(left, top, width, height, 8, 8)
    bits = 0
    for channel in range(3):
        values = [data[i * 4 + channel] for i in range(64)]
        average = sum(values) / len(values)
        for value in values:
            bits = (bits << 1) | (1 if value > average else 0)
    return bits


def motion_map(moved: list[tuple[int, int, int]], tw: int, th: int, rows: int = 12) -> str:
    """Collapse the changed cells into a small ASCII grid, so a glance says
    *where* on the game screen it moved."""
    cols = rows * 2  # character cells are roughly twice as tall as wide
    grid = [[" "] * cols for _ in range(rows)]
    for col, row, delta in moved:
        y = min(rows - 1, row * rows // th)
        x = min(cols - 1, col * cols // tw)
        grid[y][x] = "#" if delta > 48 else ("+" if delta > 16 else ".")
    border = "+" + "-" * cols + "+"
    return "\n".join([border] + ["|" + "".join(r) + "|" for r in grid] + [border])


def send_input(*inputs: INPUT) -> None:
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(f"SendInput sent {sent} of {len(inputs)} events (error {ctypes.get_last_error()})")


def mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, value=_INPUTUNION(mi=MOUSEINPUT(dx=dx, dy=dy, dwFlags=flags)))


def mouse_move_to(x: int, y: int) -> None:
    """Move the cursor through SendInput, not SetCursorPos.

    SetCursorPos relocates the cursor but injects nothing into the input
    stream, so a game that tracks the mouse from move *events* (rather than
    polling GetCursorPos every frame) never learns the cursor arrived - and a
    click that follows lands on whatever the game still believes is under the
    pointer, which is usually nothing. An absolute MOUSEEVENTF_MOVE is
    indistinguishable from a real mouse being dragged there.

    Absolute coordinates are normalized to 0..65535 across the *virtual*
    desktop, not the primary monitor, or a multi-monitor setup lands the
    cursor at a fraction of the intended position."""
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    nx = int((x - vx) * 65535 / vw)
    ny = int((y - vy) * 65535 / vh)
    send_input(mouse_input(
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def key_input(vk: int, keyup: bool) -> INPUT:
    """Scancode-based, not virtual-key-based: game runtimes routinely read
    the keyboard at a level where a VK-only synthetic event is invisible,
    while a scancode event is indistinguishable from real hardware.

    Extended keys need their flag set explicitly - the arrow cluster shares
    raw scancodes with the numeric keypad, so an arrow sent without
    EXTENDEDKEY arrives as the numpad equivalent and a game that only binds
    the arrows ignores it."""
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if keyup else 0)
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(type=INPUT_KEYBOARD, value=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags)))


def touch(hwnd: int, kind: str, key: str, at: tuple[float, float],
          button: str = "left", hold: float = 0.08, hover: float = 0.2) -> str:
    """Deliver one input to the window and describe what was sent.

    'move' only repositions the cursor - no button, no key - which is the
    least state-changing thing that can still provoke a visible reaction
    (hover highlights, cursor-follow art).

    `at` is a fraction of the client area rather than absolute pixels so the
    same call means the same place on a 4K fullscreen window and a small
    windowed one.

    A click is deliberately *slow*: move, wait, press, hold, release. Sending
    the down and the up in one SendInput call puts both in the same input
    batch, so a game sampling the mouse once per frame can see the button
    already released by the time it looks and register nothing at all. Same
    for the move: a button press arriving in the same millisecond as the
    cursor gets hit-tested against wherever the pointer used to be. Both
    failure modes look identical from outside - the click is simply
    ignored."""
    left, top, width, height = client_rect_on_screen(hwnd)
    point = (left + int(width * at[0]), top + int(height * at[1]))

    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)  # focus changes are asynchronous; input before it lands goes elsewhere

    if kind == "move":
        mouse_move_to(*point)
        return f"cursor moved to {point} ({at[0]:.2f}, {at[1]:.2f} of client area)"

    if kind == "click":
        mouse_move_to(*point)
        time.sleep(hover)  # let the game hit-test the new cursor position first
        down, up = BUTTON_FLAGS[button]
        send_input(mouse_input(down))
        time.sleep(hold)   # hold long enough for at least one game frame to sample it
        send_input(mouse_input(up))
        return (f"{button} click at {point} ({at[0]:.2f}, {at[1]:.2f} of client area), "
                f"held {hold * 1000:.0f}ms after a {hover * 1000:.0f}ms hover")

    vk = VK_NAMES.get(key.lower()) or (ord(key.upper()) if len(key) == 1 else None)
    if vk is None:
        raise SystemExit(f"Unknown key {key!r}; use a single character or one of: {', '.join(VK_NAMES)}")
    send_input(key_input(vk, keyup=False), key_input(vk, keyup=True))
    return f"key {key!r} (vk 0x{vk:02X}) pressed and released"


def main() -> None:
    parser = argparse.ArgumentParser(description="Touch a native game window and report screen motion.")
    parser.add_argument("--title", default="Tile Tale", help="Substring of the target window's title")
    parser.add_argument("--restore", action="store_true",
                        help="Un-minimize and raise the window first (capture reads the screen, "
                             "so the window has to be visible)")
    parser.add_argument("--restore-timeout", type=float, default=6.0,
                        help="How long to keep trying to bring the window back with --restore")
    parser.add_argument("--touch", choices=["none", "move", "click", "key"], default="none",
                        help="Input to deliver before watching (default: none - reads only)")
    parser.add_argument("--key", default="space", help="Key for --touch key")
    parser.add_argument("--button", choices=list(BUTTON_FLAGS), default="left",
                        help="Mouse button for --touch click")
    parser.add_argument("--click-hold", type=float, default=0.08, metavar="SECONDS",
                        help="How long the button stays down (a 0s down/up pair is often "
                             "sampled as no click at all)")
    parser.add_argument("--hover-delay", type=float, default=0.2, metavar="SECONDS",
                        help="Pause between moving the cursor and pressing, so the game "
                             "hit-tests the new position before the press arrives")
    parser.add_argument("--at", default="0.5,0.5", metavar="FX,FY",
                        help="Where to touch, as a fraction of the client area (default: centre)")
    parser.add_argument("--watch", type=float, default=0.0, metavar="SECONDS",
                        help="Watch for motion for this long after touching")
    parser.add_argument("--fps", type=float, default=10.0, help="Capture rate while watching")
    parser.add_argument("--map", action="store_true",
                        help="Print a motion map per moving frame, not just the combined one at the end")
    parser.add_argument("--threshold", type=int, default=6,
                        help="Mean per-channel delta for a cell to count as moved (0-255)")
    parser.add_argument("--grid", type=int, nargs=2, default=(64, 36), metavar=("W", "H"),
                        help="Thumbnail size the frame diff runs on")
    parser.add_argument("--crop-moved", metavar="DIR",
                        help="Save a PNG per moving element, cropped to what actually changed")
    parser.add_argument("--crop-prefix", default="crop", help="Filename prefix for --crop-moved")
    parser.add_argument("--min-cluster", type=int, default=3,
                        help="Ignore motion clusters smaller than this many cells (anti-noise)")
    parser.add_argument("--pad", type=int, default=1, help="Cells of padding around a crop")
    parser.add_argument("--max-crop", type=int, default=480, help="Longest side of a saved crop")
    parser.add_argument("--hash-tolerance", type=int, default=10,
                        help="Hamming distance (of 192 bits) below which two crops count as the same picture")
    parser.add_argument("--slice", metavar="DIR",
                        help="Slice --region into a --slice-grid of PNGs and exit")
    parser.add_argument("--slice-grid", type=int, nargs=2, default=(3, 3), metavar=("COLS", "ROWS"))
    parser.add_argument("--slice-prefix", default="cell")
    parser.add_argument("--sheet", metavar="PATH", help="Also write a contact sheet of the sliced cells")
    parser.add_argument("--hash-inset", type=float, default=0.18,
                        help="Fraction trimmed off each edge before hashing, to ignore neighbour "
                             "bleed from imperfect grid alignment")
    parser.add_argument("--group-by", choices=["color", "hash"], default="color",
                        help="Similarity metric for --dedupe (default: color - see color_signature)")
    parser.add_argument("--color-tolerance", type=float, default=10.0,
                        help="Max per-channel mean difference for two cells to count as the same kind")
    parser.add_argument("--dedupe", action="store_true",
                        help="Group sliced cells by average hash and write one PNG per distinct kind")
    parser.add_argument("--region", default="0,0,1,1", metavar="FX,FY,FW,FH",
                        help="Sub-region for --save/--slice, as fractions of the client area")
    parser.add_argument("--save", metavar="PATH", help="Write a PNG of the current screen and exit")
    parser.add_argument("--save-size", type=int, nargs=2, default=(960, 540), metavar=("W", "H"),
                        help="Resolution for --save")
    args = parser.parse_args()

    set_dpi_aware()
    hwnd, title = find_window(args.title)

    if args.restore:
        # Poll rather than sleep a fixed interval: a fullscreen-exclusive game
        # coming back from minimized has to re-acquire the display mode, which
        # takes an unpredictable moment, and a background console process is
        # subject to Windows' foreground lock so SetForegroundWindow may be
        # refused outright - the client rect going non-zero is the only
        # trustworthy signal that it actually came back.
        deadline = time.monotonic() + args.restore_timeout
        while time.monotonic() < deadline:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.4)
            if client_rect_on_screen(hwnd)[2] > 0:
                break
        time.sleep(0.6)  # let it render a settled frame before measuring anything

    left, top, width, height = client_rect_on_screen(hwnd)
    if width <= 0 or height <= 0:
        raise SystemExit(
            f"{title!r} has an empty client area ({width}x{height}) - it is minimized. "
            f"Un-minimize it, or pass --restore."
        )
    tw, th = args.grid
    print(f"window   : {title!r} (hwnd 0x{hwnd:X})")
    print(f"client   : {width}x{height} at ({left}, {top})")
    print(f"capture  : {tw}x{th} thumbnail, threshold {args.threshold}, {args.fps} fps")

    if args.save:
        sw, sh = args.save_size
        fx, fy, fw, fh = parse_region(args.region)
        rx, ry = left + int(width * fx), top + int(height * fy)
        rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
        write_png(args.save, grab_thumbnail(rx, ry, rw, rh, sw, sh), sw, sh)
        print(f"saved    : {args.save} ({sw}x{sh} of a {rw}x{rh} region at {rx},{ry})")
        return

    if args.slice:
        slice_dir = Path(args.slice)
        slice_dir.mkdir(parents=True, exist_ok=True)
        fx, fy, fw, fh = parse_region(args.region)
        rx, ry = left + int(width * fx), top + int(height * fy)
        rw, rh = max(1, int(width * fw)), max(1, int(height * fh))
        cols, rows = args.slice_grid
        cell_w, cell_h = rw // cols, rh // rows
        out_w, out_h = fit_within(cell_w, cell_h, args.max_crop)
        print(f"slicing  : {rw}x{rh} region at {rx},{ry} into {cols}x{rows} "
              f"cells of {cell_w}x{cell_h} (saved at {out_w}x{out_h})")

        buffers = []
        for row in range(rows):
            for col in range(cols):
                buf = grab_thumbnail(rx + col * cell_w, ry + row * cell_h, cell_w, cell_h, out_w, out_h)
                buffers.append(buf)
                name = f"{args.slice_prefix}_r{row + 1}c{col + 1}.png"
                write_png(str(slice_dir / name), buf, out_w, out_h)
                print(f"           {name}")
        if args.sheet:
            sheet, sw, sh = contact_sheet(buffers, out_w, out_h, cols)
            write_png(args.sheet, sheet, sw, sh)
            print(f"sheet    : {args.sheet} ({sw}x{sh})")

        if args.dedupe:
            names = [f"r{i // cols + 1}c{i % cols + 1}" for i in range(len(buffers))]
            if args.group_by == "color":
                groups = group_by_color(buffers, out_w, out_h, args.color_tolerance, args.hash_inset)
            else:
                groups = group_by_hash(buffers, out_w, out_h, args.hash_tolerance, args.hash_inset)
            unique_dir = slice_dir / "unique"
            unique_dir.mkdir(exist_ok=True)
            print(f"distinct : {len(groups)} kind(s) among {len(buffers)} cells")
            for kind, group in enumerate(groups, start=1):
                name = f"{args.slice_prefix}_kind{kind:02d}.png"
                write_png(str(unique_dir / name), buffers[group[0]], out_w, out_h)
                print(f"           {name}  <- {', '.join(names[i] for i in group)}")
            sheet, sw, sh = contact_sheet([buffers[g[0]] for g in groups], out_w, out_h, len(groups))
            write_png(str(unique_dir / f"{args.slice_prefix}_kinds_sheet.png"), sheet, sw, sh)
        return

    # The pre-touch frame has to be captured BEFORE the input is delivered.
    # Touching first and then grabbing the baseline hides any reaction fast
    # enough to complete in the interim - it is already present in the
    # baseline, so it diffs to zero and reads as "the game ignored us".
    baseline = grab_thumbnail(left, top, width, height, tw, th) if args.watch > 0 else None

    if args.touch != "none":
        try:
            fx, fy = (float(part) for part in args.at.split(","))
        except ValueError:
            raise SystemExit(f"--at wants two comma-separated fractions, got {args.at!r}")
        print(f"touch    : {touch(hwnd, args.touch, args.key, (fx, fy), args.button, args.click_hold, args.hover_delay)}")

    if args.watch <= 0:
        # Still prove capture works, and say whether it read the game or something on top of it.
        grab_thumbnail(left, top, width, height, tw, th)
        foreground = user32.GetForegroundWindow() == hwnd
        print(f"capture ok; game is {'in the foreground' if foreground else 'NOT in the foreground'}")
        return

    print(f"watching for {args.watch:g}s - Ctrl+C to stop\n")
    interval = 1.0 / args.fps
    previous = baseline
    started = time.monotonic()
    frames = moving_frames = 0
    peak = 0
    occluded_frames = 0
    total_moved: list[tuple[int, int, int]] = []
    crop_hashes: list[int] = []
    crop_index = 0
    crop_dir = Path(args.crop_moved) if args.crop_moved else None
    if crop_dir is not None:
        crop_dir.mkdir(parents=True, exist_ok=True)

    try:
        while time.monotonic() - started < args.watch:
            time.sleep(interval)
            current = grab_thumbnail(left, top, width, height, tw, th)
            frames += 1
            if user32.GetForegroundWindow() != hwnd:
                occluded_frames += 1
            moved = diff_cells(previous, current, tw, th, args.threshold)
            if moved:
                moving_frames += 1
                worst = max(m[2] for m in moved)
                peak = max(peak, worst)
                total_moved.extend(moved)
                elapsed = time.monotonic() - started
                share = 100.0 * len(moved) / (tw * th)
                print(f"[{elapsed:6.2f}s] MOTION  {len(moved):5d} cells ({share:5.1f}% of screen), peak delta {worst:3d}")
                if args.map:
                    print(motion_map(moved, tw, th))

                if crop_dir is not None:
                    for cluster in cluster_cells(moved):
                        if len(cluster) < args.min_cluster:
                            continue
                        cx, cy, cw, ch = cells_to_rect(cluster, tw, th, width, height, args.pad)
                        digest = crop_hash(left + cx, top + cy, cw, ch)
                        # Successive frames of one animation, and a highlight that
                        # reappears later, both re-crop the same picture; keep one.
                        if any(bin(digest ^ seen).count("1") <= args.hash_tolerance for seen in crop_hashes):
                            continue
                        crop_hashes.append(digest)
                        ow, oh = fit_within(cw, ch, args.max_crop)
                        crop_index += 1
                        name = f"{args.crop_prefix}_{crop_index:03d}_{cx}x{cy}_{cw}x{ch}.png"
                        write_png(str(crop_dir / name), grab_thumbnail(left + cx, top + cy, cw, ch, ow, oh), ow, oh)
                        print(f"           crop -> {name}  ({cw}x{ch} at {cx},{cy})")
            previous = current
    except KeyboardInterrupt:
        print("\ninterrupted")

    print(f"\n{frames} frames, {moving_frames} with motion, peak delta {peak}")
    if total_moved:
        print("\nwhere it moved (all frames combined):")
        print(motion_map(total_moved, tw, th))
    if occluded_frames:
        print(f"WARNING: game was not foreground for {occluded_frames}/{frames} frames - "
              f"those captured whatever was on top of it, not the game.")


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Windows-only (user32/gdi32).")
    main()
