"""Sweep several frames of one screen and report which cells hold still.

The readiness gate in `Controller._wait_settled` asks a single question of the whole
window - did any cell move more than `screen_match` allows - and its docstring claims
"a startup transient crosses it by construction, idle animation does not". On
2026-09-07 the Clash Royale lobby falsified that: idle animation moved 132 of 2304
cells against a tolerance of 60, and a live, perfectly readable client failed the gate
with `never rendered a settled frame`.

The premise behind that single number is that a screen is either moving or it is not.
Games are not like that. A lobby has an animated offer banner, a ticking countdown, a
glowing arena and a shimmer on the button plate, all while every button, label and
counter sits exactly where it was. So "how much of the window moved" conflates two
different things, and the useful question is *which parts* moved.

This measures that directly: N frames, and for each of the 2304 cells, how many of the
N-1 consecutive pairs it changed in. Cells that changed in none of them are the chrome -
buttons, text, counters, panel edges. Cells that changed in most are decoration.

Nothing here is a fix. It is the measurement that says whether a per-screen stable mask
is worth building, and `recon.py` already has the shape of that answer in
`Screen.animated`, which excludes self-animating cells from the identity test. The
readiness gate is the one place that still judges the whole window at once.

Usage: python sweep_stability.py [frames] [--interval SECONDS] [--label NAME]
       python sweep_stability.py --from a.png b.png c.png [--label NAME]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from PIL import Image, ImageDraw  # noqa: E402


from controller import (READY_COLS, READY_ROWS, changed_cells,  # noqa: E402
                        readable_output, set_dpi_aware, variance)

from attach import apply_calibration, attach  # noqa: E402

GAME = "Clash Royale"
# Used only in offline mode, where there is no Target to read them off.
DEFAULT_CELL_DELTA = 10
DEFAULT_SCREEN_MATCH = 0.974
NCELLS = READY_COLS * READY_ROWS
OUT = Path(__file__).resolve().parent / "out"

# Bands to attribute motion to, as (label, y_from, y_to) in fractions of the window.
# Named after what is actually drawn there on this game's lobby, because "cell 1483 is
# volatile" is not something a person can act on.
BANDS = (
    ("top bar (Claim, coins, gems)", 0.00, 0.08),
    ("clan banner / name / trophies", 0.08, 0.25),
    ("arena art + side icons", 0.25, 0.58),
    ("offer banner (Catch Up)", 0.58, 0.73),
    ("battle row + event timer", 0.73, 0.88),
    ("bottom navigation", 0.88, 1.00),
)


def thumbnail(path: Path) -> bytes:
    """One saved PNG reduced to the gate's own grid, in the gate's own BGRA layout.

    BOX resampling on purpose: it averages every source pixel in a cell, which is what
    `Controller.grab` is doing when it downsamples, so a frame that came from a 393x700
    capture and one from 787x1400 reduce to comparable numbers. A smoothing filter would
    let the source resolution leak into the answer.
    """
    im = Image.open(path).convert("RGB").resize((READY_COLS, READY_ROWS), Image.BOX)
    out = bytearray()
    for r, g, b in im.getdata():
        out += bytes((b, g, r, 255))
    return bytes(out)


def tally(shots: list[bytes], delta: int) -> list[int]:
    """Per cell, how many of the consecutive pairs it moved in."""
    moved = [0] * NCELLS
    for before, after in zip(shots, shots[1:]):
        for cell in range(NCELLS):
            i = cell * 4
            d = (abs(before[i] - after[i])
                 + abs(before[i + 1] - after[i + 1])
                 + abs(before[i + 2] - after[i + 2])) // 3
            if d > delta:
                moved[cell] += 1
    return moved


def sweep(controller, frames: int, interval: float) -> tuple[list[bytes], list[int]]:
    """`frames` thumbnails off the live window, and the per-cell tally."""
    shots: list[bytes] = []
    for n in range(frames):
        if n:
            time.sleep(interval)
        shots.append(controller.grab(READY_COLS, READY_ROWS, verify=False))
    return shots, tally(shots, controller.target.cell_delta)


def on_mask(before: bytes, after: bytes, mask: set[int], delta: int) -> int:
    """How many cells of `mask` moved between one pair."""
    hits = 0
    for cell in mask:
        i = cell * 4
        d = (abs(before[i] - after[i]) + abs(before[i + 1] - after[i + 1])
             + abs(before[i + 2] - after[i + 2])) // 3
        if d > delta:
            hits += 1
    return hits


def render_map(moved: list[int], pairs: int) -> str:
    """The grid as text. '.' never moved, '#' moved in every pair, digits in between."""
    lines = []
    for row in range(READY_ROWS):
        out = []
        for col in range(READY_COLS):
            n = moved[row * READY_COLS + col]
            out.append("." if n == 0 else "#" if n == pairs else str(min(n, 9)))
        lines.append("".join(out))
    return "\n".join(lines)


def paint(controller, moved: list[int], pairs: int, path: Path) -> None:
    """A full-resolution frame with the volatile cells washed red over it.

    Full resolution and not the 64x36 thumbnail the measurement runs on, which is the
    whole reason this needs an image library: the question a person asks of this picture
    is "which *button* is that stable cell part of", and a 64x36 upscale cannot answer it
    - it shows blocky colour with no readable control in it. Drawn as a translucent wash
    rather than a replacement so the control underneath stays legible, and stable cells
    are left completely untouched so the chrome reads as the *unmarked* part.
    """
    raw, wide, tall = controller.capture((0.0, 0.0, 1.0, 1.0), 1000)
    base = Image.frombytes("RGBA", (wide, tall), raw, "raw", "BGRA").convert("RGBA")
    wash = Image.new("RGBA", (wide, tall), (0, 0, 0, 0))
    pen = ImageDraw.Draw(wash)
    cw, ch = wide / READY_COLS, tall / READY_ROWS
    for cell, count in enumerate(moved):
        if not count:
            continue
        share = count / pairs
        col, row = cell % READY_COLS, cell // READY_COLS
        pen.rectangle([col * cw, row * ch, (col + 1) * cw - 1, (row + 1) * ch - 1],
                      fill=(255, 40, 40, int(60 + 135 * share)))
    Image.alpha_composite(base, wash).convert("RGB").save(path)


def paint_saved(source: Path, moved: list[int], pairs: int, path: Path) -> None:
    """`paint`, but over a saved frame - the offline half of the same picture."""
    base = Image.open(source).convert("RGBA")
    wide, tall = base.size
    wash = Image.new("RGBA", (wide, tall), (0, 0, 0, 0))
    pen = ImageDraw.Draw(wash)
    cw, ch = wide / READY_COLS, tall / READY_ROWS
    for cell, count in enumerate(moved):
        if not count:
            continue
        share = count / pairs
        col, row = cell % READY_COLS, cell // READY_COLS
        pen.rectangle([col * cw, row * ch, (col + 1) * cw - 1, (row + 1) * ch - 1],
                      fill=(255, 40, 40, int(60 + 135 * share)))
    Image.alpha_composite(base, wash).convert("RGB").save(path)


def main() -> int:
    readable_output()
    set_dpi_aware()
    argv = sys.argv[1:]
    frames = 5
    interval = 1.0
    label = "sweep"
    paths: list[str] = []
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--from":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                paths.append(argv[i]); i += 1
        elif argv[i] == "--interval":
            interval = float(argv[i + 1]); i += 2
        elif argv[i] == "--label":
            label = argv[i + 1]; i += 2
        else:
            rest.append(argv[i]); i += 1
    if rest:
        frames = int(rest[0])
    if not paths and frames < 2:
        print("need at least 2 frames to compare anything")
        return 2
    if paths and len(paths) < 2:
        print("need at least 2 saved frames to compare anything")
        return 2

    # Offline mode exists because the client is not always up, and because a saved set of
    # frames is the only way to re-run this measurement on a screen that has since changed.
    # `cell_delta` and `screen_match` are then the calibrated defaults rather than a live
    # target's, which is stated in the output rather than left to be inferred.
    controller = None
    if paths:
        shots = [thumbnail(Path(p)) for p in paths]
        frames = len(shots)
        delta, match = DEFAULT_CELL_DELTA, DEFAULT_SCREEN_MATCH
        print(f"{frames} saved frames, {READY_COLS}x{READY_ROWS} = {NCELLS} cells, "
              f"cell_delta {delta} (calibrated default)")
        for p in paths:
            print(f"  {p}")
    else:
        controller = attach(GAME, verbose=False)
        # The remembered calibration first, exactly as `wait_live.py` does it. Without
        # this the numbers here are scored against `Target`'s own default of 0.94 -
        # tolerance 138 - while the recon gate that actually failed runs on the measured
        # 0.974, tolerance 59. That is a factor of 2.3, wide enough to turn a FAILS into a
        # PASSES, and the calibration file's own note flags the trap by name.
        applied = apply_calibration(controller, GAME, ("screen_match", "cell_delta"))
        source = "the remembered calibration" if applied else "the target default"
        delta, match = controller.target.cell_delta, controller.target.screen_match
        print(f"{frames} frames {interval}s apart, {READY_COLS}x{READY_ROWS} = {NCELLS} "
              f"cells, cell_delta {delta} (from {source})")
    tolerance = int((1.0 - match) * NCELLS)
    print(f"the readiness gate tolerates {tolerance} cells (screen_match {match})\n")

    if controller is not None:
        shots, moved = sweep(controller, frames, interval)
    else:
        moved = tally(shots, delta)
    pairs = frames - 1
    stable = [c for c in range(NCELLS) if moved[c] == 0]
    always = [c for c in range(NCELLS) if moved[c] == pairs]
    ever = NCELLS - len(stable)

    print(f"stable in all {pairs} pairs : {len(stable):5d} of {NCELLS} "
          f"({len(stable)/NCELLS:.1%})")
    print(f"moved at least once      : {ever:5d} ({ever/NCELLS:.1%})")
    print(f"moved in every pair      : {len(always):5d} ({len(always)/NCELLS:.1%})")

    print("\nwhere the moving cells are:")
    for name, lo, hi in BANDS:
        rows = range(int(lo * READY_ROWS), max(int(lo * READY_ROWS) + 1,
                                               int(hi * READY_ROWS)))
        band = [r * READY_COLS + c for r in rows for c in range(READY_COLS)]
        busy = [c for c in band if moved[c]]
        print(f"  {name:34s} {len(busy):4d} of {len(band):4d} cells "
              f"({len(busy)/max(1,len(band)):5.1%})")

    print("\nwhat the two policies see, pair by pair:")
    worst_all = worst_stable = 0
    stable_set = set(stable)
    for n, (before, after) in enumerate(zip(shots, shots[1:]), 1):
        whole = changed_cells(before, after, delta)
        hits = on_mask(before, after, stable_set, delta)
        worst_all = max(worst_all, whole)
        worst_stable = max(worst_stable, hits)
        print(f"  pair {n}: whole window {whole:4d}   stable cells only {hits:4d}")
    print("  (the right column is 0 by construction - every cell that moved in any of "
          "these\n   pairs was excluded from the mask. See the held-out split below.)")

    print(f"\nbusiest pair: whole window {worst_all}, stable cells only {worst_stable}, "
          f"tolerance {tolerance}")
    print(f"  gate on the whole window : "
          f"{'PASSES' if worst_all <= tolerance else 'FAILS - would report the client dead'}")
    print(f"  gate on the stable mask  : "
          f"{'PASSES' if worst_stable <= tolerance else 'FAILS'}")
    print(f"  frame variance {variance(shots[-1]):.1f}")

    # A mask fit on every pair scores 0 on every pair by definition, which proves nothing.
    # The claim worth testing is that the mask *generalises*: cells that held still in the
    # first frames go on holding still in frames the mask has never seen. That needs a
    # split, and it needs at least 4 frames (2 pairs to learn from, 1 to be judged on).
    if frames >= 4:
        cut = (frames + 1) // 2
        learned = tally(shots[:cut], delta)
        learn_mask = {c for c in range(NCELLS) if learned[c] == 0}
        print(f"\nheld-out test: mask learned on frames 1-{cut} "
              f"({len(learn_mask)} stable cells), judged on the rest:")
        worst_held = 0
        for n, (before, after) in enumerate(zip(shots[cut - 1:], shots[cut:]), cut):
            whole = changed_cells(before, after, delta)
            hits = on_mask(before, after, learn_mask, delta)
            worst_held = max(worst_held, hits)
            print(f"  pair {n}: whole window {whole:4d}   learned mask {hits:4d}")
        print(f"  worst held-out reading {worst_held} against tolerance {tolerance}: "
              f"{'PASSES' if worst_held <= tolerance else 'FAILS - the mask does not hold'}")
    else:
        print(f"\nheld-out test: skipped, {frames} frames is not enough to learn on some "
              f"and be judged on others (needs 4)")

    OUT.mkdir(exist_ok=True)
    text = OUT / f"stability-{label}.txt"
    text.write_text(render_map(moved, pairs) + "\n", encoding="utf-8")
    png = OUT / f"stability-{label}.png"
    if controller is not None:
        paint(controller, moved, pairs, png)
        over = "the live window"
    else:
        paint_saved(Path(paths[-1]), moved, pairs, png)
        over = Path(paths[-1]).name
    print(f"\nwrote {text.name} (per-cell map) and {png.name} "
          f"(volatile cells washed red over {over})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
