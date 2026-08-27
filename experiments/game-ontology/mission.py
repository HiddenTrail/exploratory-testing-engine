"""Missions: the map stops being only an output and becomes an input.

    py mission.py --game Mitosis

`sweep.py` explores by a fixed policy - arrow keys first, then this appearance's
committing keys, then points the cursor was seen to react to, and when a screen runs dry,
breadth-first to the nearest screen that still has something untried. That policy is
deliberately blind: it has to work on a game nobody has looked at. Its cost is that it
cannot use what it just learned. A map that says "sc03 is the campaign screen and it has
a Level 1 button at (0.31, 0.44)" is read by the explorer as four arrow keys and a
hotspot list, because that is all the explorer can read.

A mission closes that loop. The model reads the map, the missions already flown, and a
screenshot of where the harness is standing, and writes ONE mission: a goal and a short
list of steps. This program executes them literally and reports what actually happened,
step by step. Then it asks for the next one, which is now briefed by everything the last
one proved or disproved.

**The plan is a hypothesis; the executor is the referee.** That split is the whole
design, and it is why a mission must contain at least one `expect` step (enforced in
`describe.validate`, not requested in the prompt). "Click Campaign, then we should be on
a screen not yet on the map" is a claim that can be wrong, and when it is wrong the
report says so at the step where it broke, with the screen the harness was actually
looking at. A plan without an expectation cannot fail, so it also cannot teach anything -
it just moves the game around.

**Nothing here is trusted more than in recon.** Every step goes through
`Recon.take`, so the same identity matching, the same transition recording and the same
late credit for a launcher handover apply. Every committing action goes through
`Recon.permitted`, so the coordinate denylist and the modality gate are unchanged. What
is new is only where candidate actions come from: a plan may name a control the cursor
never reacted to, and that action arrives with no verdict, so `Recon.ask_about` buys one
for it. The model proposing a coordinate does not make the coordinate allowed - it makes
it a question, asked with the same brief and answerable with "no".

**Which is what unlocks games the explorer cannot touch at all.** Two of the three games
this has been pointed at have screens that ignore the cursor entirely: hover mapping
finds nothing, so the explorer has no click candidates and only arrow keys to spend. The
map still holds labelled coordinates for those screens, because the vetting call reports
what it can see whether or not anything reacted. A mission can click them.

**What carries between missions.** The map, and the game itself: missions run inside one
launch, so a mission can start where the last one ended. Resetting is a step (`restart`)
rather than a rule, because after the first mission the model is the thing that knows
whether the current state is worth building on - and a cold launch is expensive enough
(measured per game, 0.5-4s of settling on top of the launch) that spending it four times
because the harness insists is a real cost. The budget, the reserve and the kill switch
are `sweep.py`'s, shared rather than reimplemented.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import calibrate
import recon
import sweep
import target as targets
from controller import Controller, WindowLost, is_fraction, log, set_dpi_aware
from probe import VK_NAMES
from recon import UNVETTED, Action

MISSIONS = 4
# Screens a single `go` may travel through. A route longer than this is not a route, it
# is a plan of its own, and executing it silently means a mission whose first step is
# fifteen actions long and whose report cannot say which one went wrong.
ROUTE_HOPS = 6
# Verdicts a single mission may buy for controls nobody has ruled on. Each is a model
# call inside the mission, and this is what stops a twelve-step plan of clicks costing
# twelve of them.
VERDICT_BUDGET = 6


def known_names(data: dict) -> dict:
    """What a plan is allowed to refer to: screens, labelled controls, keys.

    Handed to the validator rather than described in the prompt, because a name the
    executor cannot resolve has to be rejected at the call and not discovered at step
    four with the game halfway through a menu."""
    labels = {(element.get("label") or "").strip().lower()
              for screen in data["screens"]
              for element in screen.get("elements", [])
              if element.get("label")}
    return {"screens": {s["id"] for s in data["screens"]},
            "labels": labels - {""},
            "keys": set(VK_NAMES)}


def digest(data: dict, standing: str, flown: list[dict]) -> str:
    """The map as something to plan against, rather than as a record.

    Deliberately not the ontology JSON. That file is 100KB of fingerprints and volatile
    masks whose whole purpose is to be machine-comparable, and none of it answers "what
    is there and what have we not tried". This says, per screen: what it is, what is on
    it and where, what has been sent from it and what happened, and what was refused and
    why - because a refusal is the most useful thing in the file for a planner. It is
    the reason not to try that door again."""
    names = {s["id"]: (s.get("name") or s["id"]) for s in data["screens"]}
    lines = [f"# The map so far: {len(data['screens'])} screens, "
             f"{len(data['transitions'])} transitions observed.\n"]

    for screen in data["screens"]:
        here = " <- THE HARNESS IS STANDING HERE" if screen["id"] == standing else ""
        lines.append(f"## {screen['id']}: {names[screen['id']]}{here}")
        if screen.get("purpose"):
            lines.append(screen["purpose"])
        elements = [e for e in screen.get("elements", [])]
        if elements:
            lines.append("\nControls seen on it (a label with coordinates can be "
                         "clicked; one without cannot be targeted):")
            for element in elements:
                at = element.get("at")
                # An unaimable coordinate is reported as absent rather than printed.
                # Printing it would offer the planner a control it cannot click - the step
                # would be refused - and `at: [697, 190]` reads as a perfectly good target
                # right up to the point where something tries to aim at it.
                where = f"at ({at[0]:.3f}, {at[1]:.3f})" if is_fraction(at) \
                    else "no usable coordinates recorded"
                lines.append(f"- {element['label']!r} {where}: {element.get('what', '')}")
        hover = screen.get("hover", {})
        if hover.get("inert"):
            lines.append(f"\nThis screen ignores the cursor: {hover.get('probed')} points "
                         f"were hovered and nothing reacted, so the explorer had no click "
                         f"candidates here at all. Naming a control by label is the only "
                         f"way anything gets clicked on it.")
        outgoing = [t for t in data["transitions"] if t["from"] == screen["id"]]
        if outgoing:
            lines.append("\nWhat has been sent from here:")
            for t in outgoing:
                if t["effect"] == "screen":
                    result = f"-> {t['to']} ({names.get(t['to'], '?')})"
                elif t["effect"] == "variant":
                    result = "the same screen, different appearance"
                else:
                    result = "nothing visible changed"
                lines.append(f"- {t['action']['id']}: {result} "
                             f"({t['changed_cells']} of 576 cells, {t['settle_ms']}ms)")
        else:
            lines.append("\nNothing has ever been successfully sent from this screen.")
        # Scoped by prefix because a refusal is recorded against whichever of the two
        # scopes the action names: a click against the screen, a committing key against
        # the appearance it was judged on, whose id starts with the screen's own.
        # Grouped by action rather than listed per appearance. Measured on a real map: 24
        # refusals on one screen, of which 3 were distinct - the same three keys refused
        # on eight appearances for the same reason each time. Listed raw they are most of
        # the digest, which teaches the planner that this screen is a wall of prose
        # rather than that Esc is refused on it.
        refused: dict[str, tuple[str, int]] = {}
        for entry in data.get("blocked_actions", []):
            scope, _, action = entry["what"].partition(" ")
            if not scope.startswith(screen["id"]) or entry["why"] == UNVETTED:
                continue
            why, count = refused.get(action, (entry["why"], 0))
            refused[action] = (why, count + 1)
        if refused:
            lines.append("\nRefused here on safety grounds, and not worth re-planning:")
            lines.extend(f"- {action}: {why}"
                         + (f" (refused on {count} appearances of this screen)"
                            if count > 1 else "")
                         for action, (why, count) in refused.items())
        selections = [f"{v['id']} (selected {v['selected']!r})"
                      for v in screen.get("variants", []) if v.get("selected")]
        if selections:
            lines.append("\nAppearances of it that differ by what is selected: "
                         + ", ".join(selections))
        lines.append("")

    if flown:
        lines.append("# Missions already flown\n")
        for mission in flown:
            lines.append(f"## Mission {mission['index']}: {mission['goal']}")
            lines.append(f"Verdict: {mission['verdict']}")
            for step in mission["steps"]:
                lines.append(f"- step {step['n']} {step['said']}: {step['happened']}")
            lines.append("")
    return "\n".join(lines)


class Mission:
    """One plan, executed step by step, with what each step actually did.

    A step's outcome is recorded whether it worked or not, and the mission stops at the
    first failure. Stopping is not a bug to be worked around: after a step that did
    something other than what the plan said, every later step is aimed at a screen the
    harness is not on, and running them anyway is how an explorer ends up clicking at
    coordinates on a dialog it cannot read."""

    def __init__(self, session: recon.Recon, index: int, plan: dict):
        self.session = session
        self.controller = session.controller
        self.index = index
        self.plan = plan
        self.steps: list[dict] = []
        self.verdict = ""
        self.verdicts_bought = 0
        # Snapshotted here, because "expect somewhere new" is a claim about the map this
        # mission was planned against. By the time an `expect` step runs, the screen the
        # step before it discovered has already been filed - so a test that asked whether
        # the current screen is on the map would answer yes, every time, and the one
        # expectation worth making would be the one that can never hold.
        self.known_at_start = set(session.screens)

    # -- targeting ----------------------------------------------------------

    def _element(self, label: str, screen) -> tuple[tuple[float, float] | None, str]:
        """Fractional coordinates for a control named by label, on the screen we are on.

        Refusing to reach across screens is the point of the second half: the same label
        can appear on two screens, and a plan that clicks a Back button belonging to
        somewhere else is clicking a position that happens to be free on this one."""
        wanted = label.strip().lower()
        for element in (screen.vetting or {}).get("elements", []):
            if (element.get("label") or "").strip().lower() == wanted:
                at = element.get("at")
                if is_fraction(at):
                    return (float(at[0]), float(at[1])), ""
                if at:
                    # A coordinate that is not a fraction, which is what a map written
                    # before `describe.py` checked for it can contain: one real one holds
                    # `at: [697, 190]`, pixels of the screenshot the annotator was shown.
                    # Refused here rather than left to `Controller.point`, so it costs the
                    # step that aimed at it instead of the mission it was in, and so the
                    # report says which control the map is wrong about.
                    return None, (f"the map puts {label!r} at {at}, which is not a "
                                  f"fraction of the window, so there is nothing to aim at")
                return None, (f"the map records {label!r} on {screen.id} but never located "
                              f"it, so there is no coordinate to click")
        for other in self.session.screens.values():
            for element in (other.vetting or {}).get("elements", []):
                if (element.get("label") or "").strip().lower() == wanted:
                    return None, (f"{label!r} belongs to {other.id}, and the harness is on "
                                  f"{screen.id}")
        return None, f"no control called {label!r} is recorded anywhere on the map"

    def _target(self, step: dict, screen) -> tuple[tuple[float, float] | None, str]:
        if step.get("element"):
            return self._element(step["element"], screen)
        at = step.get("at")
        if at and len(at) == 2:
            return (float(at[0]), float(at[1])), ""
        return None, "no target given"

    def _route(self, here: str, there: str) -> tuple[list[Action], str]:
        """Actions that have been observed to lead from one screen to another.

        Breadth-first over recorded screen changes only - the same edges
        `route_to_frontier` walks, for the same reason: an edge that was observed once is
        the only kind of route this harness can honestly claim to know."""
        if here == there:
            return [], ""
        outgoing: dict[str, list[tuple[Action, str]]] = {}
        for transition in self.session.transitions.values():
            if transition.kind == "screen":
                outgoing.setdefault(transition.source, []).append(
                    (transition.action, transition.dest))
        queue, seen = [(here, [])], {here}
        while queue:
            node, path = queue.pop(0)
            if len(path) >= ROUTE_HOPS:
                continue
            for action, dest in outgoing.get(node, []):
                if dest in seen:
                    continue
                if dest == there:
                    return path + [action], ""
                seen.add(dest)
                queue.append((dest, path + [action]))
        return [], (f"no route from {here} to {there} has ever been observed"
                    + (f" within {ROUTE_HOPS} hops" if seen - {here} else ""))

    # -- acting -------------------------------------------------------------

    def _act(self, action: Action) -> dict:
        """One action, vetted and recorded. The only path from a plan to an input."""
        screen, variant, before_fp = self.session.look()
        ok, why = self.session.permitted(screen, variant, action)
        if not ok and why in (UNVETTED, "no verdict for this action") \
                and self.verdicts_bought < VERDICT_BUDGET:
            # The action the plan named was never a candidate the explorer measured, so
            # nobody has ruled on it. Buying a verdict is what makes a planned click
            # possible at all; it is emphatically not what makes it allowed.
            self.verdicts_bought += 1
            if self.session.ask_about(screen, variant, [action]):
                ok, why = self.session.permitted(screen, variant, action)
        if not ok:
            return {"ok": False, "from": screen.id, "to": screen.id,
                    "happened": f"refused before it was sent - {why}"}
        transition, found, settle = self.session.take(screen, variant, before_fp, action)
        effect = {"screen": f"moved to {transition.dest}", "variant": "same screen, "
                  "different appearance", "none": "nothing visible changed"}[transition.kind]
        return {"ok": True, "from": transition.source, "to": transition.dest,
                "transition": transition.id, "effect": transition.kind, "new": found,
                "happened": f"{effect} ({transition.changed} of 576 cells, {settle}ms)"}

    def _expect(self, step: dict) -> dict:
        """A step that sends nothing and decides whether the plan was right so far."""
        screen, variant, _ = self.session.look()
        if step.get("screen"):
            ok = screen.id == step["screen"]
            return {"ok": ok, "from": screen.id, "to": screen.id,
                    "happened": (f"on {screen.id} as expected" if ok else
                                 f"expected {step['screen']}, actually on {screen.id} "
                                 f"({(screen.vetting or {}).get('name') or 'unnamed'})")}
        if step.get("that") == "new":
            ok = screen.id not in self.known_at_start
            return {"ok": ok, "from": screen.id, "to": screen.id,
                    "happened": (f"{screen.id} is somewhere the map had not been before "
                                 f"this mission" if ok else f"{screen.id} "
                                 f"({(screen.vetting or {}).get('name') or 'unnamed'}) was "
                                 f"already on the map, seen {screen.observations} times")}
        changed = self.steps and self.steps[-1].get("effect") in ("screen", "variant")
        return {"ok": bool(changed), "from": screen.id, "to": screen.id,
                "happened": ("the previous step did change the picture" if changed else
                             "the previous step changed nothing visible")}

    def _one(self, number: int, step: dict) -> dict:
        verb = step.get("do")
        said = describe_step(step)
        screen, _, _ = self.session.look()

        if verb == "expect":
            outcome = self._expect(step)
        elif verb == "wait":
            seconds = float(step.get("seconds", 1))
            time.sleep(seconds)
            after, _, _ = self.session.look()
            # No transition is recorded: nothing was sent, so there is no action to
            # credit the change to, and inventing an edge here would put a route in the
            # map that no input can traverse.
            outcome = {"ok": True, "from": screen.id, "to": after.id,
                       "happened": (f"after {seconds:.0f}s the game is on {after.id}"
                                    + (" (it moved on its own, so no edge was recorded - "
                                       "nothing was pressed)" if after.id != screen.id
                                       else ", unchanged"))}
        elif verb == "restart":
            self.controller.close()
            self.controller.start()
            after, _, _ = self.session.look()
            outcome = {"ok": True, "from": screen.id, "to": after.id,
                       "happened": f"relaunched cold and landed on {after.id}"}
        elif verb == "go":
            route, why = self._route(screen.id, step.get("screen", ""))
            if why:
                outcome = {"ok": False, "from": screen.id, "to": screen.id,
                           "happened": why}
            else:
                outcome = {"ok": True, "from": screen.id, "to": screen.id,
                           "happened": "already there"}
                for hop, action in enumerate(route, 1):
                    outcome = self._act(action)
                    outcome["happened"] = f"hop {hop}/{len(route)} {action.describe()}: " \
                                          f"{outcome['happened']}"
                    if not outcome["ok"]:
                        break
                if outcome["ok"] and outcome["to"] != step["screen"]:
                    outcome["ok"] = False
                    outcome["happened"] += (f" - the route ended on {outcome['to']}, not "
                                            f"{step['screen']}, so the map's edges no "
                                            f"longer lead where they did")
        elif verb == "press":
            times = int(step.get("times", 1) or 1)
            outcome = {"ok": False, "from": screen.id, "to": screen.id,
                       "happened": "no press was made"}
            for press in range(1, times + 1):
                outcome = self._act(Action("key", key=step["key"].lower()))
                if times > 1:
                    outcome["happened"] = f"press {press}/{times}: {outcome['happened']}"
                if not outcome["ok"]:
                    break
        elif verb in ("click", "hover"):
            at, why = self._target(step, screen)
            if at is None:
                outcome = {"ok": False, "from": screen.id, "to": screen.id,
                           "happened": f"could not be aimed - {why}"}
            else:
                outcome = self._act(Action(verb, at=at))
        else:
            outcome = {"ok": False, "from": screen.id, "to": screen.id,
                       "happened": f"{verb!r} is not something this harness can do"}

        outcome.update({"n": number, "do": verb, "said": said,
                        "note": step.get("note", "")})
        return outcome

    def fly(self) -> dict:
        log(f"\n--- mission {self.index}: {self.plan['goal']}")
        log(f"    because: {self.plan['why']}")
        for number, step in enumerate(self.plan["steps"], 1):
            outcome = self._one(number, step)
            self.steps.append(outcome)
            log(f"  {'ok  ' if outcome['ok'] else 'STOP'} {number}. "
                f"{outcome['said']}: {outcome['happened']}")
            if not outcome["ok"]:
                break

        expectations = [s for s in self.steps if s["do"] == "expect"]
        met = [s for s in expectations if s["ok"]]
        ran = len(self.steps) == len(self.plan["steps"]) and self.steps[-1]["ok"]
        if ran and expectations and len(met) == len(expectations):
            self.verdict = (f"achieved: every step ran and all {len(met)} expectation(s) "
                            f"held")
        elif ran:
            self.verdict = ("ran to the end, but an expectation did not hold: "
                            + "; ".join(s["happened"] for s in expectations if not s["ok"]))
        else:
            self.verdict = (f"stopped at step {self.steps[-1]['n']} of "
                            f"{len(self.plan['steps'])} - {self.steps[-1]['happened']}")
        log(f"    verdict: {self.verdict}")
        return {"index": self.index, "goal": self.plan["goal"], "why": self.plan["why"],
                "success": self.plan.get("success", ""),
                "abandon_if": self.plan.get("abandon_if", ""),
                "steps": self.steps, "verdict": self.verdict,
                "verdicts_bought": self.verdicts_bought,
                "achieved": self.verdict.startswith("achieved")}


def describe_step(step: dict) -> str:
    """A step as a person would read it, used in both the log and the report."""
    verb = step.get("do")
    if verb == "go":
        return f"go to {step.get('screen')}"
    if verb == "press":
        times = int(step.get("times", 1) or 1)
        return f"press {step.get('key')}" + (f" x{times}" if times > 1 else "")
    if verb in ("click", "hover"):
        if step.get("element"):
            return f"{verb} {step['element']!r}"
        at = step.get("at") or [0, 0]
        return f"{verb} at ({at[0]:.3f}, {at[1]:.3f})"
    if verb == "expect":
        if step.get("screen"):
            return f"expect to be on {step['screen']}"
        return f"expect the screen to be {step.get('that')}"
    if verb == "wait":
        return f"wait {step.get('seconds')}s"
    return str(verb)


def newest_map(out: Path, game: str) -> tuple[Path | None, str]:
    """The newest map of this game that this code can still read, and what was skipped.

    By modification time rather than by the timestamp in the directory name, which was
    the first version and was wrong twice over: `Path.glob` is case-insensitive on
    Windows, so a run directory named in lower case sorted above one named in title case
    and a map from an hour earlier won; and a directory's name is a claim about when a
    run started, not about when its last pass finished writing.

    Skipping incompatible schemas rather than failing on them, because the newest map is
    not necessarily the newest *readable* map, and "there is nothing to plan from" is a
    much worse answer than planning from the one before it. `Recon.resume` refuses an old
    schema outright, which is correct for a resume and useless as a search."""
    wanted = game.lower()
    found = sorted((path for path in out.glob("*/**/ontology.json")
                    if path.parent.name.lower().startswith(wanted)
                    or path.parent.parent.name.lower().startswith(wanted)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    stale = 0
    for path in found:
        try:
            schema = json.loads(path.read_text(encoding="utf-8")).get("schema")
        except (OSError, ValueError):
            continue
        if schema == recon.SCHEMA:
            return path.parent, (f"skipped {stale} older map(s) written by an earlier "
                                 f"schema" if stale else "")
        stale += 1
    return None, (f"{stale} map(s) exist but all were written by an earlier schema"
                  if stale else "")


def write_missions(out: Path, game: str, flown: list[dict], grew: dict) -> Path:
    lines = [f"# {game} - {len(flown)} missions\n",
             "Each mission was written by the model from the map as it stood, then "
             "executed literally. The verdict is the harness's, not the model's: a "
             "mission is achieved only if every step ran and every `expect` step held.\n"]
    for mission in flown:
        lines.append(f"## Mission {mission['index']}: {mission['goal']}\n")
        lines.append(f"**Why:** {mission['why']}\n")
        lines.append(f"**Would count as success:** {mission['success']}\n")
        lines.append(f"**Verdict:** {mission['verdict']}\n")
        lines.append("| # | step | expected | what happened |")
        lines.append("| --- | --- | --- | --- |")
        for step in mission["steps"]:
            lines.append(f"| {step['n']} | {step['said']} | {step.get('note', '')} "
                         f"| {step['happened']} |")
        lines.append("")
    lines.append("## What the missions added to the map\n")
    lines.append(f"{grew['screens_before']} screens and {grew['transitions_before']} "
                 f"transitions going in; {grew['screens_after']} and "
                 f"{grew['transitions_after']} coming out. "
                 f"{grew['actions']} actions were sent, and "
                 f"{sum(m['verdicts_bought'] for m in flown)} safety verdicts were bought "
                 f"for controls the explorer had never proposed.\n")
    achieved = [m for m in flown if m["achieved"]]
    lines.append(f"{len(achieved)} of {len(flown)} missions were achieved. "
                 + ("The ones that were not are the more informative half: a plan that "
                    "broke at a named step says exactly which belief about the game was "
                    "wrong.\n" if len(achieved) < len(flown) else "\n"))
    path = out / "missions.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", required=True,
                        help="the game's name, as a person would write it")
    parser.add_argument("--from", dest="source", default=None,
                        help="a directory holding the ontology.json to plan from; "
                             "defaults to the newest one recorded for this game")
    parser.add_argument("--missions", type=int, default=MISSIONS)
    parser.add_argument("--budget", type=float, default=sweep.BUDGET,
                        help="hard wall-clock ceiling in minutes over the whole run")
    parser.add_argument("--no-clicks", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()
    deadline = started + args.budget * 60
    live: list[Controller] = []
    sweep.arm_kill_switch(deadline, args.budget, lambda: live[0] if live else None)

    calibration = calibrate.load(args.game)
    target = targets.resolve(args.game, calibration)

    here = Path(__file__).parent
    source, aside = (Path(args.source), "") if args.source \
        else newest_map(here / "out", target.name)
    if source is None or not (source / "ontology.json").exists():
        raise SystemExit(f"no map to plan from for {target.name!r}"
                         + (f" - {aside}" if aside else " under out/")
                         + f". Run `py sweep.py --game {args.game!r}` first: a mission is "
                         f"written from a map, and there is nothing here to read.")
    log(f"planning from {source.relative_to(here)}" + (f" ({aside})" if aside else ""))

    out = here / "out" / f"{target.name}-missions-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)

    import describe
    director = describe.make_director()
    vetter = describe.make_vetter()

    set_dpi_aware()
    controller = Controller(target)
    live.append(controller)
    session = recon.Recon(controller, out, vetter=vetter, allow_clicks=not args.no_clicks)
    data = json.loads((source / "ontology.json").read_text(encoding="utf-8"))
    log(f"  {session.resume(data, source)}")
    grew = {"screens_before": len(session.screens),
            "transitions_before": len(session.transitions)}

    flown: list[dict] = []
    try:
        controller.start()
        for index in range(1, args.missions + 1):
            left = (deadline - time.monotonic()) / 60
            if left < sweep.BUDGET_FLOOR:
                log(f"\nbudget spent with {left * 60:.0f}s left; not planning mission "
                    f"{index}")
                break

            screen, variant, _ = session.look()
            standing = session.to_json()
            # Captured fresh rather than reusing the appearance's stored PNG. They are
            # usually the same picture, but a resumed map's images were taken minutes or
            # days ago by an earlier pass, and the one question this call has to answer
            # correctly is "where are we now".
            shot = out / "images" / f"mission{index}-standing.png"
            controller.save_png(shot)
            content = [
                {"type": "text", "text": digest(standing, screen.id, flown)},
                {"type": "text", "text":
                    f"\nThe harness is standing on {screen.id}, appearance {variant.id}, "
                    f"which looks like this right now:"},
                describe.image_block(shot),
                {"type": "text", "text":
                    f"\nPlan mission {index} of at most {args.missions}. "
                    f"{left:.0f} minutes of budget are left."},
            ]
            plan = director(content, known_names(standing))
            flown.append(Mission(session, index, plan).fly())
            session.save()
            recon.write_report(session.to_json(), out)
    except (WindowLost, OSError) as error:
        controller.note(f"missions ended early - {type(error).__name__}: {error}")
    finally:
        session.save()
        recon.write_report(session.to_json(), out)
        try:
            controller.close()
        except OSError as error:
            log(f"  could not close the game: {error}")
        live.clear()

    if not flown:
        log("no mission was flown")
        return
    grew.update(screens_after=len(session.screens),
                transitions_after=len(session.transitions),
                actions=session.actions_taken)
    log(f"\nwrote {write_missions(out, target.name, flown, grew)}")
    log(f"{sum(1 for m in flown if m['achieved'])} of {len(flown)} missions achieved; "
        f"the map went from {grew['screens_before']} screens and "
        f"{grew['transitions_before']} transitions to {grew['screens_after']} and "
        f"{grew['transitions_after']}")


if __name__ == "__main__":
    main()
