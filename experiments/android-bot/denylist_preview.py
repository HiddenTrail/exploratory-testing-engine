"""Draw the denylist over a live frame, so the boxes can be checked by eye.

A denylist is written as fractions of the client area, and fractions are exactly the
kind of number that is plausible and wrong: a box off by 0.05 still looks reasonable
in the source and no longer covers the button it was written for. The only cheap check
is to photograph the game with the boxes drawn on it and look.

Read-only apart from bringing the window forward. Nothing is clicked.

Run:  python experiments/android-bot/denylist_preview.py [title]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import readable_output, set_dpi_aware  # noqa: E402

from attach import attach  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
# Magenta in BGRA, which no Clash Royale screen contains and no eye will mistake for
# part of the game.
INK = (255, 0, 255)
EDGE = 3


def outline(pixels: bytearray, width: int, height: int,
            box: tuple[float, float, float, float], ink: tuple[int, int, int] = INK,
            edge: int = EDGE) -> None:
    """Stroke one fractional box onto a top-down BGRA buffer, in place."""
    fx, fy, fw, fh = box
    left, top = int(fx * width), int(fy * height)
    right, bottom = min(width - 1, int((fx + fw) * width)), min(height - 1, int((fy + fh) * height))
    blue, green, red = ink

    def plot(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            at = (y * width + x) * 4
            pixels[at:at + 3] = bytes((blue, green, red))

    for thickness in range(edge):
        for x in range(left, right + 1):
            plot(x, top + thickness)
            plot(x, bottom - thickness)
        for y in range(top, bottom + 1):
            plot(left + thickness, y)
            plot(right - thickness, y)


def main() -> None:
    readable_output()
    set_dpi_aware()
    needle = sys.argv[1] if len(sys.argv) > 1 else "Clash Royale"
    controller = attach(needle)

    denylist = controller.target.denylist
    if not denylist:
        print(f"no denylist for {controller.target.name!r} in targets.DENYLISTS")
        raise SystemExit(1)

    controller.focus()
    frame, width, height = controller.capture()
    pixels = bytearray(frame)
    for entry in denylist:
        outline(pixels, width, height, entry["box"])
        print(f"  {entry['box']}  {entry['why']}")

    OUT.mkdir(parents=True, exist_ok=True)
    shot = OUT / "denylist-preview.png"
    controller.write_capture(shot, (bytes(pixels), width, height))
    print(f"\nwrote {shot} ({width}x{height}), {len(denylist)} boxes")


if __name__ == "__main__":
    main()
