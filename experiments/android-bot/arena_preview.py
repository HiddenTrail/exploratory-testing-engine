"""Draw `arena.py`'s geometry onto a saved frame, and read a frame pair with it.

`denylist_preview.py` exists because a fractional box is the kind of number that is
plausible and wrong. Everything in `arena.py` is that same kind of number, with one
difference: the denylist can only be checked against a live window, but the arena boxes
were measured off frames that are still on disk - so this check costs no game at all.

Two things, both offline:

  * **the boxes**, stroked onto one frame: the arena, the river that splits their half
    from ours, the lane split, and the top of the card panel. Look at the result. If the
    magenta river line is not on the water, `arena.RIVER` is wrong.
  * **the reading**, if a second frame is given: what `arena.quadrants` makes of the pair.
    A pair one second apart during a live match is the only honest way to find out whether
    `arena.BUSY` is anywhere near right, and the frames `battle.py` already writes every
    sixty seconds are exactly that pair.

Run:  python experiments/android-bot/arena_preview.py [frame.png [second.png]]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-screen-probe"))

from probe import read_png, thumbnail_from_bgra, write_png  # noqa: E402

import arena  # noqa: E402
from denylist_preview import outline  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
DEFAULT = OUT / "battle-m1-t120.png"
# The same magenta `denylist_preview` uses for boxes; a second colour for the lines that
# are not boxes, so a river drawn in the wrong place is not mistaken for a box edge.
LINE = (0, 255, 255)  # BGR: yellow
CELL_DELTA = 10       # Target.cell_delta, the harness default


def strokes() -> list[tuple[tuple[float, float, float, float], tuple[int, int, int], str]]:
    """Every line to draw, as a fractional box: what it is and why it is there.

    A zero-height box is a horizontal line and a zero-width box a vertical one, which is
    `outline`'s behaviour for free rather than a second drawing routine to keep correct.
    """
    left, top, width, height = arena.ARENA
    return [
        (arena.ARENA, (255, 0, 255), "the arena - generous at the edges on purpose"),
        ((left, arena.RIVER, width, 0.0), LINE, f"the river at y {arena.RIVER}"),
        ((left + width / 2, top, 0.0, height), LINE, "the lane split"),
        ((0.0, arena.PANEL_TOP, 1.0, 0.0), LINE, f"card panel top at y {arena.PANEL_TOP}"),
    ]


def draw(source: Path, destination: Path) -> tuple[int, int]:
    pixels, width, height = read_png(str(source))
    canvas = bytearray(pixels)
    for box, ink, why in strokes():
        outline(canvas, width, height, box, ink=ink, edge=2)
        print(f"  {box}  {why}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_png(str(destination), bytes(canvas), width, height)
    return width, height


def reading(first: Path, second: Path) -> arena.Threat:
    """What `arena` makes of two saved frames.

    Goes through `thumbnail_from_bgra` rather than `Controller.grab`, which is the one
    place this differs from a live look: the box average here approximates GDI's HALFTONE
    rather than reproducing it, so a fraction measured here is the right order of
    magnitude and not the exact number the driver will see.
    """
    before, width, height = read_png(str(first))
    after, after_width, after_height = read_png(str(second))
    if (width, height) != (after_width, after_height):
        raise SystemExit(f"frames differ in size: {width}x{height} vs {after_width}x{after_height}")
    grid = (arena.COLS, arena.ROWS)
    return arena.read(
        thumbnail_from_bgra(before, width, height, *grid, region=arena.ARENA),
        thumbnail_from_bgra(after, width, height, *grid, region=arena.ARENA),
        CELL_DELTA,
    )


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not source.exists():
        raise SystemExit(f"no such frame: {source}\n"
                         f"battle.py writes one every {60}s into {OUT}")

    print(f"{source.name}:")
    shot = OUT / "arena-preview.png"
    width, height = draw(source, shot)
    print(f"\nwrote {shot} ({width}x{height})")
    print(f"river is grid row {arena.river_row()} of {arena.ROWS}")

    if len(sys.argv) > 2:
        second = Path(sys.argv[2])
        if not second.exists():
            raise SystemExit(f"no such frame: {second}")
        threat = reading(source, second)
        print(f"\n{source.name} -> {second.name}: {threat.line()}")
        print(f"  busy at >= {arena.BUSY:.0%}, pressure {threat.pressure:.0%}")


if __name__ == "__main__":
    main()
