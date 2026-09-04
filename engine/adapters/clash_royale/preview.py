"""Photograph the live client with the action space and the denylist drawn on it.

The operator's standing rule for this project is that the boxes are shown before
anything clicks, and this is what satisfies it for the adapter. It is also the only
honest check on the coordinates: `(0.216, 0.943)` is exactly the kind of number
that is plausible and wrong, and a point 0.03 off still looks reasonable in the
source while landing on the neighbouring tab. Reading the source cannot catch that.
Looking at the picture can.

Read-only apart from bringing the window forward. **Nothing is clicked** - the
crosshairs are drawn where a tap *would* go.

Run:  python -m engine.adapters.clash_royale.preview
"""

from __future__ import annotations

from pathlib import Path

from engine.adapters.clash_royale.actions import CATALOGUE, GUARD_PROBES, RECOVERY, vet
from engine.adapters.clash_royale.session import attach

# Magenta for what is forbidden and cyan for what the Driver may touch. Both are
# absent from every Clash Royale screen, so neither can be mistaken for part of the
# game, and they are far enough apart to tell without a legend.
FORBIDDEN = (255, 0, 255)
ALLOWED = (255, 255, 0)
PROBE = (0, 165, 255)

OUT = Path(__file__).resolve().parents[3] / "experiments" / "android-bot" / "out"


def _outline_fn():
    """`denylist_preview.outline`, which already draws a fractional box correctly.

    Imported on call rather than at module load for the same reason as the rest of
    the harness: it reaches Win32 through `controller`. It is importable at all
    because `session` put experiments/android-bot on the path when this module
    imported it. Reused rather than reimplemented because a second copy of the same
    arithmetic is a second chance to get the off-by-one on the right and bottom
    edges wrong, and this preview's whole job is to be trustworthy about where an
    edge is.
    """
    from denylist_preview import outline  # noqa: E402
    return outline


def crosshair(pixels: bytearray, width: int, height: int, at: tuple[float, float],
              ink: tuple[int, int, int], arm: int = 14) -> None:
    """Mark one exact point: a cross through it, not a box around it.

    A box would say "somewhere in here", and the thing being reviewed is a single
    pixel-precise coordinate. The centre is left unpainted so that whatever the tap
    would actually land on is still visible underneath the mark.
    """
    cx, cy = int(at[0] * width), int(at[1] * height)
    blue, green, red = ink

    def plot(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            index = (y * width + x) * 4
            pixels[index:index + 3] = bytes((blue, green, red))

    for offset in range(2, arm + 1):
        for thickness in (0, 1):
            plot(cx - offset, cy + thickness)
            plot(cx + offset, cy + thickness)
            plot(cx + thickness, cy - offset)
            plot(cx + thickness, cy + offset)


def main() -> None:
    session, report = attach()
    print()

    handle = session.controller
    frame, width, height = handle.capture()
    pixels = bytearray(frame)
    outline = _outline_fn()

    for entry in handle.target.denylist:
        outline(pixels, width, height, entry["box"], ink=FORBIDDEN)
    for _, at in GUARD_PROBES:
        crosshair(pixels, width, height, at, PROBE, arm=8)
    for action, why in vet(handle.target):
        # `why` is always None here or `preflight` inside attach() would have
        # refused to get this far. Drawn from `vet` rather than from CATALOGUE
        # directly so that if that ever stops being true, the picture says so.
        crosshair(pixels, width, height, action.at, FORBIDDEN if why else ALLOWED)

    OUT.mkdir(parents=True, exist_ok=True)
    shot = OUT / "adapter-action-space.png"
    handle.write_capture(shot, (bytes(pixels), width, height))

    print(f"wrote {shot} ({width}x{height})")
    print(f"  magenta boxes: {len(handle.target.denylist)} denylisted region(s) - nothing may be "
          f"tapped inside these")
    print(f"  orange crosses: {len(GUARD_PROBES)} probe point(s), each inside a magenta box, all "
          f"confirmed refused by the guard")
    print(f"  cyan crosses: {len(CATALOGUE)} action(s) the Driver may choose from "
          f"({RECOVERY} is the way back)")
    print("\nLook at the picture before running anything live. Every cyan cross must sit on the "
          "control its name claims, and none of them inside a magenta box.")


if __name__ == "__main__":
    main()
