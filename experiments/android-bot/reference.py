"""Cut the card reference library out of saved frames and write `cards.py`.

Run by hand, not by the driver: `python experiments/android-bot/reference.py`. It reads
frames from `out/`, which is gitignored, so the *output* is what gets committed and this
file is the record of where those numbers came from. If `cards.py` ever needs rebuilding
and the frames are gone, EXEMPLARS below says exactly which frame and slot each signature
was cut from, and the frames can be recaptured.

Why a luminance signature and not the pixels
--------------------------------------------
A card the player cannot afford is drawn in **greyscale**, so colour is available for
about a third of the frames a card appears in and absent for the rest. Luminance survives
both states. The signature is mean-removed - the pattern of light and dark rather than the
brightness - because greying also shifts the overall level.

Why several exemplars per card
------------------------------
Two things move under the artwork. Greyed cards get an **animated diagonal shine** that
sweeps across them, and the window has been captured at 393x700, 449x800 and 787x1400, so
the block averaging lands on different pixels. One exemplar per card scored 8 of 9 with the
worst hit at 21.5 against a wrong answer at 23.1 - a margin too thin to trust. Several
exemplars, matched by nearest, put every correct answer at or below 13.6 and every wrong
one at or above 24.2. `MATCH_LIMIT` sits in that gap.

Measured, leave-one-out, on the 22 exemplars below: 18 of 21 named correctly (fireball has
only one exemplar so it cannot be held out), and the 3 that fail all fail *above* the limit
- so they come back as "unknown" rather than as a wrong name. That is the behaviour worth
having: this library never has to be right, it has to never be confidently wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "game-screen-probe"))

from probe import read_png, thumbnail_from_bgra  # noqa: E402

OUT = HERE / "out"

# The panel geometry lives in `hand.py`; imported rather than repeated so a change to the
# geometry cannot silently invalidate a library cut against the old one.
sys.path.insert(0, str(HERE))
from hand import (GREY_BELOW, SLOT_COLS, SLOT_ROWS, saturation,  # noqa: E402
                  signature, slot_box)

# name -> (elixir cost, role). The costs are read off the pink circle on each card in the
# frames; the roles are the strategy's own vocabulary and are the only judgement in here.
DECK = {
    "goblins":   (2, "defence"),
    "knight":    (3, "defence"),
    "minions":   (3, "support"),
    "arrows":    (3, "spell"),
    "archers":   (3, "support"),
    "minipekka": (4, "defence"),
    "musketeer": (4, "support"),
    "fireball":  (4, "spell"),
    "giant":     (5, "tank"),
}

# (card, frame, slot). Identified by eye at 4x-6x zoom, one card at a time.
#
# There are nine cards here and a Clash Royale deck holds eight, so at least one of these is
# not in the deck currently being dealt. That is not a contradiction to resolve: the frames
# span several sessions and the Training Camp deck is not the same every time. It was found
# the hard way - a live board showed Goblins, Mini P.E.K.K.A., Archers and Fireball, and a
# library that knew seven cards named none of the four. Goblins and Archers were simply
# absent; Fireball had a single exemplar and missed its own card by 32. So the rule this list
# follows is to keep every card ever identified rather than to model one deck, and to give
# every card at least two exemplars - one is not a library entry, it is a coincidence waiting
# to be tested.
EXEMPLARS = [
    ("knight", "m1-t000", 1), ("knight", "m1-t060", 2),
    ("minions", "m1-t000", 2), ("minions", "m1-t121", 2), ("minions", "m1-t120", 1),
    ("minipekka", "m1-t000", 3), ("minipekka", "t151", 4), ("minipekka", "t091", 4),
    ("musketeer", "m1-t000", 4), ("musketeer", "t121", 2),
    ("musketeer", "t151", 2), ("musketeer", "t030", 2),
    ("arrows", "m1-t120", 2), ("arrows", "t121", 3), ("arrows", "t151", 3),
    ("arrows", "t030", 3), ("arrows", "m1-t060", 4),
    ("giant", "m1-t120", 4), ("giant", "m1-t121", 3), ("giant", "t030", 4),
    ("giant", "t121", 4), ("giant", "m1-t060", 3),
    # Fireball is the cautionary one. It had a single exemplar for a long time, and that
    # exemplar was the worst rendering the card has: greyed *and* caught mid-shine. So a live
    # colour Fireball missed its own card by 32 and read as unknown for a whole match. All
    # three phases are here now - two greyed at different points in the shine, one in colour.
    ("fireball", "m1-t121", 1), ("fireball", "t091", 2),
    ("fireball", "strategy-stuck", 4),
    # From the live board the run above landed on. Slot 2 of that frame is a Mini P.E.K.K.A.
    # drawn *selected* - larger, lit, shifted up by a stray tap - and is deliberately not
    # cut: a selected card is a different picture, and one exemplar of it would be the only
    # thing in this library that had to be right about the interface rather than the artwork.
    # These two have one exemplar each and so cannot be held out by `leave_one_out`, which
    # means they are unverified. Frames from the next match are what fixes that.
    ("goblins", "strategy-stuck", 1),
    ("archers", "strategy-stuck", 3),
]


# (frame, slot) pairs that are **not cards**, used to bound MATCH_LIMIT from above.
#
# Needed because leave-one-out alone cannot bound it. Once the state split removed every
# collision, "the best a wrong answer managed" had no wrong answers to measure and the limit
# came out at five hundred million - a library that would confidently name a photograph of a
# barbarian as a Musketeer. The limit has to be bounded by something real, and the real thing
# is the distance at which not-a-card sits: these are card-slot boxes on a loading screen, a
# result screen and two off-board captures. Every one of them must come back unknown, and how
# close the nearest of them gets is the ceiling.
NEGATIVES = [
    ("strategy-m1-t000", 1), ("strategy-m1-t000", 2),
    ("strategy-m1-t000", 3), ("strategy-m1-t000", 4),
    ("no-board", 1), ("no-board", 2), ("no-board", 3), ("no-board", 4),
    ("t182", 1), ("t182", 2), ("t182", 3), ("t182", 4),
    ("m1-end", 1), ("m1-end", 2),
]


def cells_of(frame: str, slot: int) -> bytes:
    """The downsampled artwork of one slot of one saved frame.

    `thumbnail_from_bgra` and not `Controller.grab`: the driver reads the panel with one
    capture and downsamples in Python for exactly this reason. GDI's HALFTONE StretchBlt
    and a block average do not agree closely enough to build a library with one and match
    it with the other, and that mismatch would show up as a library that works offline and
    names nothing live.
    """
    bgra, width, height = read_png(str(OUT / f"battle-{frame}.png"))
    return thumbnail_from_bgra(bgra, width, height, SLOT_COLS, SLOT_ROWS, slot_box(slot))


def cut(frame: str, slot: int) -> tuple[int, ...]:
    """One exemplar's signature, through the same code the driver will use at runtime."""
    return signature(cells_of(frame, slot))


