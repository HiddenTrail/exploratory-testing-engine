"""A sweep: several short passes at one game, each starting where the last stopped.

    py sweep.py --game Mitosis

That is the whole interface. No window title, no executable path, no timings, no
screen list - the game is found by the name a person calls it, and everything else is
either discovered or measured. Pointing this at a game nobody has run it against
before is the thing it exists to make ordinary.

**Why passes instead of one long run.** A recon session degrades as it goes: it wanders
into a submenu with no way back, the window breaks, a dialog it cannot read swallows
every input. The one move that reliably returns an unknown game to a known state is a
cold launch, and a long session can only spend that as a recovery - it has already lost
the time. Short passes make the relaunch the *plan*. Each pass gets three minutes, dies
however it dies, and the next one starts from the title screen.

**What carries.** Everything, which is what makes the passes cumulative rather than
repetitive. The map carries, so pass 4 does not re-press the keys pass 1 answered or
re-buy the vetting calls it paid for; it rejoins the game already knowing the routes
and spends its three minutes past them. The calibration carries, and it is recut from
the passes' own transitions - so the numbers that used to be typed in by hand get
better the longer this runs, which is the claim the experiment is here to test.

**How long it takes, promised rather than estimated.** `--budget` is a wall-clock ceiling
on the whole sweep, counted from before the game is even resolved, and 15 minutes is the
default. It is not the same claim as `--passes` times `--minutes`: that product counts only
time inside the exploration loop, while a sweep also pays for a cold launch per pass, a
readiness wait, a report write and a shutdown - about a third again on top, measured. So
the budget governs and the passes give way to it. Each one is handed whatever is left minus
a reserve for its own launch and shutdown, a pass that cannot get 45 seconds of exploring
is not started at all, and the summary says which of the two limits ended the sweep.

Backing that is a kill switch: a daemon thread that force-exits a minute past the budget,
after closing the game. Trimming a pass only works on code that checks a clock, and the
failures worth insuring against are the ones that do not - a launch that never settles, a
model call that never returns.

**When it stops.** After two passes in a row that add nothing - no new screen, no new
transition. Not on "exhausted", which a session can report while merely stuck, and not
on a fixed count, which either wastes passes on a small game or truncates a large one.
Two is the smallest number that is not fooled by one unlucky pass that spent its budget
lost in a menu; the sweep says so in its summary either way, because "it stopped finding
things" and "it ran out of passes" are different results and only one of them means the
map is finished.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import calibrate
import recon
import target as targets
from controller import Controller, WindowLost, log, set_dpi_aware

PASSES = 5
MINUTES = 3.0
# Consecutive passes that add nothing before the sweep is called finished. One is too
# eager: a pass that opens a dialog it cannot read and spends three minutes there adds
# nothing and proves nothing.
DRY_PASSES = 2

# Wall clock for the whole sweep, and the number that is actually promised. `--minutes`
# times `--passes` is not that number: it counts only time inside the exploration loop,
# while a sweep also pays for a cold launch per pass, a readiness wait, a report write and
# a shutdown. Measured on this machine, five three-minute passes take about twenty
# minutes, so the sum of the parts understates the total by a third.
BUDGET = 15.0
# Held back from each pass for the parts either side of the exploration loop: the cold
# launch and readiness wait before it, and saving the ontology, writing the report and
# closing the game after. Without it the last pass explores down to zero and the shutdown
# runs past the budget, which is the one part of a pass that must not be cut off.
BUDGET_RESERVE = 0.75
# Below this much left, a pass is not started at all - and it is the reserve plus a useful
# minimum, so a pass that does start always gets at least 45 seconds of actual exploring
# rather than spending its whole life starting up.
BUDGET_FLOOR = 1.5
# Grace after the budget before the process is killed outright. The deadline is checked
# between passes and inside the exploration loop, so in the normal case it is never
# reached; what it exists for is the blocking call that ignores both - a launch that never
# settles, a model call that never returns - and for those, nothing short of exiting works.
KILL_GRACE = 60.0

# The controller currently owning a game window, for the kill switch to close on its way
# out. A force-exit skips every `finally`, so without this the last thing a killed sweep
# does is leave a fullscreen game running on someone's desktop.
_live: Controller | None = None


def arm_kill_switch(deadline: float, budget: float, live=None) -> None:
    """Kill the process if the budget plus its grace period runs out.

    A daemon thread rather than a signal or a timeout parameter, because what this
    protects against is precisely the call that is not watching a clock. Its job is to be
    the one thing in the sweep that cannot be blocked.

    `live` is a callable returning whichever controller currently owns a game window, or
    None. A callable rather than the controller itself because the thread outlives any
    particular one, and it is shared with `mission.py`: the failure being insured against
    - a game left fullscreen on someone's desktop by a process that skipped every
    `finally` - is not specific to sweeping."""
    live = live or (lambda: _live)

    def watch() -> None:
        while True:
            left = deadline + KILL_GRACE - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(left, 1.0))
        log(f"\nkill switch: {budget:.0f} minutes plus {KILL_GRACE:.0f}s of grace are "
            f"gone and something is still running; killing the run")
        owner = live()
        if owner is not None:
            try:
                owner.close()
            except OSError as error:
                log(f"  could not close the game: {error}")
        os._exit(2)

    threading.Thread(target=watch, daemon=True, name="kill-switch").start()


def run_pass(target, out: Path, previous: Path | None, minutes: float,
             vetter, allow_clicks: bool) -> dict:
    """One pass, from a cold launch to a written report. Never raises.

    A pass that dies must not take the sweep with it - the next one starts from a
    relaunch anyway, which is precisely the failure this shape is designed around. So
    everything is caught, the partial map is written, and what went wrong is recorded
    in the pass's own notes rather than on the way out."""
    global _live
    out.mkdir(parents=True, exist_ok=True)
    controller = Controller(target)
    _live = controller
    session = recon.Recon(controller, out, vetter=vetter, allow_clicks=allow_clicks)
    inherited = (0, 0)
    if previous is not None:
        data = json.loads((previous / "ontology.json").read_text(encoding="utf-8"))
        log(f"  {session.resume(data, previous)}")
        inherited = (len(session.screens), len(session.transitions))

    failure = ""
    try:
        controller.start()
        session.run(minutes)
    except (WindowLost, OSError) as error:
        failure = f"{type(error).__name__}: {error}"
        controller.note(f"pass ended early - {failure}")
    except KeyboardInterrupt:
        failure = "interrupted"
        raise
    finally:
        data = session.to_json()
        session.save()
        recon.write_report(data, out)
        try:
            controller.close()
        except OSError as error:                    # noqa: PERF203
            log(f"  could not close the game: {error}")
        _live = None

    return {
        "dir": out.name,
        "screens": len(session.screens),
        "transitions": len(session.transitions),
        "new_screens": len(session.screens) - inherited[0],
        "new_transitions": len(session.transitions) - inherited[1],
        "actions": session.actions_taken,
        "restarts": controller.restarts,
        "splits": session.splits,
        "notes": controller.notes,
        "failure": failure,
        # The loop's own account, which the table needs because a pass can end three ways
        # and only one of them is an exception: it can die, run out of time, or run out of
        # legal moves. Reporting the third as "time up" hides the finding that three
        # minutes was not the binding constraint.
        "stopped": data["session"].get("stopped") or "cut short",
        "ontology": data,
    }


