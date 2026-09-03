"""Measure where a mapped screen's elements are, and say which ones the safety layers catch.

Read-only: it captures the window and brings it forward, and sends no input at all. No
model call either - it works from a map a previous pass already vetted.

Why this exists as its own step. Every element's tap point used to be a coordinate the
vetting call read off a screenshot; it is now the centre of a rectangle measured against
the window (`Recon.locate_elements`). That is the improvement, and it is also a change to
*every* aimed point on every screen - and the coordinate denylist is checked against the
final point. A control whose measured centre moved a little could in principle land on the
other side of a denylist box from where its described point was, and the place to find that
out is here, before a pass sends anything, rather than in a transition afterwards.

So the table below prints, per element, the rectangle, the point it produces, and whether
`Target.forbids` or `touch.costs_money` would stop it. Two kinds of row are worth reading
closely: one caught by neither that names money in its description anyway, and one that a
box catches by a hair.

Only the screen currently on display can be measured - a rectangle is read off the live
window, so a screen the game is not showing has nothing to read. Bring the game to whatever
screen you want checked and run it again.

Run:  python experiments/android-bot/preview_elements.py [--map out/<run>] [--title "Clash Royale"]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import log, readable_output, set_dpi_aware  # noqa: E402
from recon import (MIN_STABLE_CELLS, NCELLS, agreement, as_box,  # noqa: E402
                   box_centre, diff_cells, fingerprint, is_fraction)

from attach import attach  # noqa: E402
from denylist_preview import outline  # noqa: E402
from run_recon import remember  # noqa: E402
from touch import TouchRecon, costs_money  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
# BGR. Magenta is the denylist, as in `denylist_preview`; an element is green when it is
# a candidate this pass could tap and red when one of the safety layers stops it.
DENY = (255, 0, 255)
CLEAR = (0, 200, 0)
BLOCKED = (0, 0, 255)


def latest_map() -> Path:
    """The most recent run directory holding a map, so the usual case needs no argument."""
    maps = sorted(OUT.glob("*/ontology.json"), key=lambda p: p.stat().st_mtime)
    if not maps:
        raise SystemExit(f"no ontology.json under {OUT}")
    return maps[-1].parent


def main() -> None:
    readable_output()
    set_dpi_aware()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", default="")
    parser.add_argument("--title", default="Clash Royale")
    parser.add_argument("--screen-match", type=float, default=0.0,
                        help="override the calibrated threshold, as run_recon.py does. Pass "
                             "the same value here as there, or this checks coordinates "
                             "against a screen the pass will not agree it was on")
    args = parser.parse_args()

    source = Path(args.map) if args.map else latest_map()
    controller = attach(args.title)
    remember(controller, args.title)
    if args.screen_match:
        controller.target.screen_match = args.screen_match
        log(f"  screen_match overridden to {args.screen_match}")

    # A throwaway session, never saved: this reads the map and the window and writes
    # neither. The elements it measures are measured again by the pass that needs them.
    session = TouchRecon(controller, OUT / "preview-elements", vetter=None,
                         allow_clicks=False)
    log(session.resume(json.loads((source / "ontology.json").read_text("utf-8")), source))

    controller.focus()
    live = fingerprint(controller)
    # The same two measures `Recon._match_screen` uses, and in the same order, because a
    # preview that answered "which screen is this" differently from the session would be
    # checking coordinates on a screen the pass will not agree it was on. Membership is the
    # *masked* score - cells known to move on this screen do not count against it - and
    # which stored appearance it is closest to is raw distance. Scoring membership raw, as
    # this first did, reads a coin counter going from 113 to 1 063 as a different place.
    qualified = []
    nearest = None
    for screen in session.screens.values():
        score, stable, _ = agreement(live, screen.representative, screen.volatile,
                                     session.cell_delta)
        if stable < MIN_STABLE_CELLS:
            continue
        if nearest is None or score > nearest[0]:
            nearest = (score, stable, screen)
        if score >= session.screen_match:
            qualified.append((score, stable, screen))
    if not qualified:
        near = (f"nearest was {nearest[2].id} at {nearest[0]:.3f} on {nearest[1]} stable "
                f"cells" if nearest else "the map has nothing to compare against")
        raise SystemExit(f"no mapped screen matches the window at screen_match "
                         f"{session.screen_match} ({near}), so nothing here can be measured "
                         f"against a screen the pass would agree it was on. Either bring the "
                         f"game to a screen the map knows, or the threshold is too tight for "
                         f"this game between sessions.")

    score, stable, screen = max(qualified, key=lambda q: q[0])
    variant = min(screen.variants.values(),
                  key=lambda v: len(diff_cells(live, v.fp, session.cell_delta)))
    raw = len(diff_cells(live, variant.fp, session.cell_delta))
    log(f"the window is {screen.id} - {(screen.vetting or {}).get('name', 'unnamed')}, "
        f"agreement {score:.3f} on {stable} stable cells (threshold {session.screen_match}); "
        f"closest stored appearance {variant.id}, {raw} of {NCELLS} cells away raw")

    elements = (screen.vetting or {}).get("elements", [])
    if not elements:
        raise SystemExit(f"{screen.id} has no vetted elements to place")
    for element in elements:                    # so a re-run measures rather than reports
        element.pop("located", None)
    session.locate_elements(screen, variant)

    frame, width, height = controller.capture()
    pixels = bytearray(frame)
    for entry in controller.target.denylist or []:
        outline(pixels, width, height, entry["box"], DENY)

    log(f"\n{len(elements)} elements on {screen.id}, and what would stop each one:")
    stopped = 0
    for element in elements:
        label = (element.get("label") or "?")[:34]
        box = as_box(element.get("box"))
        if box is None:
            log(f"  {label:<34} {'-':<22} no usable rectangle")
            continue
        at = box_centre(box)
        why = controller.target.forbids(*at) or ""
        word = costs_money(f"{element.get('label', '')} {element.get('what', '')}")
        verdict = ("DENYLIST: " + why[:60] if why
                   else f"money word {word!r}" if word
                   else "off the window" if not is_fraction(at)
                   else "")
        stopped += bool(verdict)
        outline(pixels, width, height, box, BLOCKED if verdict else CLEAR, 2)
        log(f"  {label:<34} {element.get('located', '?'):<22} "
            f"({at[0]:.3f}, {at[1]:.3f})  {verdict}")

    log(f"\n{stopped} of {len(elements)} stopped, {len(elements) - stopped} tappable")
    for note in controller.notes:
        if screen.id in note:
            log(f"  note: {note}")

    OUT.mkdir(parents=True, exist_ok=True)
    shot = OUT / f"element-preview-{screen.id}.png"
    controller.write_capture(shot, (bytes(pixels), width, height))
    log(f"\nwrote {shot} ({width}x{height}) - magenta is the denylist, green a tappable "
        f"element, red one that is stopped")


if __name__ == "__main__":
    main()