def state_of(frame: str, slot: int) -> str:
    """Whether that slot was drawn greyed or in colour, by the runtime test.

    Derived rather than hand-labelled on purpose. The state decides which half of the
    library an exemplar belongs in, and it is the same question `hand.read_band` asks of a
    live slot using the same threshold - so a hand-written label here could disagree with
    the reader and put an exemplar somewhere it would never be looked for.
    """
    return "grey" if saturation(cells_of(frame, slot)) <= GREY_BELOW else "ready"


def library() -> dict[str, dict[str, list[tuple[int, ...]]]]:
    """state -> card -> exemplars. Nested this way round because that is the order the
    lookup happens in: the reader knows the state before it knows the card."""
    out: dict[str, dict[str, list[tuple[int, ...]]]] = {}
    for card, frame, slot in EXEMPLARS:
        out.setdefault(state_of(frame, slot), {}).setdefault(card, []).append(
            cut(frame, slot))
    return out


def distance(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def leave_one_out() -> tuple[int, int, float, float, list[str]]:
    """Score the library against itself with each exemplar held out.

    Returns hits, testable, the worst distance a *correct* answer needed, the best distance a
    *wrong* answer managed, and a line per failure. The gap between those two numbers is
    where the threshold has to live, and printing both is the only way to see whether there
    is a gap at all rather than a threshold picked to make the number look good. The failure
    lines matter as much: the first version of this printed only the totals, and "21 of 25"
    hid the fact that every one of the four misses was a greyed card - which was the whole
    diagnosis.

    Scored **within state**, because that is how `hand.name_of` matches. Scoring across
    states would report a library far worse than the one actually used, and would have kept
    reporting failures after they were fixed.
    """
    signatures = {(f, s): cut(f, s) for _, f, s in EXEMPLARS}
    states = {(f, s): state_of(f, s) for _, f, s in EXEMPLARS}
    counts: dict[tuple[str, str], int] = {}
    for card, frame, slot in EXEMPLARS:
        key = (states[(frame, slot)], card)
        counts[key] = counts.get(key, 0) + 1

    hits = testable = 0
    worst_right, best_wrong = 0.0, 1e9
    failures: list[str] = []
    for card, frame, slot in EXEMPLARS:
        state = states[(frame, slot)]
        if counts[(state, card)] < 2:
            continue
        testable += 1
        ranked = sorted((distance(signatures[(frame, slot)], signatures[(f, s)]), c)
                        for c, f, s in EXEMPLARS
                        if (f, s) != (frame, slot) and states[(f, s)] == state)
        best, named = ranked[0]
        if named == card:
            hits += 1
            worst_right = max(worst_right, best)
        else:
            best_wrong = min(best_wrong, best)
            own = min([d for d, c in ranked if c == card] or [float("inf")])
            failures.append(f"{card} {state} from {frame} slot {slot}: nearest was "
                            f"{named} at {best:.1f}, its own card at {own:.1f}")

    # The negative controls bound the limit from above whether or not any exemplar collided.
    # Scored against the whole library rather than within state: a thing that is not a card
    # has no state, and the reader will guess one for it from saturation - so the honest
    # question is how close it gets to *anything* the library holds.
    for frame, slot in NEGATIVES:
        mine = signature(cells_of(frame, slot))
        nearest = min(distance(mine, signatures[(f, s)]) for _, f, s in EXEMPLARS)
        if nearest < best_wrong:
            best_wrong = nearest
            failures.append(f"nearest non-card: {frame} slot {slot} at {nearest:.1f} "
                            f"(this is the ceiling, not a bug)")
    return hits, testable, worst_right, best_wrong, failures


def source() -> str:
    lib = library()
    hits, testable, worst_right, best_wrong, _ = leave_one_out()
    lines = [
        '"""The deck, as the driver can recognise it. Generated - see reference.py.',
        "",
        f"Leave-one-out on the exemplars this was cut from: {hits} of {testable} named",
        f"correctly, the worst correct answer needing {worst_right:.1f} and the best wrong",
        f"one managing {best_wrong:.1f}. MATCH_LIMIT sits between those two, so a wrong",
        "answer comes back as None instead.",
        "",
        "COST and ROLE are hand-written in reference.py. SIGNATURES are mean-removed 6x6",
        "luminance patterns, several per card because greyed cards carry a moving shine and",
        "the window has been captured at three different sizes.",
        "",
        "**Keyed by state first, then by card.** A greyed card is matched only against greyed",
        "exemplars: the shine on a greyed card dominates its signature, so greyed cards of",
        "different names look more alike than a greyed card and its own colour artwork. A card",
        "with no exemplar in the state it is seen in reads as unknown rather than guessing",
        "across states.",
        '"""',
        "",
        f"MATCH_LIMIT = {round((worst_right + best_wrong) / 2)}",
        "",
        "COST = {",
    ]
    for name in sorted(DECK):
        lines.append(f"    {name!r}: {DECK[name][0]},")
    lines += ["}", "", "ROLE = {"]
    for name in sorted(DECK):
        lines.append(f"    {name!r}: {DECK[name][1]!r},")
    lines += ["}", "", "SIGNATURES = {"]
    for state in sorted(lib):
        lines.append(f"    {state!r}: {{")
        for name in sorted(lib[state]):
            where = [f"{f} slot {s}" for c, f, s in EXEMPLARS
                     if c == name and state_of(f, s) == state]
            lines.append(f"        # cut from {', '.join(where)}")
            lines.append(f"        {name!r}: (")
            for sig in lib[state][name]:
                body = ", ".join(str(v) for v in sig)
                lines.append(f"            ({body}),")
            lines.append("        ),")
        lines.append("    },")
    lines += ["}", ""]
    return "\n".join(lines)


def main() -> None:
    missing = [f"battle-{f}.png" for _, f, _ in EXEMPLARS
               if not (OUT / f"battle-{f}.png").exists()]
    if missing:
        raise SystemExit(
            "STOPPING: these frames are not in out/, so the library cannot be rebuilt: "
            + ", ".join(sorted(set(missing)))
            + ". out/ is gitignored; recapture them with battle.py before rebuilding.")

    lib = library()
    for state in sorted(lib):
        thin = sorted(name for name in lib[state] if len(lib[state][name]) < 2)
        print(f"{state:6}: {len(lib[state])} cards, "
              f"{sum(len(v) for v in lib[state].values())} exemplars"
              + (f"; only one exemplar each, so untestable: {', '.join(thin)}"
                 if thin else ""))
    missing_state = sorted(set(DECK) - set(lib.get("grey", {})) - set(lib.get("ready", {})))
    if missing_state:
        print(f"  no exemplar at all: {', '.join(missing_state)}")

    hits, testable, worst_right, best_wrong, failures = leave_one_out()
    print(f"leave-one-out within state: {hits} of {testable} named correctly")
    print(f"  worst correct answer needed {worst_right:.1f}")
    print(f"  best wrong answer managed   {best_wrong:.1f}")
    for line in failures:
        print(f"  {'ceiling' if line.startswith('nearest non-card') else 'MISS   '} {line}")
    if best_wrong <= worst_right:
        raise SystemExit(
            "STOPPING: a wrong answer scored at least as well as the worst correct one, so "
            "there is no threshold that separates them. Refusing to write a library that "
            "cannot say 'unknown' honestly - add exemplars for the cards that collide, "
            "using the MISS lines above to see which ones they are.")
    path = Path(__file__).resolve().parent / "cards.py"
    path.write_text(source(), encoding="utf-8")
    print(f"wrote {path.name}: {len(EXEMPLARS)} exemplars across "
          f"{len(set(DECK))} cards, MATCH_LIMIT {round((worst_right + best_wrong) / 2)}")


if __name__ == "__main__":
    main()