def write_summary(out: Path, game: str, passes: list[dict], calibration: dict,
                  stopped: str, elapsed: float = 0.0, budget: float = 0.0) -> Path:
    """The sweep's own report: what each pass added, and what it cost.

    Deliberately about *growth* rather than totals. Every pass inherits the map, so its
    totals are mostly its predecessors' work, and a column of totals reads like five
    productive passes even when four of them found nothing."""
    lines = [f"# {game} - sweep of {len(passes)} passes\n",
             f"Stopped because {stopped}.\n",
             "| pass | new screens | new transitions | total screens | total transitions "
             "| actions | restarts | ended |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for index, result in enumerate(passes, 1):
        lines.append(
            f"| {index} | +{result['new_screens']} | +{result['new_transitions']} "
            f"| {result['screens']} | {result['transitions']} | {result['actions']} "
            f"| {result['restarts']} | {result['failure'] or result['stopped']} |")

    final = passes[-1]["ontology"]
    lines.append(f"\nThe map is `{passes[-1]['dir']}/ontology.json` - the last pass "
                 f"inherited every earlier one, so it is the whole sweep and not a "
                 f"fifth of it. `{passes[-1]['dir']}/report.md` is the readable view.\n")

    lines.append("## Calibration\n")
    lines.append("Both numbers were measured, not chosen. What they were measured from "
                 "is kept so they can be argued with:\n")
    startup = calibration.get("measured", {}).get("startup", {})
    if startup:
        lines.append(f"- `startup_quiet` = **{calibration['startup_quiet']}s**. The "
                     f"window changed {len(startup.get('change_at', []))} times over "
                     f"{startup.get('watched_seconds')}s of a cold launch"
                     + (f" (at {', '.join(f'{t}s' for t in startup['change_at'][:10])})"
                        if startup.get("change_at") else "")
                     + f"; the longest still moment *inside* startup was "
                     f"{startup.get('longest_interior_gap')}s, and the wait has to "
                     f"outlast that rather than the whole startup."
                     + ("" if startup.get("settled") else
                        f" {startup.get('why', '')}"))
    match = calibration.get("measured", {}).get("screen_match", {})
    if match:
        lines.append(f"- `screen_match` = **{calibration['screen_match']}**. "
                     + match.get("why", "").capitalize() + ".")
        if match.get("populations_overlap"):
            lines.append("  Those two populations overlap, which is a real finding "
                         "about this game: no single threshold separates 'the same "
                         "place, changed' from 'somewhere else' here, so its screens "
                         "are told apart by the model's naming. Watch "
                         "`screens_split_by_name` in the pass reports.")

    notes = [(index, note) for index, result in enumerate(passes, 1)
             for note in result["notes"]]
    if notes:
        lines.append("\n## What the passes ran into\n")
        lines.extend(f"- pass {index}: {note}" for index, note in notes)

    session = final["session"]
    lines.append("\n## Cost\n")
    if elapsed:
        # The two numbers are different claims and the difference is the point: what the
        # sweep promised, against what only the exploration loop got to spend.
        # Wall clock and the allotment, and nothing derived from the difference between
        # them: a pass that ran out of moves hands time back, and a pass pays for its own
        # launch and shutdown outside the loop, so the two effects run opposite ways and
        # any single number claiming to be "overhead" would be netting them against each
        # other.
        allotted = sum(p.get("minutes", 0) for p in passes)
        lines.append(f"**{elapsed / 60:.1f} minutes** of wall clock against a "
                     f"{budget:.0f}-minute budget. {len(passes)} passes were allotted "
                     f"{allotted:.1f} minutes of exploration between them, each also "
                     f"paying for a cold launch, a readiness wait, a report and a "
                     f"shutdown - and handing back whatever it did not spend.\n")
    lines.append(f"{sum(p['actions'] for p in passes)} actions across "
                 f"{len(passes)} passes; {sum(p['restarts'] for p in passes)} relaunches "
                 f"the harness had to make on its own; "
                 f"{sum(len(s['variants']) for s in final['screens'])} appearances "
                 f"recorded. Model vetting was "
                 f"{'on' if session['vetted_by_model'] else 'off'}.\n")

    path = out / "sweep.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", required=True,
                        help="the game's name, as a person would write it")
    parser.add_argument("--passes", type=int, default=PASSES)
    parser.add_argument("--minutes", type=float, default=MINUTES,
                        help="exploration time per pass; a pass is cut shorter if that is "
                             "all the budget has left")
    parser.add_argument("--budget", type=float, default=BUDGET,
                        help="hard wall-clock ceiling on the whole sweep, in minutes, "
                             "counted from before the startup measurement")
    parser.add_argument("--remeasure", action="store_true",
                        help="measure startup again even if this game has been measured")
    parser.add_argument("--no-model", action="store_true",
                        help="no vetting call, so committing actions stay locked")
    parser.add_argument("--no-clicks", action="store_true")
    args = parser.parse_args()

    # Started before anything else that costs time, including the startup measurement and
    # resolving the game. A ceiling that only covers the passes is not a ceiling.
    started = time.monotonic()
    deadline = started + args.budget * 60
    arm_kill_switch(deadline, args.budget)

    calibration = calibrate.load(args.game)
    target = targets.resolve(args.game, calibration)
    calibration.setdefault("game", target.name)
    calibration.setdefault("measured", {})

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(__file__).parent / "out" / f"{target.name}-sweep-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    vetter = None
    if not args.no_model:
        import describe
        vetter = describe.make_vetter()

    set_dpi_aware()

    if args.remeasure or "startup" not in calibration["measured"]:
        # Measured on its own launch, before any pass, because the wait a pass performs
        # is the thing being measured and cannot be used to measure itself. Costs one
        # launch and about fifteen seconds, once per game.
        log("\nmeasuring a cold launch")
        scout = Controller(target)
        scout.attach_or_launch()
        measured = calibrate.measure_startup(scout, target.screen_match)
        scout.close()
        target.startup_quiet = measured["startup_quiet"]
        calibration["measured"]["startup"] = measured
        calibration["startup_quiet"] = measured["startup_quiet"]
        calibration["window_title"] = target.window_title
        log(f"  wrote {calibrate.save(args.game, calibration)}")

    results: list[dict] = []
    previous: Path | None = None
    dry = 0
    stopped = f"it ran out of passes ({args.passes})"

    for index in range(1, args.passes + 1):
        left = (deadline - time.monotonic()) / 60
        if left < BUDGET_FLOOR:
            stopped = (f"the {args.budget:.0f}-minute budget ran out after "
                       f"{index - 1} of {args.passes} passes - what is left would be "
                       f"spent starting the game up rather than exploring it")
            log(f"\nbudget spent with {left * 60:.0f}s left; not starting pass {index}")
            break
        minutes = min(args.minutes, left - BUDGET_RESERVE)
        log(f"\n=== pass {index}/{args.passes}, {minutes:.1f} minutes "
            + (f"(trimmed from {args.minutes:.0f} - {left:.1f} left of the "
               f"{args.budget:.0f}-minute budget) " if minutes < args.minutes else "")
            + f"({'extending ' + previous.name if previous else 'from nothing'}) ===")
        result = run_pass(target, out / f"pass{index}", previous, minutes,
                          vetter, not args.no_clicks)
        result["minutes"] = minutes
        results.append(result)
        log(f"  pass {index}: +{result['new_screens']} screens, "
            f"+{result['new_transitions']} transitions "
            f"({result['screens']} and {result['transitions']} in total)")

        # Recut from everything recorded so far, not only from this pass - a resumed
        # ontology carries every earlier transition, so each recut is made on more
        # evidence than the last. The masks of screens already on the map were built
        # under the old threshold and are not revisited; the new number governs what the
        # next pass files, which is where being wrong is still expensive.
        recut = calibrate.recut_screen_match(result["ontology"])
        # Adopted whether the recut moved the number or kept it, because "kept" means
        # kept at *the value the pass ended on* - and a pass can loosen its own threshold
        # mid-run from a hover sweep (`Recon.relax_match`). Re-reading only on a
        # successful recut would throw that away on exactly the passes that recorded no
        # screen change to recut from, which are the ones with the least evidence and so
        # the ones that most need to keep what they measured.
        if recut["screen_match"] != target.screen_match:
            log(f"  screen_match {target.screen_match} -> {recut['screen_match']}: "
                f"{recut['why'] if not recut.get('kept') else 'carried from the pass itself'}")
            target.screen_match = recut["screen_match"]
        calibration["screen_match"] = target.screen_match
        calibration["measured"]["screen_match"] = recut
        calibration["window_title"] = target.window_title or calibration.get("window_title", "")
        calibrate.save(args.game, calibration)

        previous = out / f"pass{index}"
        dry = dry + 1 if not (result["new_screens"] or result["new_transitions"]) else 0
        if dry >= DRY_PASSES:
            stopped = (f"{DRY_PASSES} passes in a row added nothing - no new screen and "
                       f"no new transition, which is what a finished map looks like")
            log(f"\n{dry} passes in a row found nothing new; stopping")
            break

    log(f"\nwrote {write_summary(out, target.name, results, calibration, stopped, time.monotonic() - started, args.budget)}")
    final = results[-1]
    log(f"{final['screens']} screens, {final['transitions']} transitions, "
        f"{sum(r['actions'] for r in results)} actions over {len(results)} passes")


if __name__ == "__main__":
    main()
