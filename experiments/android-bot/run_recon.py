"""Run a game-ontology recon pass against a game inside the Google Play Games emulator.

The same session `recon.py` runs, with two substitutions and one prohibition:

- the game is *attached to*, never launched, because a Play Games title has no
  executable to launch (see `attach.py`);
- the window is never closed at the end. Every earlier target could be closed and
  relaunched to return it to a known state; this one is a live account on somebody's
  server, so closing it buys nothing and a relaunch cannot undo anything the pass did.
- `--dry` measures whether the window is drivable at all and calls no model. Worth
  running first on a new game: Clash Royale's main screen animates continuously
  (running water, waving flags), and the readiness loop's job is to tell that apart
  from a startup transient using `screen_match`, which for a game with no calibration
  is a default rather than a measurement.

Run:  python experiments/android-bot/run_recon.py --minutes 1 [--dry]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import log, readable_output, set_dpi_aware  # noqa: E402
from recon import Recon, write_report, write_session_log  # noqa: E402

from attach import apply_calibration, attach  # noqa: E402
from touch import TouchRecon  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def remember(controller, game: str) -> None:
    """Apply whatever a previous pass measured for this game, and say so.

    The overlay itself lives in `attach.apply_calibration`, because `attach` builds its own
    Target rather than going through `targets.resolve` - so every caller has to ask, and the
    copies of this loop that grew in three scripts left a fourth caller with none.
    """
    if not apply_calibration(controller, game):
        log(f"  no calibration for {game!r} yet; using defaults "
            f"(startup_quiet {controller.target.startup_quiet}s, "
            f"screen_match {controller.target.screen_match})")
        return
    log(f"  calibration: startup_quiet {controller.target.startup_quiet}s, "
        f"screen_match {controller.target.screen_match}")


def dry(controller) -> int:
    """Check the window is readable and settles, without a model or an input. 0 if fine."""
    log(controller.ensure_readable(allow_restart=False))
    settled = controller._wait_settled()
    if settled is None:
        log("NOT DRIVABLE: the window never held still long enough to count as settled. "
            "Loosen screen_match or raise startup_quiet before spending a pass on it.")
        return 1
    log(f"settled after {settled:.1f}s")

    # Two fingerprints a second apart, scored the way the session scores them. This is
    # the number that decides whether an idle main screen reads as one screen or as a
    # new one every frame, which is the difference between a map and a pile of frames.
    from recon import fingerprint
    first = fingerprint(controller)
    time.sleep(1.0)
    second = fingerprint(controller)
    from controller import changed_cells
    from recon import GRID_COLS, GRID_ROWS
    cells = GRID_COLS * GRID_ROWS
    moved = changed_cells(first, second, controller.target.cell_delta)
    agree = 1.0 - moved / cells
    log(f"idle drift: {moved} of {cells} cells moved in 1s, agreement {agree:.3f} "
        f"vs screen_match {controller.target.screen_match}")
    if agree < controller.target.screen_match:
        log("WARNING: idling alone reads as a different screen. A pass would file a new "
            "screen every frame; screen_match needs to be cut below that agreement.")
        return 1
    log("drivable: the idle screen reads as one screen")
    return 0


def main() -> None:
    readable_output()
    set_dpi_aware()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", default="Clash Royale")
    parser.add_argument("--minutes", type=float, default=1.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--resume", default="")
    parser.add_argument("--dry", action="store_true",
                        help="readability and drift check only: no model call, no input")
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--no-clicks", action="store_true")
    parser.add_argument("--screen-match", type=float, default=0.0,
                        help="override the calibrated screen_match for this pass. Needed "
                             "when a calibration cut inside one session is too tight for "
                             "the next: Clash Royale's 0.974 was measured on a pass whose "
                             "coin counter read 113, and an idle main screen reading 1 063 "
                             "scores 0.971 against it - a duplicate of the one screen every "
                             "pass starts on. Overridden here rather than by rewriting the "
                             "measurement, so the run says what it used")
    parser.add_argument("--desktop-probes", action="store_true",
                        help="use the full desktop repertoire - hover sweep, arrow keys, "
                             "enter/space/esc - instead of the touch one. Measured to "
                             "waste a third of a pass on this target; kept so the "
                             "comparison can be re-run rather than taken on trust")
    args = parser.parse_args()

    controller = attach(args.game)
    remember(controller, args.game)
    if args.screen_match:
        log(f"  screen_match {controller.target.screen_match} -> {args.screen_match} "
            f"(asked for on the command line, not measured)")
        controller.target.screen_match = args.screen_match

    if args.dry:
        raise SystemExit(dry(controller))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else OUT / f"{args.game}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    vetter = None
    if not args.no_model:
        import describe
        vetter = describe.make_vetter()

    shape = Recon if args.desktop_probes else TouchRecon
    log(f"probe repertoire: {'desktop' if args.desktop_probes else 'touch'}")
    session = shape(controller, out, vetter=vetter, allow_clicks=not args.no_clicks)
    if args.resume:
        source = Path(args.resume)
        log(session.resume(json.loads((source / "ontology.json").read_text(
            encoding="utf-8")), source))
    try:
        log(controller.ensure_readable(allow_restart=False))
        session.run(args.minutes)
    except KeyboardInterrupt:
        log("\ninterrupted")
    finally:
        data = session.to_json()
        log(f"\nwrote {session.save()}")
        log(f"wrote {write_report(data, out)}")
        log(f"wrote {write_session_log(session.session_log, out)}")
        log(f"{len(session.screens)} screens, {len(session.transitions)} transitions, "
            f"{sum(len(s.variants) for s in session.screens.values())} images")
        # Deliberately not closed. See the module docstring.
        log("left the game open")


if __name__ == "__main__":
    main()
