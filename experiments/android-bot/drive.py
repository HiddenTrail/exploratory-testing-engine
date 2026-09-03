"""Drive the game one tap at a time, with a person deciding every tap.

The recon session in `run_recon.py` explores: it picks its own actions to map a game it
knows nothing about. This is the other half - a directed errand, where the destination is
known and the only question is which control to press next. Reaching a named screen by
exploring is the wrong tool for that: it would wander the whole menu tree paying a vetting
call per screen to arrive somewhere it was already told to go.

So there is no model in this file and no policy. One command captures the window, one
command taps a point and captures the result, and whoever is reading the pictures chooses.
That makes the safety story simple, too: nothing is sent that was not looked at first.

Two rules it keeps anyway, because a person driving is not a reason to remove the guards:

- the denylist is checked, and a point inside a box is refused. The refusal can be
  overridden with `--allow "<reason>"`, which prints the reason and the box it overrides.
  A bypass is deliberate, one tap at a time, and on the record - which is the difference
  between an override and a hole.
- the window is never closed and never launched, as everywhere else in this directory.

Run:  python experiments/android-bot/drive.py look
      python experiments/android-bot/drive.py tap 0.916 0.107
      python experiments/android-bot/drive.py tap 0.500 0.830 --allow "Training Camp start"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import log, readable_output, set_dpi_aware  # noqa: E402

from attach import attach  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
SETTLE = 1.2        # seconds between the tap and the picture of what it did. Long enough
                    # for this game's screen transitions, which measured 0.9-1.5s.


def shoot(controller, name: str) -> Path:
    """Photograph the window at full resolution and say where it went."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"drive-{name}.png"
    width, height = controller.write_capture(path, controller.capture(longest=4000))
    log(f"  wrote {path} ({width}x{height})")
    return path


def main() -> None:
    readable_output()
    set_dpi_aware()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("look", "tap"))
    parser.add_argument("x", type=float, nargs="?")
    parser.add_argument("y", type=float, nargs="?")
    parser.add_argument("--title", default="Clash Royale")
    parser.add_argument("--allow", default="",
                        help="tap a denylisted point anyway, for this reason. Printed with "
                             "the box it overrides, so the record says what was bypassed "
                             "and why rather than that nothing was in the way")
    parser.add_argument("--name", default="",
                        help="what to call the pictures, so a sequence of taps does not "
                             "overwrite its own evidence")
    args = parser.parse_args()

    controller = attach(args.title)
    controller.focus()

    if args.command == "look":
        shoot(controller, args.name or "now")
        return

    if args.x is None or args.y is None:
        raise SystemExit("tap needs an x and a y, as fractions of the window")
    at = (args.x, args.y)
    if not all(0.0 <= v <= 1.0 for v in at):
        raise SystemExit(f"{at} is not a point inside the window")

    why = controller.target.forbids(*at)
    if why and not args.allow:
        raise SystemExit(f"REFUSED: ({at[0]:.3f}, {at[1]:.3f}) is inside a denylist box - "
                         f"{why}. If this is deliberate, say so with --allow \"<reason>\".")
    if why:
        log(f"  OVERRIDE: tapping into a denylist box - {why}")
        log(f"  reason given: {args.allow}")

    name = args.name or f"{at[0]:.3f}-{at[1]:.3f}".replace(".", "")
    shoot(controller, f"{name}-before")
    log(f"  tapping ({at[0]:.3f}, {at[1]:.3f})")
    controller.click(*at)
    time.sleep(SETTLE)
    shoot(controller, f"{name}-after")


if __name__ == "__main__":
    main()
