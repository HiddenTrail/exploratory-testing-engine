"""The decisions the kit makes about a machine, separated from the Win32 calls that feed them.

Why the seam is here
--------------------
Nothing in this file can touch a window. Every function is arithmetic over numbers
somebody else measured, and that buys one specific thing: the rules that decide whether a
run may start are testable on a machine with no game, no emulator and no Win32 API - which
is where CI runs, and where the colleague this kit is for will read the test output before
he ever opens the client. `preflight.py` is the half that grabs frames and is Windows-only.
This is the half that decides what a grab *means*, and it is not.

The split also names the mistake it exists to stop. Every frame-comparison constant in this
project was calibrated against a lobby that has since changed: the account progressed, the
lobby gained an animated offer banner and a ticking countdown, and idle animation went from
1 cell of 576 to 132 of 2304. That is past the readiness gate's tolerance, so a live and
perfectly readable client died with `window never rendered a settled frame`. A number that
decides whether a run may start therefore has to be re-derived per session - and a
re-derivation nobody can test is exactly how the next stale constant gets written.

The one thing this deliberately does not do
-------------------------------------------
It never concludes a client is dead from a lack of movement. A live, logged-in lobby was
measured sitting at a steady 1 cell of 576 for ninety seconds while genuinely rendering -
the *content* proved it, a countdown appeared on the Battle button, and the cell count
denied it. So `drift_reading` reports movement as evidence and says what it cannot rule
out, rather than returning a verdict. `wait_live.py` learned this the expensive way and the
kit is not going to relearn it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# The reference is the one part of the engine's Clash Royale adapter that needs no Win32 -
# it is a JSON file of measured fingerprints and a few dataclasses - so importing it here
# is free, and it is what supplies the grid every number below is expressed in. Comparing
# against a different grid would not be a tuning choice, it would mean scoring measurements
# under conditions they were never taken under.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.adapters.clash_royale import reference  # noqa: E402

NCELLS = reference.NCELLS
GRID = (reference.GRID_COLS, reference.GRID_ROWS)

# Cells of slack past the widest movement an idle screen was seen to make. Lifted from
# `game-ontology/calibrate.py` with its reasoning intact: a session sees the widest idle
# twitch it happened to catch, not the widest one that exists, and a threshold cut exactly
# at the observed maximum splits the first slightly wider one into a screen of its own.
SLACK_CELLS = 2

# Bounds on the derived threshold, also calibrate.py's. Below the floor a screen has to
# reproduce so little of itself that anything matches anything; above the ceiling nothing
# survives a single frame of animation. Both are properties of the measure, not of a game.
MATCH_FLOOR, MATCH_CEILING = 0.80, 0.99

# Movement at or under this is indistinguishable from a stale frame plus capture noise -
# a lobby's slow water/flag cycle measured 4-5 cells of 576. Used only to phrase what a
# reading cannot rule out, never to refuse a run.
NOISE_CELLS = 12


class Refuse(RuntimeError):
    """A run must not start, and the message is the whole of what the operator sees.

    Carried as an exception rather than a return code because every raise site is a place
    where continuing would send input at a client in a state nobody planned for, and a
    caller that forgot to check a return code would do exactly that.
    """


@dataclass(frozen=True)
class DriftReading:
    """What an idle window did while nobody touched it.

    `worst` rather than `mean` is the number the threshold is cut from, because the
    threshold has to hold the *widest* idle moment together. The lobby animates on a cycle
    longer than a second, so a single one-second sample of a healthy lobby reads zero
    movement about four times in five - measured live: 5, 0, 0, 0, 0, 5. Averaging that
    would report a lobby as almost perfectly still and then cut a threshold no frame of it
    can clear.
    """
    samples: tuple[int, ...]
    ncells: int

    @property
    def worst(self) -> int:
        return max(self.samples, default=0)

    @property
    def agreement(self) -> float:
        """The worst sample expressed the way `recon.agreement` scores a frame."""
        return 1.0 - self.worst / self.ncells

    def line(self) -> str:
        seen = ", ".join(str(s) for s in self.samples)
        note = (f"which is at or under the {NOISE_CELLS} cells that capture noise alone can "
                f"produce, so this cannot tell a live screen from a frozen one"
                if self.worst <= NOISE_CELLS else
                "so the picture is genuinely moving and the client is rendering")
        return (f"idle drift over {len(self.samples)} samples: {seen} cells of {self.ncells} "
                f"(worst {self.worst}, agreement {self.agreement:.3f}) - {note}")


@dataclass(frozen=True)
class Threshold:
    """A screen-match cut, and the argument for it.

    `why` is a field rather than something the caller composes, because this number ends up
    in the wiki's overview page as the provenance of every screen identity in the run. A
    threshold with no argument attached is the thing this kit exists to stop shipping.
    """
    value: float
    measured: float
    calibrated: float
    clamped: str
    why: str

    @property
    def looser_than_calibrated(self) -> bool:
        return self.value < self.calibrated


def screen_match_for(drift: DriftReading, calibrated: float) -> Threshold:
    """The tightest screen-match cut that still admits this session's own idle animation.

    Tight rather than midway between "idle" and "a real transition", for the reason
    calibrate.py gives: the gap between those two populations is not evidence about where
    the boundary sits, and the two errors are not comparable. Too tight invents a screen per
    animation frame, which is a cluttered map somebody can read past. Too loose lets one
    screen absorb its neighbours, and then its volatile mask grows over the very cells that
    would have told them apart and no later pass can undo it.

    The calibrated value is passed in to be *reported against*, not to be blended with. If a
    session needs a looser cut than the file on disk, that is the finding - it means the
    client changed since the file was written - and averaging the two would hide it.
    """
    loosest = 1.0 - (drift.worst + SLACK_CELLS) / drift.ncells
    value = round(min(MATCH_CEILING, max(MATCH_FLOOR, loosest)), 3)
    clamped = ("floor" if loosest < MATCH_FLOOR else
               "ceiling" if loosest > MATCH_CEILING else "")

    why = (f"the widest idle moment moved {drift.worst} of {drift.ncells} cells, so a cut at "
           f"{value} is the most demanding one under which this screen still reads as itself "
           f"({SLACK_CELLS} cells of slack past what was seen)")
    if clamped == "floor":
        why += (f". Clamped up to the {MATCH_FLOOR} floor: the raw derivation wanted "
                f"{loosest:.3f}, under which a frame need only reproduce that fraction of a "
                f"screen to be filed as it, and nothing useful is measurable there")
    elif clamped == "ceiling":
        why += (f". Clamped down to the {MATCH_CEILING} ceiling: the raw derivation wanted "
                f"{loosest:.3f}, which no frame of an animating game survives")
    if value < calibrated:
        why += (f". This is looser than the {calibrated} in the calibration file, which means "
                f"the client animates more now than when that was measured - report it rather "
                f"than treat it as noise")
    elif value > calibrated:
        why += (f". This is tighter than the {calibrated} in the calibration file, so screens "
                f"that file would have merged may be told apart in this pass")

    return Threshold(value=value, measured=round(loosest, 3), calibrated=calibrated,
                     clamped=clamped, why=why)


@dataclass(frozen=True)
class Baseline:
    """Where the run is about to start from, and whether that is allowed.

    Three outcomes rather than two, and the middle one is the point. A run takes its first
    screen as the place it returns to after every discovery, so starting somewhere else is
    not a safety problem - it is a *labelling* problem that produces findings which are
    entirely artefacts: `return_to_main` reads as a navigation to somewhere new and
    `open_cards` reads as a control that does nothing. Both look like findings. Neither is.
    """
    verdict: str          # "ok" | "refuse" | "warn"
    message: str


def baseline_verdict(screen: str, agreement: float, label: str, carried: bool) -> Baseline:
    """Judge the first frame of a session against the carried main screen.

    A frame that matched some *other* measured screen is refused, because the client is
    demonstrably somewhere a person can navigate away from. A frame that matched nothing at
    all only warns, because the likeliest cause is a stale reference rather than a misplaced
    client - the game updates itself and the fingerprints carry a date - and refusing would
    mean one game update makes the kit unrunnable until somebody regenerates them.
    """
    home = reference.BY_ID[reference.MAIN_SCREEN]
    if screen == reference.MAIN_SCREEN:
        return Baseline("ok", f"Started on {label}, agreement {agreement:.3f} against the "
                              f"fingerprint measured in {reference.SOURCE['pass']}.")
    if carried:
        return Baseline("refuse", (
            f"the client is on {label} (agreement {agreement:.3f}), not on {home.label}. A run "
            f"takes its first screen as the place it returns to after every discovery, so "
            f"starting here would make every navigation reading relative to the wrong place and "
            f"produce findings that are purely artefacts. Press back or the home tab by hand "
            f"until the main screen is up, then run again. Nothing was tapped."))
    return Baseline("warn", (
        f"the first frame matched NO carried screen (closest agreement {agreement:.3f}, below "
        f"the {reference.SCREEN_MATCH} cut), so this run cannot confirm it started on "
        f"{home.label}. Either the client is somewhere the {reference.SOURCE['pass']} pass never "
        f"went, or those fingerprints have gone stale - both are worth reporting, and every "
        f"screen name below is relative to whatever this actually is."))


def restart_verdict(attempt: int, limit: int, has_map: bool) -> tuple[bool, str]:
    """Whether a crashed recon pass may be resumed, and what to say either way.

    Resumed rather than restarted, always: a fresh pass would re-explore the screens the
    dead one already mapped and spend the remaining budget doing it again. Recon supports
    `--resume` from an `ontology.json`, so a pass that got far enough to write one is worth
    continuing and a pass that did not is worth reporting as a failure rather than looping.
    """
    if attempt > limit:
        return False, (f"the recon pass has now failed {attempt} times, past the limit of "
                       f"{limit}. Not retrying: something is wrong with the client or the "
                       f"machine rather than with this particular pass, and the artifacts "
                       f"written so far are more useful than another crash on top of them.")
    if not has_map:
        return False, ("the recon pass died before writing an ontology.json, so there is "
                       "nothing to resume from and a retry would start from zero against a "
                       "client that just killed a pass. Check the log above - the usual cause "
                       "is the client having stopped rendering, which only a relaunch fixes, "
                       "and relaunching is a person's job here.")
    return True, (f"resuming from the map the failed pass wrote (attempt {attempt} of "
                  f"{limit}), so the screens it already found are not re-explored.")
