"""One live client, observed as a state machine.

What this makes observable, and what it deliberately does not
-------------------------------------------------------------
The SUT is a game rendered as pixels. It has no API, no logs and no DOM, so the
observation layer answers the two questions a frame can answer honestly:

- **which screen is this**, by agreement against a growing library of screens the
  run has already seen, and
- **how long did it take to settle**, which is the cheapest available signal for
  "that action did something substantial".

It does *not* try to read what is on a screen. The android-bot experiment can
name a Clash Royale card from its artwork, and doing that took a signature
library, a state split, three thresholds and several sessions of measurement -
all of it specific to the card panel of one game. None of that is available for a
screen nobody has measured, so a reader here would be inventing content it cannot
see. Screen identity and settle time are the two things a frame yields without a
per-screen calibration, which makes them the two things this can be honest about.

Screens are still output, and are now also a prior
--------------------------------------------------
No screen name in this package is hand-authored. Every frame is identified by
comparison, anything unrecognised becomes a new screen, and the run can contradict
anything it was given - the same discipline `experiments/game-ontology/` holds
itself to, and for the same reason: a list of this game's screens written down by
hand would let the run grade its own homework.

What it *is* given is `reference.py`: eleven screens an earlier recon pass measured
against this same client, carried as dated fingerprints with provenance. That is a
measurement, not a declaration, and the four things that keep it one are argued in
`reference.py`'s docstring. The reason it is worth having is in the next section.

The Driver still cannot predict a screen by *name* on a first visit - it is never
shown which fingerprint is about to match - so what it predicts stays structural:
same screen, a screen already seen, or somewhere new. See `adapter.PREDICTIONS`.

Two tripwires
-------------
`observe` refuses, hard and uncatchably, on either of two things.

The elixir bar, which is on a board and nowhere else - measured 17%-87% on every
board frame and 0%-1% on every frame that is not one. The scope this adapter was
given is the meta-game, so a board appearing means something has gone wrong in a
way no prediction accounts for, and the run stops rather than keep sending taps
into a live match.

And a screen classified `abort` in the carried reference: the Offers/Shop screen,
two clan screens, a battle result screen. This is the tripwire the carried data
bought, and it closes a real hole - before it, a run that somehow reached a
purchase flow would have registered it as an ordinary new screen, recovered from
it, and produced a report that read clean.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from engine.adapters.clash_royale import reference
from engine.adapters.clash_royale.actions import BY_NAME, RECOVERY, Unsafe, preflight

# The harness and the readers live in experiments/, which the engine README calls
# an untouched historical archive. Importing across that line rather than porting
# 1,600 lines of Win32 window handling is a debt, taken knowingly: the controller
# is the part of this that has been hardened against a real client - a silently
# frozen window, a Chrome tab with the same title, a resize between sessions - and
# a fresh copy would be a fresh copy of none of that.
_EXPERIMENTS = Path(__file__).resolve().parents[3] / "experiments"
for _path in (_EXPERIMENTS / "game-ontology", _EXPERIMENTS / "android-bot",
              _EXPERIMENTS / "game-screen-probe"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _harness():
    """The bot's own modules, imported on call rather than at module load.

    `controller` calls `ctypes.WinDLL` at import time, so importing it on Windows
    is fine and importing it anywhere else is not. Every test in this package that
    does not drive a real window must be able to run without a Win32 API present,
    which means this import cannot happen while the adapter module is being read -
    and `registry.py` imports the adapter module to answer `--adapter clash_royale`.

    `attach` rather than `target.resolve`: a Play Games title has no executable, so
    the whole discovery path every other target used is unavailable, and
    `attach.attach` is the replacement - one unowned visible window with the right
    name whose process is the emulator. It builds the `Target`, denylist included,
    which is why nothing here resolves one separately.

    `recon` is in here for the comparison functions, not for the recon itself: the
    carried fingerprints were measured by `recon.fingerprint` and matched by
    `recon.agreement`, so using those two rather than a local copy of the same
    arithmetic means the comparison this does is the comparison the data was
    produced under. A reimplementation would be a second stride to get wrong, and a
    fingerprint compared on the wrong stride does not error - it disagrees with
    everything, which reads as "every screen is new".
    """
    import attach  # noqa: E402
    import battle  # noqa: E402
    import controller  # noqa: E402
    import recon  # noqa: E402
    return attach, battle, controller, recon


def recon_fingerprint(handle) -> bytes:
    """One frame in the exact form the carried fingerprints are stored in.

    A thin wrapper so there is one place this happens: `recon.fingerprint` grabs at
    32x18 and strips the alpha byte, giving 576 cells of BGR. Grabbing here and
    stripping locally would be the same three lines and the second chance to get
    the stride wrong.
    """
    _, _, _, recon = _harness()
    return recon.fingerprint(handle)


# The grid and the threshold are both the carried pass's, not this file's. They are
# not free parameters: the fingerprints in `reference.py` are 32x18 cells of BGR
# matched at SAME_SCREEN (whatever `known_screens.json` carries - re-extracted per
# pass, not a constant), and a different grid or a looser cut here would not be a
# tuning choice, it would mean comparing those measurements under conditions they
# were never taken under. `reference.check_reference` refuses a file whose grid
# disagrees.
GRID_COLS, GRID_ROWS = reference.GRID_COLS, reference.GRID_ROWS
SAME_SCREEN = reference.SCREEN_MATCH

# Fraction of the elixir strip that must be pink before this refuses to continue.
# Well under the 17% floor measured across board frames, because this is a
# tripwire and the expensive mistake is the one where it does not fire.
BOARD_TRIPWIRE = 0.08


@dataclass(frozen=True)
class Candidate:
    """One stored picture a frame can be compared against.

    Carried appearances and screens this run discovered for itself are the same
    kind of thing here on purpose: identity is a fingerprint comparison either way,
    and the only difference is whether `carried` is set - which is what supplies a
    name, a purpose and a verdict for the ones somebody has already looked at.
    """
    screen: str
    appearance: str
    fingerprint: bytes
    volatile: frozenset[int]
    carried: reference.KnownScreen | None = None


def carried_candidates() -> list[Candidate]:
    """The reference, flattened into one comparison list.

    Every stored appearance becomes its own candidate, variants included. That is
    the point of carrying them: the main screen has five appearances because chest
    timers, a clan banner and an event badge each change what it looks like without
    making it somewhere else, so matching only the representative would call four
    of those five something new.
    """
    return [Candidate(screen=screen.id, appearance=appearance.key,
                      fingerprint=appearance.fingerprint, volatile=appearance.volatile,
                      carried=screen)
            for screen in reference.KNOWN_SCREENS
            for appearance in screen.appearances]


@dataclass(frozen=True)
class Observation:
    """What one frame said.

    `screen` is a carried screen's id where one matched, and otherwise a name this
    run invented for somewhere nobody has measured. `known` is False only on the
    visit that discovered a screen, so a carried screen is known on its first
    sighting - which is the whole difference the reference makes to a prediction.
    """
    screen: str
    agreement: float
    known: bool           # False on the visit that discovered this screen
    settle: float = 0.0
    first_sight: bool = False  # this run had not been to this screen before
    label: str = ""        # what to call it in a log, including a carried name
    # The carried record of whatever matched, carried on the observation rather than
    # looked up by id afterwards. Looking it up would mean the verdict came from the
    # global reference while the name came from the candidate that actually matched,
    # and those two can disagree - a candidate whose id is absent from the reference
    # would then have no verdict at all, so an abort screen would go unnoticed.
    known_screen: reference.KnownScreen | None = None

    @property
    def carried(self) -> bool:
        """Whether this matched something somebody had already measured."""
        return self.known_screen is not None

    def line(self) -> str:
        note = " FIRST SIGHT" if self.first_sight else ""
        return (f"{self.label or self.screen} (agrees {self.agreement:.3f}, "
                f"{'known' if self.known else 'NEW'}{note}, settled in {self.settle:.2f}s)")


@dataclass
class Session:
    """A live client, the screens it has been measured to have, and the ones this
    run found for itself.

    `candidates` is seeded from the reference by default rather than by the caller,
    so that the abort tripwire is present in any session anybody constructs. A test
    that wants a blank library has to ask for one explicitly - which is the right
    way round, because the failure mode of an unseeded session is that the shop
    screen looks ordinary.
    """
    controller: object
    candidates: list[Candidate] = field(default_factory=carried_candidates)
    seen: set[str] = field(default_factory=set)
    _counter: int = 0

    def _identify(self, frame: bytes) -> Observation:
        """The nearest stored appearance, or a newly registered screen.

        Nearest rather than first-over-threshold: two screens of this client can
        both clear `SAME_SCREEN` against a third - the navigation bar alone is a
        large, identical fraction of every meta-game screen - so taking the first match
        would make the answer depend on the order the candidates happen to be in,
        which for the carried ones is the order a different session discovered them.
        """
        _, _, _, recon = _harness()
        delta = self.controller.target.cell_delta

        if len(frame) != reference.NCELLS * 3:
            # Fails closed on the one comparison error that produces a plausible
            # answer instead of a crash: `diff_cells` truncates to the shorter of
            # the two, so a short frame is compared over a handful of cells and can
            # agree with anything. A run whose every frame matched the shop screen
            # at 1.000 would look like a finding rather than like a broken grab.
            raise Unsafe(
                f"ABORTING: this frame is {len(frame)} bytes, not "
                f"{reference.NCELLS * 3} ({GRID_COLS}x{GRID_ROWS} cells of BGR). Comparing it "
                f"would silently score against only the part that exists, so every screen "
                f"identification after this point would be untrustworthy - including the ones "
                f"the shop and battle tripwires depend on."
            )

        best = None
        for candidate in self.candidates:
            score, stable, _ = recon.agreement(frame, candidate.fingerprint,
                                               candidate.volatile, delta)
            # `stable` is what stops `score` from lying: a screen whose volatile
            # mask has eaten most of it is scored over what is left, and 1.0 over a
            # dozen cells is a coincidence. The floor is recon's own, so this
            # rejects exactly what the pass that produced these would have.
            if stable < recon.MIN_STABLE_CELLS:
                continue
            if best is None or score > best[0]:
                best = (score, candidate)

        if best is not None and best[0] >= SAME_SCREEN:
            score, candidate = best
            first_sight = candidate.screen not in self.seen
            self.seen.add(candidate.screen)
            return Observation(
                screen=candidate.screen, agreement=score, known=True,
                first_sight=first_sight, known_screen=candidate.carried,
                label=candidate.carried.label if candidate.carried else candidate.screen,
            )

        # Somewhere neither this run nor the carried pass has been. Named for what
        # that means rather than by position: `unknown-1` says the eleven measured
        # screens did not match, which is a more useful thing for a log to say than
        # `screen-12`. Registered as its own candidate so a second visit recognises
        # it, but never merged into the carried screen it came closest to - letting
        # a near-match absorb frames is how a stored fingerprint drifts into
        # matching things it was never measured on.
        self._counter += 1
        name = f"unknown-{self._counter}"
        self.candidates.append(Candidate(screen=name, appearance=name,
                                         fingerprint=frame, volatile=frozenset()))
        self.seen.add(name)
        return Observation(screen=name, agreement=(best[0] if best else 0.0), known=False,
                           label=f"{name} (not in the carried reference)")

    def observe(self, settle: float = 0.0) -> Observation:
        """Which screen is up. Raises `Unsafe` on a board or on a forbidden screen.

        The board tripwire is checked before the identification, not after, because
        a board would otherwise be registered as an ordinary new screen and the run
        would carry on tapping at it. The reference tripwire has to be checked after
        - being *told* which screen this is is the whole mechanism - which is why
        the board is not left to it: no carried fingerprint of a board exists at
        all, and a match at `SAME_SCREEN` is not something to stake the scope rule on.
        """
        _, battle, _, _ = _harness()
        pink = battle.elixir_showing(self.controller)
        if pink >= BOARD_TRIPWIRE:
            raise Unsafe(
                f"ABORTING: the elixir bar reads {pink:.0%} pink, which means a battle is in "
                f"progress. This adapter's scope is the meta-game only, so no prediction here "
                f"accounts for a live match and no further input will be sent. Get the client "
                f"back to the main screen by hand before running again."
            )

        where = self._identify(recon_fingerprint(self.controller))
        forbidden = where.known_screen
        if forbidden is not None and forbidden.verdict == "abort":
            raise Unsafe(
                f"ABORTING on {forbidden.label}, agreement {where.agreement:.3f}. That screen is "
                f"classified 'abort' in the carried reference: {forbidden.why}. No further input "
                f"will be sent. Leave the screen by hand, and treat this as a finding - reaching "
                f"it from an action space of five vetted taps is exactly the failure the "
                f"coordinate guard exists to prevent."
            )
        return replace(where, settle=settle)

    def act(self, action_name: str) -> dict:
        """Send one named tap and report what happened, including a refusal.

        A denylist refusal is a **result**, not an error. `Controller.click` raises
        `PermissionError`, and letting that propagate would abort a run over the
        guard doing its job - while the Driver, which is trying to build a model of
        what this interface does, learns more from "that was refused, and here is
        why" than from a crash. The refusal is reported with the guard's own reason
        text so the Driver reads the human rationale rather than a status code.
        """
        action = BY_NAME[action_name]
        before = self.observe()
        try:
            self.controller.click(*action.at)
        except PermissionError as refused:
            return {
                "action": action_name, "at": list(action.at), "what": action.what,
                "screen_before": before.screen, "verdict": "refused",
                "why": str(refused), "screen_after": before.screen,
                "screen_was": "same_screen", "settle": 0.0,
            }

        settle = self.controller.wait_stable()
        after = self.observe(settle=settle)
        if after.screen == before.screen:
            screen_was = "same_screen"
        elif after.known:
            screen_was = "known_screen"
        else:
            screen_was = "new_screen"
        return {
            "action": action_name, "at": list(action.at), "what": action.what,
            "screen_before": before.screen, "verdict": "sent",
            "screen_after": after.screen, "screen_was": screen_was,
            # What the earlier pass called this screen, where it recognised one, so
            # the log reads "sc07 (Collection/Card Deck screen)" rather than an id.
            # Separate from `screen_after` because that is what a prediction is
            # checked against and it must stay a bare, stable token.
            "screen_after_label": after.label,
            "was_measured_before": after.carried,
            "first_sight_this_run": after.first_sight,
            "agreement": round(after.agreement, 3), "settle": round(settle, 2),
        }

    def recover(self) -> str:
        """Get back to the main screen, and say whether it worked.

        Called after any action that landed somewhere new, which is the user's own
        rule turned into code: an unexpected panel is left by dismissing it or by
        going back, never by pressing on through it. Reported rather than asserted
        because a recovery that fails is the most important thing a log can say -
        the run is then somewhere nobody chose, and continuing to explore from
        there is how a session ends up somewhere it should not be.

        The carried reference is what makes "whether it worked" answerable at all.
        Before it, this could only say which screen it ended on, and no name in a
        fresh run meant anything; now the home screen has a measured fingerprint,
        so a recovery that did not reach it says so in the one field the report
        renders.
        """
        self.controller.click(*BY_NAME[RECOVERY].at)
        self.controller.wait_stable()
        where = self.observe()
        if where.screen == reference.MAIN_SCREEN:
            return where.screen
        return (f"{where.label} - NOT the main screen "
                f"({reference.BY_ID[reference.MAIN_SCREEN].label}), so the next test starts "
                f"somewhere nobody chose")


TITLE = "Clash Royale"

# How much the window may change over a second and still count as settled. The
# main screen animates by about 3% on its own - water, flags, a pulsing button -
# so this is above that and well below a transition.
IDLE_DRIFT = 0.10


def attach(verbose: bool = True) -> tuple[Session, str]:
    """Find the running client, prove the guard is loaded, and start a session.

    Returns the session and the preflight report, rather than printing it here, so
    the same text reaches the console and the run's report - see
    `adapter.render_onboarding_section`.

    The order matters twice over. `preflight` runs against `controller.target`, the
    exact object `Controller.click` consults, so it cannot pass by vetting a
    different denylist than the one that will be enforced. And it runs before
    anything is capable of clicking, so a denylist that failed to load stops the
    run at the cheapest possible moment rather than after the first tap.

    `check_reference` is the same shape of check for the second tripwire, and is
    here rather than inside `preflight` because it is a different claim: `preflight`
    proves the coordinate guard refuses the controls it was written for, and this
    proves the run can still recognise a screen it must not be on. Both fail closed,
    and both texts go into the report, because a tripwire that quietly matches
    nothing is worse than no tripwire - it produces a clean report about an
    unprotected run.
    """
    attach_module, _, controller_module, _ = _harness()
    controller_module.readable_output()
    controller_module.set_dpi_aware()

    handle = attach_module.attach(TITLE, verbose=verbose)
    report = f"{preflight(handle.target)}\n\n{reference.check_reference()}"
    if verbose:
        print(report)

    # Input goes to screen coordinates, so a window that is not in front would have
    # its taps land on whatever is. Done after preflight because focusing is the
    # first thing this does to the machine at all.
    handle.focus()
    return Session(controller=handle), report


def check_ready(adapter) -> None:
    """`SUTAdapter.check_sut_ready`: a client, off-board, still, and on the home screen.

    Four separate things, and the first three have each actually gone wrong in this
    project: the window was a Chrome tab with a matching title, the client had
    frozen while every Win32 health check said fine, and a single sample landed
    mid-animation. Raises SystemExit, so the message is the whole of what the
    operator sees - and is the reason this is a hook rather than something the loop
    discovers: a run against a client that isn't there should cost nothing to find
    out.

    The fourth is new, and only became checkable with the carried reference. A run
    that starts on, say, the card collection would take that screen as its baseline;
    `open_cards` would then read `same_screen` and `return_to_main` would read
    `new_screen`, both of which look like findings and neither of which is, and the
    mislabelling would propagate through every checkpoint. There is no way to catch
    that from a frame alone - a fresh session has nothing to compare against - so
    before the reference existed this was a real hole.
    """
    _, battle, _, _ = _harness()
    try:
        session, report = attach()
    except Unsafe:
        # Never softened into SystemExit: an Unsafe here means the safety layers
        # are not in the state a run requires, and that message should not be
        # mistaken for "the game isn't open".
        raise
    except SystemExit:
        raise
    except Exception as failed:
        raise SystemExit(
            f"Clash Royale's client could not be reached: {failed!r}. Start Google Play Games "
            f"and get the game to its main screen, then run this again. Note this cannot launch "
            f"the game itself - a Play Games title has no executable to start."
        )

    pink = battle.elixir_showing(session.controller)
    if pink >= BOARD_TRIPWIRE:
        raise SystemExit(
            f"REFUSING to start: the elixir bar reads {pink:.0%} pink, so a battle is already in "
            f"progress. This adapter only touches the meta-game. Let the match finish and get "
            f"back to the main screen first."
        )

    # Stillness, checked over a second, because a frame caught mid-transition is a
    # picture of a transition and would be matched against as though it were a
    # place. This also catches the loading screen, which changes constantly and is
    # the state the client is in most often when someone thinks it is ready.
    first = session.controller.grab(GRID_COLS, GRID_ROWS)
    time.sleep(1.0)
    moved = battle.fraction_changed(
        first, session.controller.grab(GRID_COLS, GRID_ROWS),
        GRID_COLS * GRID_ROWS, session.controller.target.cell_delta)
    if moved > IDLE_DRIFT:
        raise SystemExit(
            f"REFUSING to start: the window changed by {moved:.0%} over one second, which is "
            f"above the {IDLE_DRIFT:.0%} an idle screen drifts by, so it is mid-transition or "
            f"still loading. Wait for it to settle and run again. Nothing was tapped."
        )

    # Where the run is about to start from. `observe` is used rather than a bare
    # comparison so that the abort tripwire applies to the baseline too: a client
    # left on the shop screen must stop the run here, before onboarding sends its
    # one real tap, and not be quietly adopted as the screen everything is measured
    # against.
    home = reference.BY_ID[reference.MAIN_SCREEN]
    baseline = session.observe()
    if baseline.screen == reference.MAIN_SCREEN:
        note = (f"Started on {baseline.label}, agreement {baseline.agreement:.3f} against the "
                f"fingerprint measured in {reference.SOURCE['pass']}.")
    elif baseline.carried:
        raise SystemExit(
            f"REFUSING to start: the client is on {baseline.label} (agreement "
            f"{baseline.agreement:.3f}), not on {home.label}. A run takes its first screen as the "
            f"place it returns to after every discovery, so starting here would make "
            f"`return_to_main` look like a navigation to somewhere new and `open_cards` look like "
            f"a control that does nothing - two findings that would both be artefacts. Press back "
            f"or the home tab by hand until the main screen is up, then run again. Nothing was "
            f"tapped."
        )
    else:
        # Deliberately not a refusal. This is a labelling check, not a safety one -
        # the guard, the board tripwire and the abort screens are all still in force
        # - and a stale reference is the likeliest cause: the client updates itself,
        # and the fingerprints have a date on them. Refusing here would mean one
        # game update makes the adapter unrunnable until somebody regenerates the
        # reference, so it says so loudly and continues.
        note = (f"WARNING: the first frame matched NO carried screen (closest agreement "
                f"{baseline.agreement:.3f}, below the {SAME_SCREEN} cut), so it is registered as "
                f"{baseline.screen} and this run cannot confirm it started on {home.label}. Either "
                f"the client is somewhere the {reference.SOURCE['pass']} pass never went, or those "
                f"fingerprints have gone stale - both are worth reporting. Treat every "
                f"`same_screen` / `new_screen` reading below as relative to whatever this is.")
        print(f"\n{note}")

    adapter.onboarding_extra["preflight"] = report
    adapter.onboarding_extra["baseline"] = note
    _SESSIONS["live"] = session


# One live session per process, because there is one client and attaching twice
# would give two Controllers racing each other for the foreground - which is
# precisely what killed an earlier run of the bot. `check_ready` fills it and
# `execute_test` reads it, which also means a run cannot execute a test without
# having passed readiness first.
_SESSIONS: dict[str, Session] = {}


def live() -> Session:
    session = _SESSIONS.get("live")
    if session is None:
        raise Unsafe(
            "no live session: check_sut_ready must run before any test executes, because it is "
            "what proves the guard is loaded and the client is off-board."
        )
    return session
