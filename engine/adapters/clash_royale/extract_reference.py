"""Extract a committable screen reference from a game-ontology recon pass.

Run once, by hand, when a recon pass has produced a map worth carrying:

    python -m engine.adapters.clash_royale.extract_reference \\
        "experiments/android-bot/out/Clash Royale-20260903-153913"

Why this exists rather than the adapter reading the pass directly
----------------------------------------------------------------
`out/` is gitignored. An adapter that read a recon directory at run time would
work on this machine and silently seed nothing on any other checkout - and
"silently seed nothing" is indistinguishable from "seeded fine" in every log the
run produces. So the data is extracted into `known_screens.json`, which is
committed, and the adapter reads only that.

The extraction is also a large reduction: the source pass is 293KB of fingerprints,
hover maps, element boxes, per-variant crops and image paths. What survives is what
a *navigation* run can use - identity, a name, a purpose, the volatile mask, and the
measured settle times - which is about a quarter of it and none of the pixels.

Fail closed on classification
-----------------------------
Every screen must have an entry in `VERDICTS` before it can be written out. That is
not bureaucracy: the recon reached the Offers/Shop screen and a battle result
screen, and the whole safety value of carrying this data is that a run can now
recognise those and stop. A new pass that discovers a twelfth screen must have it
classified by a person, because the alternative - defaulting an unclassified screen
to "fine" - would mean the one screen nobody had looked at is the one screen the
run treats as safe.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "known_screens.json"

# Cells per row in the recon's fingerprint grid. Asserted against the pass rather
# than assumed, because a fingerprint compared on the wrong stride does not error -
# it just disagrees with everything, which reads as "every screen is new".
GRID_COLS, GRID_ROWS = 32, 18

# What each screen in the carried pass is, and whether a meta-game-only run may be
# on it. Written out by hand after reading all eleven names and purposes, because
# this is a safety classification and a keyword match on a screen title is not one.
#
#   "ok"    - an ordinary meta-game screen. Named, explored, recovered from normally.
#   "abort" - the run stops on sight. Either it is out of scope (a purchase flow, a
#             battle) or reaching it means a denylisted control was somehow reached,
#             which is the one failure class this project has actually seen.
# Which of them is the main screen. Declared by hand next to the verdicts rather
# than inferred, because every way of inferring it is a guess about the game: it is
# not the most-visited screen (that is whatever the pass happened to loop on), not
# the one the recovery tap leads to (that is the thing being checked), and not the
# one named "main" (a name is a model's description, and two screens here are both
# called "Social screen"). What it is used for is narrow and worth being exact
# about: refusing to start a run that is anchored somewhere else.
MAIN_SCREEN = "sc01"

VERDICTS: dict[str, tuple[str, str]] = {
    "sc01": ("ok", "the main/home screen - this is where a run starts and returns to"),
    "sc02": ("ok", "the battle deck screen, reached from the bottom navigation"),
    "sc03": ("ok", "unnamed by the recon: it saw the screen but never labelled it"),
    "sc04": ("abort", "a social/clan screen. The Clan tab is denylisted, so arriving here means a "
                      "vetted action reached a screen the guard was supposed to make unreachable"),
    "sc05": ("ok", "unnamed by the recon: it saw the screen but never labelled it"),
    "sc06": ("abort", "a second social/clan screen - same reasoning as sc04"),
    "sc07": ("ok", "the card collection screen"),
    "sc08": ("abort", "the Offers/Shop screen - a real-money purchase flow, and the single thing "
                      "this run must never be on. The Shop tab is denylisted, so arriving here "
                      "means something got past the guard"),
    "sc09": ("ok", "the King Tower info panel, a card-detail overlay"),
    "sc10": ("ok", "unnamed by the recon: it saw the screen but never labelled it"),
    "sc11": ("abort", "a battle result screen, which means a battle was played. Out of scope for a "
                      "meta-game run and evidence the board tripwire was reached too late"),
}


def _mask_indices(rows: list[str] | None) -> list[int]:
    """A recon volatile/animated map, as a sorted list of cell indices.

    Stored as indices rather than as the source's row strings because that is what
    `recon.agreement` wants - a set of cells to exclude - and converting once here
    means the adapter never has to know the map was ever a picture.
    """
    if not rows:
        return []
    if len(rows) != GRID_ROWS or any(len(row) != GRID_COLS for row in rows):
        raise SystemExit(
            f"a mask in this pass is {len(rows)} rows of {len(rows[0]) if rows else 0}, not "
            f"{GRID_ROWS}x{GRID_COLS}. The fingerprint grid changed, so nothing in this pass can "
            f"be compared against a frame this adapter grabs."
        )
    return [row_index * GRID_COLS + col
            for row_index, row in enumerate(rows)
            for col, mark in enumerate(row) if mark != "."]


def _fingerprint(b64: str | None, what: str) -> str:
    """The fingerprint, checked for length and passed through unchanged.

    Kept in base64 rather than decoded and re-encoded: it is copied verbatim from
    the pass, so there is no transformation here that could be got wrong, and the
    only claim being made is about its size.
    """
    expected = GRID_COLS * GRID_ROWS * 3
    raw = base64.b64decode(b64 or "")
    if len(raw) != expected:
        raise SystemExit(
            f"{what}'s fingerprint is {len(raw)} bytes, not {expected} "
            f"({GRID_COLS}x{GRID_ROWS} cells of BGR). This pass cannot be carried."
        )
    return b64


def extract(pass_dir: Path) -> dict:
    source = pass_dir / "ontology.json"
    if not source.exists():
        raise SystemExit(f"no ontology.json in {pass_dir} - is that a recon pass directory?")
    pass_data = json.loads(source.read_text(encoding="utf-8"))

    session = pass_data["session"]
    if tuple(session["grid"]) != (GRID_COLS, GRID_ROWS):
        raise SystemExit(
            f"this pass used a {session['grid']} grid, not [{GRID_COLS}, {GRID_ROWS}]. Its "
            f"fingerprints are not comparable to what this adapter grabs."
        )

    ids = [screen["id"] for screen in pass_data["screens"]]
    unclassified = [screen_id for screen_id in ids if screen_id not in VERDICTS]
    if unclassified:
        raise SystemExit(
            f"REFUSING to write: {', '.join(unclassified)} have no entry in VERDICTS. Look at each "
            f"one's image in {pass_dir / 'images'} and classify it as 'ok' or 'abort' first. An "
            f"unclassified screen defaulting to safe would make the screen nobody reviewed the one "
            f"the run trusts."
        )

    if MAIN_SCREEN not in ids:
        raise SystemExit(
            f"MAIN_SCREEN is {MAIN_SCREEN!r}, which this pass does not contain (it has "
            f"{', '.join(ids)}). Screen ids are assigned in discovery order, so a different pass "
            f"numbers them differently - look at the images and set MAIN_SCREEN to whichever one "
            f"is the home screen."
        )
    if VERDICTS[MAIN_SCREEN][0] != "ok":
        raise SystemExit(
            f"MAIN_SCREEN is {MAIN_SCREEN!r} but its verdict is "
            f"{VERDICTS[MAIN_SCREEN][0]!r}. A run returns to the main screen after every "
            f"discovery, so a main screen the run must abort on would abort it immediately."
        )

    screens = []
    for screen in pass_data["screens"]:
        verdict, why = VERDICTS[screen["id"]]
        screens.append({
            "id": screen["id"],
            # None where the recon never named it. Carried as null rather than as an
            # invented name, so a run reports "sc05 (unnamed)" instead of implying
            # somebody knows what it is.
            "name": screen["name"],
            "purpose": screen["purpose"],
            "verdict": verdict,
            "why": why,
            "fingerprint_b64": _fingerprint(screen.get("fingerprint_b64"), screen["id"]),
            "volatile": _mask_indices(screen.get("volatile_map")),
            "identity_is_weak": screen["identity_is_weak"],
            "animated_cells": screen["animated_cells"],
            "observations": screen["observations"],
            # Every stored appearance of the screen, each with its own fingerprint.
            # Carried because the main screen alone had five: chest timers, a clan
            # banner and an event badge all change what it looks like without making
            # it a different screen, and matching only the representative would call
            # four of those five appearances something new.
            "variants": [
                {
                    "id": variant["id"],
                    "fingerprint_b64": _fingerprint(variant.get("fingerprint_b64"), variant["id"]),
                    "volatile": _mask_indices(variant.get("animated_map")),
                    "observations": variant["observations"],
                }
                for variant in (screen.get("variants") or [])
            ],
        })

    # Only taps. Every drag in the pass is dropped on the way through, because the
    # action space has none and a carried prior for an input that cannot be sent is
    # a fact the Driver can neither use nor check.
    transitions = [
        {
            "from": t["from"], "to": t["to"], "at": t["action"]["at"],
            "effect": t["effect"], "settle_ms": t["settle_ms"],
            "changed_cells": t["changed_cells"], "times_taken": t["times_taken"],
        }
        for t in pass_data["transitions"] if t["action"]["kind"] == "click"
    ]

    return {
        # Provenance first, and not decoration: everything below is a measurement
        # with a date on it, taken against a client that updates itself. A run that
        # finds these fingerprints no longer match needs to know how old they are
        # before concluding anything about the game.
        "source": {
            "pass": pass_dir.name,
            "schema": pass_data["schema"],
            "window_title": pass_data["target"].get("window_title", ""),
            "session_seconds": session["seconds"],
            "actions": session["actions"],
            "resumed_from": session.get("resumed_from"),
            "stopped": session.get("stopped"),
            "note": "Extracted by engine/adapters/clash_royale/extract_reference.py. Regenerate "
                    "with a newer pass rather than editing this file by hand.",
        },
        "grid": [GRID_COLS, GRID_ROWS],
        # The recon's own calibrated numbers, carried so the adapter uses the
        # threshold these fingerprints were measured under rather than one guessed
        # alongside them. See experiments/game-ontology/calibration/clashroyale.json:
        # the admissible range was [0.896, 0.974] and this pass ran at 0.94 with a
        # median match score of 1.0 and no screens split by name.
        "screen_match": session["screen_match_threshold"],
        "cell_delta": session["cell_delta"],
        "main_screen": MAIN_SCREEN,
        "screens": screens,
        "tap_transitions": transitions,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    reference = extract(Path(sys.argv[1]))
    OUT_PATH.write_text(json.dumps(reference, indent=2), encoding="utf-8")

    aborts = [s["id"] for s in reference["screens"] if s["verdict"] == "abort"]
    variants = sum(len(s["variants"]) for s in reference["screens"])
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size // 1024}KB)")
    print(f"  {len(reference['screens'])} screen(s), {variants} stored variant(s), "
          f"{len(reference['tap_transitions'])} tap transition(s)")
    print(f"  grid {reference['grid']}, screen_match {reference['screen_match']}, "
          f"cell_delta {reference['cell_delta']}, main screen {reference['main_screen']}")
    print(f"  abort on sight: {', '.join(aborts)}")


if __name__ == "__main__":
    main()
