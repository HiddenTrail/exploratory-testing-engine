"""Screens this client has been seen to have, carried from a recon pass.

Does this break "screens are output"?
-------------------------------------
`session.py` says a list of screen names written down here would let the run grade
its own homework, and that is still true of a *hand-written* list. This is not one.
Every screen below was measured by a game-ontology recon pass against this client -
fingerprint, volatile mask, name and purpose - and it is carried as a **prior the run
can contradict**, which is a different thing in four specific ways:

- Discovery still works unchanged. A frame that matches nothing here becomes
  `screen-N` exactly as before, so the run can still find screens this pass never saw.
- A match reports its agreement score, so a fingerprint that has gone stale shows up
  as a weak match rather than as a confident wrong name.
- Screens carried but never matched during a run are recorded as such. That is a
  finding: either the client changed, or that screen is unreachable from an action
  space of five taps - and the second is worth knowing before concluding anything
  about coverage.
- Nothing here is compared by name. Identity is a fingerprint comparison using
  `recon.agreement`, the same function and the same threshold the fingerprints were
  measured under.

What it buys, and why it is worth the coupling
---------------------------------------------
Mostly one thing: **the run can now recognise a screen it must not be on.** The recon
reached the Offers/Shop screen and a battle result screen. Before this, the only
tripwire was the elixir bar, so a run that somehow reached a purchase flow would have
registered it as an ordinary `screen-2`, recovered from it, and carried on - and the
report would have read as a clean run. See `ABORT_ON`.

Secondarily: a screen gets a name and a purpose instead of `screen-3`, and the
Driver gets measured settle times to predict against. Both are conveniences. The
tripwire is the reason.

Staleness is the honest cost
----------------------------
These are measurements with a date on them, taken against a client that updates
itself and has resized its own window between sessions. `SOURCE` carries the
provenance so that a run finding no matches at all can be read as "the reference is
old" rather than "the game changed" - and `check_reference` refuses to run at all if
the file is missing or has lost its abort screens, because a tripwire that silently
matches nothing is worse than no tripwire.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "known_screens.json"


class ReferenceMissing(RuntimeError):
    """The carried reference is absent or unusable. Never caught."""


def _load() -> dict:
    if not _PATH.exists():
        raise ReferenceMissing(
            f"{_PATH.name} is missing. Regenerate it with "
            f"`python -m engine.adapters.clash_royale.extract_reference <recon pass dir>`."
        )
    return json.loads(_PATH.read_text(encoding="utf-8"))


_DATA = _load()

SOURCE: dict = _DATA["source"]
GRID_COLS, GRID_ROWS = _DATA["grid"]
NCELLS = GRID_COLS * GRID_ROWS

# The recon's own calibrated threshold, not a number picked next to it. Carried
# because these fingerprints were measured under it: the admissible range for this
# client was [0.896, 0.974] and the pass ran at 0.94 with a median match score of
# 1.0 and no screens split by name. Anything looser merges screens; anything tighter
# calls an animating screen a new one.
SCREEN_MATCH: float = _DATA["screen_match"]
CELL_DELTA: int = _DATA["cell_delta"]

# Which carried screen is the home screen, classified by hand in
# `extract_reference.MAIN_SCREEN`. Used for one thing: refusing to start a run whose
# very first frame is positively identified as somewhere that is not it.
MAIN_SCREEN: str = _DATA["main_screen"]


@dataclass(frozen=True)
class Appearance:
    """One stored picture of a screen: the representative, or one of its variants.

    Variants matter more than they look like they should. The main screen alone had
    five - chest timers, a clan banner, an event badge all change what it looks like
    without making it somewhere else - so matching only the representative would
    call four of those five appearances a new screen.
    """
    key: str
    fingerprint: bytes
    volatile: frozenset[int]


@dataclass(frozen=True)
class KnownScreen:
    id: str
    name: str | None
    purpose: str | None
    verdict: str
    why: str
    identity_is_weak: bool
    animated_cells: int
    appearances: tuple[Appearance, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        """What to call this in a log. Never invents a name for an unnamed screen -
        the recon saw sc03, sc05 and sc10 and never labelled them, and reporting
        `sc05` plainly is more honest than guessing what it was."""
        return f"{self.id} ({self.name})" if self.name else f"{self.id} (unnamed)"


def _appearances(record: dict) -> tuple[Appearance, ...]:
    made = [Appearance(key=record["id"],
                       fingerprint=base64.b64decode(record["fingerprint_b64"]),
                       volatile=frozenset(record["volatile"]))]
    for variant in record["variants"]:
        made.append(Appearance(key=variant["id"],
                               fingerprint=base64.b64decode(variant["fingerprint_b64"]),
                               volatile=frozenset(variant["volatile"])))
    return tuple(made)


KNOWN_SCREENS: tuple[KnownScreen, ...] = tuple(
    KnownScreen(
        id=record["id"], name=record["name"], purpose=record["purpose"],
        verdict=record["verdict"], why=record["why"],
        identity_is_weak=record["identity_is_weak"], animated_cells=record["animated_cells"],
        appearances=_appearances(record),
    )
    for record in _DATA["screens"]
)

BY_ID: dict[str, KnownScreen] = {screen.id: screen for screen in KNOWN_SCREENS}

# Screens a meta-game-only run stops on sight. Derived from the classification in
# `extract_reference.VERDICTS`, which is written by hand per screen and refuses to
# extract a pass containing a screen nobody has classified.
ABORT_ON: tuple[KnownScreen, ...] = tuple(s for s in KNOWN_SCREENS if s.verdict == "abort")

# Measured tap transitions: where a tap went, and how long the client took to settle.
# Only taps - every drag in the source pass was dropped on the way through, because
# the action space has none and a prior for an input that cannot be sent is a fact
# the Driver can neither use nor check.
TAP_TRANSITIONS: tuple[dict, ...] = tuple(_DATA["tap_transitions"])


def check_reference() -> str:
    """Prove the carried reference is usable, or raise. Returns what to print.

    The same fail-closed shape as `actions.preflight`, and for the same reason: the
    dangerous failure here is silent. A reference that loaded but has no abort
    screens gives a run a tripwire that matches nothing, which produces a clean
    report about a run that had no protection at all.
    """
    if not KNOWN_SCREENS:
        raise ReferenceMissing(
            f"{_PATH.name} loaded but contains no screens, so no screen can be recognised and the "
            f"shop tripwire cannot fire. Regenerate it from a recon pass."
        )
    if not ABORT_ON:
        raise ReferenceMissing(
            f"{_PATH.name} has {len(KNOWN_SCREENS)} screen(s) but none classified 'abort', so a "
            f"run could reach the shop or a battle result screen and treat it as ordinary. Check "
            f"VERDICTS in extract_reference.py."
        )
    if MAIN_SCREEN not in BY_ID:
        raise ReferenceMissing(
            f"main_screen is {MAIN_SCREEN!r}, which is not one of {', '.join(BY_ID)}. The run "
            f"would then be unable to tell whether it started on the home screen."
        )
    sized = [a.key for s in KNOWN_SCREENS for a in s.appearances
             if len(a.fingerprint) != NCELLS * 3]
    if sized:
        raise ReferenceMissing(
            f"these fingerprints are not {NCELLS} cells of BGR: {', '.join(sized)}. They cannot be "
            f"compared against a frame this adapter grabs, and would disagree with everything - "
            f"which reads as 'every screen is new' rather than as an error."
        )

    appearances = sum(len(s.appearances) for s in KNOWN_SCREENS)
    lines = [
        f"Screen reference carried from {SOURCE['pass']}:",
        f"  {len(KNOWN_SCREENS)} screen(s), {appearances} stored appearance(s), "
        f"{len(TAP_TRANSITIONS)} measured tap transition(s)",
        f"  grid {GRID_COLS}x{GRID_ROWS}, screen_match {SCREEN_MATCH}, cell_delta {CELL_DELTA}",
        f"  home screen: {BY_ID[MAIN_SCREEN].label} - a run refuses to start anywhere else",
        f"  {len(ABORT_ON)} screen(s) the run stops on sight:",
    ]
    for screen in ABORT_ON:
        lines.append(f"    {screen.label}: {screen.why}")
    lines.append("  a frame matching none of these still becomes a new screen, as before")
    return "\n".join(lines)


def driver_briefing() -> str:
    """What to tell the Driver about screens someone has already been to.

    Explicitly framed as a prior rather than as a fact, because it is a measurement
    with a date on it and the Driver's job includes noticing that it no longer holds.
    """
    lines = [
        f"SCREENS PREVIOUSLY MEASURED ON THIS CLIENT, from an earlier exploratory pass "
        f"({SOURCE['pass']}, {SOURCE['actions']} actions over {SOURCE['session_seconds']:.0f}s). "
        f"Treat every line as a PRIOR, not a fact: the client updates itself, and a screen that no "
        f"longer matches its stored fingerprint is a finding worth reporting rather than an error. "
        f"Screens are matched by fingerprint, never by name, so a name here is only a label for "
        f"something already identified.",
        "",
    ]
    for screen in KNOWN_SCREENS:
        note = " [the run ABORTS on sight of this]" if screen.verdict == "abort" else ""
        weak = " [identity flagged unstable by that pass]" if screen.identity_is_weak else ""
        lines.append(f"  {screen.label}{note}{weak}")
        if screen.purpose:
            lines.append(f"    {screen.purpose}")
        else:
            lines.append("    that pass never labelled this screen, so nothing is known about it "
                         "beyond the fact that it exists")
    # Transitions *from* a screen the run aborts on are left out. Eleven of the
    # twenty-three carried ones are taps on the battle result screen, and putting
    # them in front of the Driver would be handing it timing priors for a place it
    # must never be - two thirds of this section spent inviting reasoning about a
    # screen that ends the run on sight. They stay in the JSON, which is a record of
    # what a pass measured; this is a briefing for a run that cannot go there.
    usable = [t for t in TAP_TRANSITIONS
              if (BY_ID.get(t["from"]) is None or BY_ID[t["from"]].verdict != "abort")]
    if usable:
        lines += [
            "",
            "TAPS THAT PASS ACTUALLY SENT, with how long the client took to settle. Its taps were "
            "aimed at its own points, not at this action space's five, so treat these as a guide to "
            "TIMING rather than as a map: an effect of 'none' means nothing changed, 'variant' "
            "means the same screen changed slightly (a highlight, a counter), 'screen' means it "
            "went somewhere else. Taps it made on screens this run aborts on are left out.",
        ]
        for t in usable:
            lines.append(f"  {t['from']} -> {t['to']} at ({t['at'][0]:.3f}, {t['at'][1]:.3f}): "
                         f"{t['effect']}, {t['changed_cells']} cells changed, settled in "
                         f"{t['settle_ms']}ms")
    return "\n".join(lines)
