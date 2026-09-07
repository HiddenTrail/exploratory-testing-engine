"""Everything that has to be true before a pass starts, checked once and reported in prose.

Why a preflight rather than letting the run find out
---------------------------------------------------
This kit exists because a person kept having to sit with the run and fix things. Going back
over what those interventions actually were, almost none of them were bugs in the code. They
were environmental, they were the same handful every time, and each one had a fix a person
could apply in ten seconds *if they knew what had happened* - which they did not, because the
symptom never named the cause.

So each check below is one of those, turned into a sentence that says what is wrong and what to
do about it:

- **the window is not the game.** A Chrome tab titled `Clash Royale - Google Play` and a VS
  Code window showing `clash-royale-wiki.html` both carry the name, and one was adopted and
  sent drags. `attach` already refuses; what this adds is saying so in a way that mentions the
  editor, because the operator's instinct is to think the game is closed.
- **DPI was not claimed, so every coordinate is wrong.** A 787x1400 client read as 393x700
  makes fractional coordinates land at half the intended offset, and nothing errors. Checked
  by measuring the client and refusing an implausible one.
- **the thresholds are stale.** Every frame-comparison constant here was calibrated against a
  lobby that no longer exists; idle animation went from 1 cell of 576 to 132 of 2304, past the
  readiness gate's tolerance, so a live and perfectly readable client died reporting `window
  never rendered a settled frame`. Re-derived per session from this session's own drift.
- **the client is not on the lobby.** Not a safety problem - a labelling one, and the findings
  it produces are pure artefacts. Refused, with the instruction to press home by hand.
- **the client has frozen.** Every Win32 health check reports a healthy window while the guest
  has stopped rendering. Reported as evidence, never as a verdict, for the reason `checks.py`
  gives at length.

What it deliberately does not do
--------------------------------
It never touches the game. No tap, no key, no focus grab, and every frame is taken with
`verify=False` - because a *verified* grab of a hidden window sends `ensure_readable` looking
for a fix, and the fix is `_restart`, which closes the client before discovering it has no
executable to reopen it with. A liveness check closed the client it was checking, and that is
the single most expensive thing this project has learned. Play Games parks its window hidden,
so this is the ordinary case here, not an edge one.

It also never relaunches, and cannot: `Target.exe` is empty on purpose. Opening the client is a
person's job, and this file's contribution to that is saying so clearly.

Windows-only, and unapologetically so. `controller` calls `ctypes.WinDLL` at import time. The
decisions this feeds are all in `checks.py`, which imports nothing of the kind and is where the
tests are.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "game-ontology"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "android-bot"))

import checks  # noqa: E402
from engine.adapters.clash_royale import reference  # noqa: E402

GAME = "Clash Royale"

# One-second samples of an untouched window. Six rather than two, because the lobby's
# animation cycle is longer than a second: a healthy lobby measured 5, 0, 0, 0, 0, 5, so two
# samples read zero movement about two times in three and would cut a threshold that no frame
# of that lobby survives. Six seconds is also the cheapest part of a five-minute pass.
DRIFT_SAMPLES = 6

# The smallest client this will drive. Below it the likeliest cause is not a small window but
# DPI virtualisation - the process never claimed per-monitor awareness, so Windows reports a
# scaled-down rect and every fractional coordinate resolves against geometry the game is not
# using. It does not error; taps just land somewhere else.
MIN_CLIENT = (200, 350)


@dataclass
class Preflight:
    """The state of the machine, and whether a pass may start on it.

    Assembled as one object rather than printed as it goes so that the same findings can be
    read by a person, written to disk beside the run, and quoted into the wiki's overview page
    as the provenance of every screen name in it. A threshold with its argument left behind in
    a terminal scrollback is a threshold nobody can check later.
    """
    game: str
    window_title: str = ""
    client: tuple[int, int] = (0, 0)
    hwnd: int = 0
    calibration: dict = field(default_factory=dict)
    denylist_boxes: int = 0
    drift: checks.DriftReading | None = None
    threshold: checks.Threshold | None = None
    baseline: checks.Baseline | None = None
    baseline_screen: str = ""
    baseline_agreement: float = 0.0
    guards: str = ""
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        self.lines.append(line)

    @property
    def ok(self) -> bool:
        return self.baseline is not None and self.baseline.verdict != "refuse"

    def to_json(self) -> dict:
        return {
            "game": self.game, "window_title": self.window_title,
            "client": list(self.client), "hwnd": self.hwnd,
            "calibration": self.calibration, "denylist_boxes": self.denylist_boxes,
            "drift": {"samples": list(self.drift.samples), "ncells": self.drift.ncells,
                      "worst": self.drift.worst,
                      "agreement": round(self.drift.agreement, 3)} if self.drift else None,
            "threshold": {"value": self.threshold.value, "measured": self.threshold.measured,
                          "calibrated": self.threshold.calibrated,
                          "clamped": self.threshold.clamped,
                          "why": self.threshold.why} if self.threshold else None,
            "baseline": {"verdict": self.baseline.verdict, "message": self.baseline.message,
                         "screen": self.baseline_screen,
                         "agreement": round(self.baseline_agreement, 3)}
            if self.baseline else None,
            "reference_pass": reference.SOURCE["pass"],
            "lines": self.lines,
        }

    def wiki_note(self) -> str:
        """The provenance paragraph the overview and identity pages carry.

        Written here rather than in `wikibuild.py` because this is where the numbers were
        measured and where the reason for them is known. The wiki's job is to not lose it.
        """
        if self.threshold is None:
            return ("The screen-match threshold for this pass was not derived from a live "
                    "measurement, so every screen identity below rests on whatever default "
                    "the run happened to carry.")
        parts = [f"**Where that threshold came from.** It was not a default: {self.threshold.why}."]
        if self.drift is not None:
            parts.append(f"The measurement behind it was {self.drift.line()}.")
        if self.baseline is not None and self.baseline.verdict == "warn":
            parts.append(f"**Read with caution:** {self.baseline.message}")
        parts.append(f"The carried fingerprints it is scored against were measured in "
                     f"`{reference.SOURCE['pass']}`, against a client that updates itself - so "
                     f"a name that reads confidently here may be describing a screen that has "
                     f"since changed.")
        return " ".join(parts)


def _controller(game: str, verbose: bool):
    """Attach, or refuse with the sentence the operator actually needs.

    `attach`'s own error is accurate and says to open the client. It is extended here with the
    two adopted-window cases, because "no Play Games window is open" reads as "the game is
    closed" and the operator then opens a second copy - while the real cause was a stranger
    window carrying the name, which `attach` printed above and which scrolls past.
    """
    from attach import attach                                             # noqa: E402
    from controller import WindowLost                                     # noqa: E402
    try:
        return attach(game, verbose=verbose)
    except WindowLost as lost:
        raise checks.Refuse(
            f"{lost}\n"
            f"  Two things to check, in this order. Is the Play Games client open with "
            f"{game!r} actually running - not the launcher's library page, the game? And did "
            f"any window above get named as ignored? A Chrome tab or an editor showing a file "
            f"about this game carries its name too, and one was adopted and sent drags before "
            f"this check existed. Nothing was tapped.") from lost


def _measure_drift(controller, samples: int, verbose: bool) -> checks.DriftReading:
    """One-second cell deltas over an untouched window.

    `verify=False` on every grab, and this is not an optimisation. A verified grab of a
    non-foreground window sends `ensure_readable` looking for a fix; the fix is `_restart`;
    `_restart` closes the client before finding out it has no executable to reopen it with.
    Play Games parks its window hidden, so a verified grab here is the *ordinary* path to
    killing the thing being measured, not an unlikely one.
    """
    from controller import changed_cells                                  # noqa: E402
    from recon import fingerprint                                         # noqa: E402

    delta = controller.target.cell_delta
    previous = fingerprint(controller, verify=False)
    readings = []
    for index in range(samples):
        time.sleep(1.0)
        current = fingerprint(controller, verify=False)
        readings.append(changed_cells(previous, current, delta))
        previous = current
        if verbose:
            print(f"  drift sample {index + 1}/{samples}: {readings[-1]} cells", flush=True)
    return checks.DriftReading(samples=tuple(readings), ncells=checks.NCELLS)


def _baseline(controller) -> tuple[str, float, bool]:
    """Which screen the client is on, using the adapter's own identification.

    Reused rather than reimplemented, for the reason `session.py` gives: the carried
    fingerprints were measured by `recon.fingerprint` and matched by `recon.agreement`, and a
    second copy of that arithmetic is a second stride to get wrong - which does not error, it
    disagrees with everything, and reads as "every screen is new".

    `observe()` also carries the two tripwires, which is why it is worth going through it
    rather than straight to `_identify`. A client sitting on a live battle board or on a screen
    the reference classifies `abort` raises `Unsafe`, and both are things a pass must not start
    on top of.
    """
    from engine.adapters.clash_royale.actions import Unsafe               # noqa: E402
    from engine.adapters.clash_royale.session import Session              # noqa: E402
    try:
        where = Session(controller=controller).observe()
    except Unsafe as unsafe:
        raise checks.Refuse(
            f"{unsafe}\n"
            f"  Nothing was tapped. Put the client back on the main screen by hand and run "
            f"again.") from unsafe
    return where.screen, where.agreement, where.carried


def run(game: str = GAME, samples: int = DRIFT_SAMPLES, verbose: bool = True) -> Preflight:
    """Check the machine and return what was found. Raises `checks.Refuse` if a pass must not start.

    Ordered by how expensive each failure is to discover later. The window first, because
    everything else measures the wrong thing without it. Geometry next, because a DPI-scaled
    rect makes every subsequent number a measurement of the wrong region. Then the guards,
    before any frame is scored, so that a run cannot get as far as looking plausible with an
    empty denylist. Drift and the threshold after that. The baseline screen last, because it is
    the only check whose answer a person can change in two seconds.
    """
    report = Preflight(game=game)

    controller = _controller(game, verbose)
    report.hwnd = controller.hwnd or 0
    report.window_title = controller.target.window_title
    report.denylist_boxes = len(controller.target.denylist)
    report.say(f"window: {report.window_title!r} (hwnd {report.hwnd})")

    _, _, width, height = controller.rect
    report.client = (width, height)
    if width < MIN_CLIENT[0] or height < MIN_CLIENT[1]:
        raise checks.Refuse(
            f"the client area measures {width}x{height}, which is smaller than the "
            f"{MIN_CLIENT[0]}x{MIN_CLIENT[1]} this will drive. The likeliest cause is not a "
            f"small window: it is that this process never claimed per-monitor DPI awareness, "
            f"so Windows is reporting a scaled-down rect and every fractional coordinate would "
            f"resolve against geometry the game is not using - taps would land somewhere else "
            f"and nothing would error. Check `set_dpi_aware()` ran before the window was "
            f"measured, and that the window is not minimised. Nothing was tapped.")
    report.say(f"client: {width}x{height}")

    # Before any frame is scored. An empty denylist is the failure that looks exactly like
    # success - every check downstream of it reports "allowed" - so it has to be impossible to
    # get past this point with one.
    from engine.adapters.clash_royale.actions import preflight as guard_check   # noqa: E402
    from engine.adapters.clash_royale.actions import Unsafe                     # noqa: E402
    try:
        report.guards = f"{guard_check(controller.target)}\n\n{reference.check_reference()}"
    except Unsafe as unsafe:
        raise checks.Refuse(f"{unsafe}\n  Nothing was tapped.") from unsafe
    report.say(f"guards: {report.denylist_boxes} coordinate box(es) loaded and verified; "
               f"reference from {reference.SOURCE['pass']} checked")

    from attach import apply_calibration                                  # noqa: E402
    report.calibration = apply_calibration(controller, game)
    report.say("calibration: "
               + (", ".join(f"{k} {v}" for k, v in sorted(report.calibration.items()))
                  if report.calibration else
                  f"none on disk for {game!r}, so the Target defaults are in use "
                  f"(screen_match {controller.target.screen_match}, "
                  f"cell_delta {controller.target.cell_delta})"))

    if verbose:
        print(f"watching an untouched window for {samples}s", flush=True)
    report.drift = _measure_drift(controller, samples, verbose)
    report.say(report.drift.line())

    report.threshold = checks.screen_match_for(report.drift, controller.target.screen_match)
    report.say(f"screen_match for this pass: {report.threshold.value} - {report.threshold.why}")

    screen, agreement, carried = _baseline(controller)
    report.baseline_screen, report.baseline_agreement = screen, agreement
    label = reference.BY_ID[screen].label if screen in reference.BY_ID else screen
    report.baseline = checks.baseline_verdict(screen, agreement, label, carried)
    if report.baseline.verdict == "refuse":
        raise checks.Refuse(report.baseline.message)
    report.say(("WARNING: " if report.baseline.verdict == "warn" else "")
               + report.baseline.message)

    return report


def main() -> int:
    """`python preflight.py` - the doctor, on its own. Touches nothing."""
    from controller import readable_output, set_dpi_aware                 # noqa: E402
    readable_output()
    set_dpi_aware()
    try:
        report = run()
    except checks.Refuse as refused:
        print(f"\nWILL NOT RUN: {refused}")
        return 1
    print("\n".join(f"  {line}" for line in report.lines))
    print("\nready" if report.baseline.verdict == "ok" else
          "\nready, with the warning above carried into the run's own output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
