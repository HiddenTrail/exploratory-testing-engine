"""The intelligence half: look at what recon collected and say what it means.

Three jobs, deliberately separate because they answer to different pressures.

**Vetting** runs inside the loop, once per newly discovered screen, and exists to
decide what the explorer is allowed to press. It is a safety gate, so it is small,
fast, and biased: `SAFETY_BRIEF` tells the model that the two ways of being wrong do
not cost the same, and that uncertainty resolves toward "dangerous".

**Annotation** runs afterwards over the finished graph and writes the ontology proper
- names, roles, and for each element what it does *per input modality*, since
"clicked" and "scrolled to with the keyboard" are different behaviours of the same
control and a description that merges them has lost the thing worth knowing.

**Direction** runs between sessions and is the only one of the three that decides what
the harness *does*. It reads the map and writes the next mission: a goal and a short
list of steps that `mission.py` executes literally. It is the same discipline pointed
forward - a mission must contain at least one `expect` step, so the plan carries its
own test and the harness can call it wrong.

The one rule that makes the output trustworthy: **every behaviour claim either cites
the transitions that witnessed it, or is marked a hypothesis.** This is enforced in
`_validate_annotation`, not requested in the prompt - a cited transition ID that does
not exist in the ontology is a rejected tool call, and the retry loop hands the model
its own invented IDs back. Asking nicely for provenance produces confident prose
about buttons that were never pressed; refusing to accept the call produces either a
citation or an admission. The distinction survives into the JSON and the report, so a
later consumer can take the observed claims and leave the guesses.

Transport is `engine/client.py` - the same Bedrock-or-API-key client, forced tool
calls, schema validation and informed retries the rest of the repo uses. Reusing it
does not make this experiment part of the engine: what is standalone here is the
ontology schema and the exploration policy, and reimplementing auth and backoff to
prove a point would only add a second thing to keep working. `call_tool_with_retry`
passes `user_message` through as the message content untouched, so handing it a list
of blocks gets image support with no change on that side.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.client import build_client, call_tool_with_retry, default_model  # noqa: E402
# What a coordinate has to look like to be aimable, from the file that defines the
# coordinate system. Imported rather than restated so that this module cannot end up
# accepting a coordinate `Controller.point` would refuse.
from controller import MODIFIERS, MOUSE_BUTTONS, is_fraction, readable_output  # noqa: E402
# The one thing shared with the session that produces the evidence: the order the
# close-ups of an action go in. Imported rather than repeated, so a fourth slot cannot be
# filmed and then quietly not shown. Safe as a top-level import because `recon` only ever
# reaches for this module inside a function.
from recon import CROP_SLOTS  # noqa: E402
from target import SAFETY_BRIEF  # noqa: E402

VET_MAX_TOKENS = 1500
ANNOTATE_MAX_TOKENS = 6000

VET_SYSTEM = f"""\
You are looking at one appearance of one screen of a video game, reached by an
automated explorer. The explorer has no idea what this game is; everything known
about it was measured from pixels.

Your job is to decide what it may press next, and to name the screen. Be concrete and
describe only what is visible - if you cannot read a label, say so rather than
guessing what it probably says.

Judge a keypress against WHAT IS CURRENTLY SELECTED, and report that selection in
`highlighted`. A key like Enter acts on the highlighted entry, so it is not safe or
unsafe in general - it is safe or unsafe for *this* entry. If the highlighted entry
is an ordinary, reversible destination, clear Enter for it; if the highlighted entry
would erase progress or quit, refuse it. Do not refuse a key merely because some
*other* entry on this screen would be dangerous to activate: the explorer will ask
again about that entry when it is the one selected.

{SAFETY_BRIEF}
First, though: this is supposed to be a video game, and the explorer cannot tell whether
it is. If what you are looking at is not a game - an editor, a browser, a file manager, a
desktop, an installer, anything belonging to the person whose machine this is - say so in
`name` and refuse EVERY action, explaining that the explorer is not looking at the game.
Typing into somebody's work is the worst thing this explorer can do, and you are the only
part of it that can read the screen well enough to notice.

Some candidates are not clicks or keys. Judge each for what it actually does:

- A DRAG presses at one point, travels to another with the button held, and releases.
  Ask what it would carry, pan or sweep out. It is usually reversible - a view that
  scrolled can scroll back - but on a screen that arranges things it can move a piece
  somewhere it cannot be put back, and where it *starts* is what it picks up.
- A WHEEL scroll over a point. Usually a view moving, and harmless. Refuse it where a
  wheel would set a value rather than move a view - a quantity to buy, sell or commit -
  because a number changed by a wheel is a decision, and this explorer cannot read it
  well enough to change it back.
- Both are aimed by the explorer at the MIDDLE of the window, blind, because nothing in
  a picture says what can be dragged or scrolled. So they usually arrive with no
  close-up. Judge them on the full window and on what is likely to be under that point.

You must return a verdict for every action you are given, using the exact action_id
strings supplied.

You may be given close-ups as well as the whole window: the same frame at full
resolution, cropped to cells that were measured to change. A pair labelled `at rest` and
`with the cursor on it` is one control photographed twice, and the difference between
them is the only direct evidence anyone has about what that point does. The full-window
image is scaled down, so where it and a close-up disagree, the close-up is right.
"""

ANNOTATE_SYSTEM = """\
You are writing the ontology of a video game's user interface from evidence gathered
by an automated explorer. You get one screen at a time: images of how it looked, and
the complete list of transitions observed from it - which input was sent, and whether
it changed nothing, changed the screen's appearance, or moved to a different screen.

Some transitions also come with close-ups: the same frames at full resolution, cropped
to the part of the window that changed. Those are the reliable evidence about small
effects. The full-window images are scaled down far enough that a highlight, a tick or a
digit changing is a few pixels in them, so where a close-up and your reading of the full
frame disagree, the close-up is right. A crop labelled `pressed` was taken with the mouse
button still held down, which is a state no other picture in the evidence contains.

Describe each interactive element you can identify, and for each one record its
behaviour SEPARATELY PER INPUT MODALITY. This matters more than anything else in the
task: a control reached by keyboard and a control reached by clicking are different
behaviours of the same thing, and a game may respond to one and ignore the other. Use
modality strings like "click", "hover", "key:down", "key:enter", "drag", "scroll".

Drag and scroll evidence deserves particular care, because it is what the explorer knows
least about. It probes both blind, in the middle of the window, so a drag that moved
something is a finding about the whole screen - the view pans, the background is a
draggable surface - and not about a control. Say which of the two you mean, and if a
wheel did nothing, record that: a screen whose content is taller than its frame and does
not scroll is worth knowing about.

Rules on evidence, which are enforced and will cause your call to be rejected:

- Every behaviour entry either cites the transition IDs that witnessed it in
  `evidence`, or sets `hypothesis` to true. Never both empty.
- Only cite transition IDs that appear in the evidence you were given. Do not invent
  IDs, and do not cite a transition from a different screen.
- "effect" describes what was observed. If a transition shows an input doing nothing
  visible, say that it does nothing - that is a real and useful finding, not a gap to
  paper over. An input that does nothing when clicked but works from the keyboard is
  exactly the kind of thing this ontology exists to record.

Write the description of the screen as context: where it sits relative to other
screens, what it is for, and how you get in and out of it.
"""

VET_TOOL = {
    "name": "vet_screen",
    "description": "Name this screen and rule on which actions the explorer may take.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short name, e.g. 'main menu'."},
            "purpose": {"type": "string", "description": "One or two sentences on what this screen is for."},
            "highlighted": {"type": "string", "description":
                            "The entry that appears selected right now, as written on screen, "
                            "or '' if nothing is. This is what a keypress would act on."},
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "what": {"type": "string"},
                        "at": {"type": "array", "items": {"type": "number"},
                               "description": "Fractional [x, y] of the client area, if locatable."},
                    },
                    "required": ["label", "what"],
                },
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string", "description": "Exactly as supplied."},
                        "safe": {"type": "boolean"},
                        "why": {"type": "string"},
                    },
                    "required": ["action_id", "safe", "why"],
                },
            },
        },
        "required": ["name", "purpose", "actions"],
    },
}

ANNOTATE_TOOL = {
    "name": "describe_screen",
    "description": "Record what this screen is and how each element behaves per input modality.",
    "input_schema": {
        "type": "object",
        "properties": {
            # Described, or the model names it after the id the evidence refers to it by -
            # and this pass overwrites the name the vetting call had already got right.
            "name": {"type": "string", "description":
                     "What a person would call this screen, e.g. 'main menu'. Never an "
                     "identifier like 'sc03'."},
            "role": {"type": "string", "description": "e.g. 'menu', 'gameplay', 'modal dialog', 'settings'."},
            "description": {"type": "string",
                            "description": "The screen in context: what it is for, how you reach it, how you leave."},
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "what": {"type": "string"},
                        "at": {"type": "array", "items": {"type": "number"}, "description":
                               "Where it is, as fractions of the window: [x, y] with both "
                               "between 0.0 and 1.0, so [0.5, 0.5] is the centre. Never "
                               "pixels. Omit it if you cannot place the element."},
                        "behaviour": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "modality": {"type": "string",
                                                 "description": "'click', 'hover', 'key:down', 'key:enter', ..."},
                                    "effect": {"type": "string"},
                                    "evidence": {"type": "array", "items": {"type": "string"},
                                                 "description": "Transition IDs that witnessed this."},
                                    "hypothesis": {"type": "boolean",
                                                   "description": "True if not directly observed."},
                                },
                                "required": ["modality", "effect"],
                            },
                        },
                    },
                    "required": ["label", "what", "behaviour"],
                },
            },
            "notes": {"type": "array", "items": {"type": "string"},
                      "description": "Anything odd, or that the evidence cannot settle."},
        },
        "required": ["name", "role", "description", "elements"],
    },
}


def image_block(path: Path) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(path.read_bytes()).decode()}}


# --- vetting (in the loop) --------------------------------------------------

def make_vetter(model: str | None = None, client=None):
    """A callable for `Recon`: (image path, screen, candidate actions, crops) -> verdict.

    Built as a closure so the client is constructed once for the session rather than
    per screen, and so `recon.py` can be handed a plain callable and stay unaware of
    which provider is behind it - or whether there is one at all."""
    client = client or build_client()
    model = model or default_model()

    def vet(image_path: Path, screen, variant, candidates, crops=()) -> dict:
        listing = "\n".join(
            f"- {action.id}  ({action.describe()})" for action in candidates)
        hotspots = ", ".join(f"({x:.2f}, {y:.2f})" for x, y in screen.hotspots) or "none"
        seen = [f"{v.id}: selected {v.highlighted!r}"
                for v in screen.variants.values() if v.highlighted and v is not variant]
        content = [
            {"type": "text", "text":
                f"Screen {screen.id}, appearance {variant.id}. The cursor was swept "
                f"across this screen and these fractional points produced a visible "
                f"reaction: {hotspots}."
                + (f"\n\nOther appearances of this same screen have already been ruled "
                   f"on, with these selections:\n" + "\n".join(f"- {s}" for s in seen)
                   if seen else "")
                + "\n\nHere it is:"},
            image_block(image_path),
        ]
        # The full window is scaled to fit 1400px, which on a 4K client shrinks a menu
        # button to a few dozen pixels - readable enough to locate, not to judge. These are
        # the same pixels uncompressed, cropped to what was measured to move, and they are
        # what makes "what does hovering do here" an answerable question.
        if crops:
            content.append({"type": "text", "text":
                            "Close-ups of the same frame, at full resolution, cropped to "
                            "the cells that were measured to change. Each is labelled with "
                            "the point it belongs to:"})
            for crop in crops:
                content.append({"type": "text", "text": crop["label"]})
                content.append(image_block(Path(crop["path"])))
        content.append(
            {"type": "text", "text":
                f"Rule on each of these candidate actions:\n{listing}\n\n"
                f"Return a verdict for every action_id above, exactly as written, and "
                f"report what is currently selected."})

        def validate(payload: dict) -> list[str]:
            given = {entry.get("action_id") for entry in payload.get("actions", [])}
            missing = [a.id for a in candidates if a.id not in given]
            unknown = [i for i in given if i not in {a.id for a in candidates}]
            errors = []
            if missing:
                errors.append(f"no verdict for: {', '.join(missing)}")
            if unknown:
                errors.append(f"verdicts for actions that were not offered: {', '.join(unknown)}")
            return errors

        payload = call_tool_with_retry(
            client, model=model, system=VET_SYSTEM, tools=[VET_TOOL],
            tool_name="vet_screen", user_message=content, validate_fn=validate,
            max_tokens=VET_MAX_TOKENS, cache_static_content=True)

        return {
            "name": payload["name"],
            "purpose": payload["purpose"],
            "highlighted": payload.get("highlighted", ""),
            "elements": payload.get("elements", []),
            "actions": {entry["action_id"]: {"safe": entry["safe"], "why": entry["why"]}
                        for entry in payload["actions"]},
        }

    return vet


# --- direction (between sessions) -------------------------------------------

PLAN_MAX_TOKENS = 2500
# Wheel notches allowed in one step. Named up here because the schema quotes it. Past
# this a scroll stops being a probe and becomes a way to lose the top of a list.
MAX_NOTCHES = 10

# The step vocabulary, defined here because it is what the model is told it may write
# and in `mission.py` it is what the executor knows how to do. One list, so a verb
# cannot be offered without being implemented or implemented without being offered.
STEP_VERBS = {
    "go": "travel to a screen already on the map, by a route the harness has observed. "
          "Give `screen`.",
    "press": "send a key. Give `key`, and `times` if it should be repeated.",
    "click": "click a control. Give `element` (a label from the map, preferred) or "
             "`at` as fractional [x, y]. Optionally `button` ('right' or 'middle') "
             "and `modifiers` (e.g. ['shift']).",
    "hover": "move the cursor onto something without pressing. Same targeting as click.",
    "drag": "press at one point, travel to another with the button held, release. "
            "Target the start with `element` or `at`, and give `to` as fractional "
            "[x, y] for the end. This is the only way to pan a view, move a slider, "
            "or carry something somewhere - a click cannot do any of them, and neither "
            "can a click followed by a click.",
    "scroll": "turn the mouse wheel over a point. Give `notches`: positive is up, away "
              "from you; negative is down. Target as for click, or give no target to "
              "scroll over the middle of the window. Set `horizontal` for a sideways "
              "wheel. Use this when a screen looks like it has more content than fits.",
    "expect": "no input at all - a check. Give `screen` for 'we should now be on this "
              "screen', or `that` = 'new' for 'this should be somewhere not yet on the "
              "map', or 'changed' for 'the picture should have changed'.",
    "wait": "let the game run without input. Give `seconds`.",
    "restart": "close the game and launch it cold, to get back to a known state.",
}

DIRECTOR_SYSTEM = f"""\
You are directing an automated harness that drives a video game it does not understand.
Everything it knows was measured from pixels by a blind explorer: it pressed keys and
clicked points, and recorded which screens it could tell apart and which inputs moved
between them. You are given that map, a screenshot of where the harness is standing
right now, and the missions already flown.

Your job is to write the NEXT MISSION: one goal, and the steps that would achieve it.

The steps are executed literally, in order, by a program with no judgement. It stops at
the first step that fails. So:

- Name only screens and element labels that appear in the map you were given.
- Prefer `go` over re-deriving a route: the harness knows the edges it has observed.
- A mission must contain at least one `expect` step. That is what makes it a test rather
  than a wish - the harness reports whether your expectation held, and a mission that
  cannot be wrong teaches nothing. Put one where your reasoning is most likely to break.
- Keep it short. Five well-aimed steps that settle one question beat twelve that drift.

What is worth a mission, in rough order: a screen the map reaches but never explored; a
control the explorer could not use because the game ignores the cursor and there was
nothing to click; a route the map suggests but has never traversed; getting into actual
gameplay rather than menus, if the map shows a way in. Say which of these you are doing
in `why`, and refer to the screens by id.

You can also drag and scroll, and you are better placed to use them than the explorer is.
It probes them blind, in the middle of the window, because nothing about a picture says
what is draggable - but you can see the screen. A list with its last row cut off, a map
larger than its frame, a slider, a card or a piece that has to go somewhere: those are all
things only a drag or a wheel can operate, and a plan that clicks them instead will report
that clicking did nothing, which is true and useless.

{SAFETY_BRIEF}
Every committing action in your plan is separately vetted before it is sent, by the same
standard, and may be refused - which ends the mission there. Do not plan around that by
disguising an action; a refusal is a finding and is recorded as one.
"""

PLAN_TOOL = {
    "name": "plan_mission",
    "description": "Set the next mission for the harness: one goal, and the steps to try.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string",
                     "description": "One line: what this mission is for."},
            "why": {"type": "string",
                    "description": "What in the map suggests it, by screen id."},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "do": {"type": "string", "enum": sorted(STEP_VERBS),
                               "description": "\n".join(f"{verb}: {what}" for verb, what
                                                        in STEP_VERBS.items())},
                        "screen": {"type": "string", "description": "A screen id, e.g. 'sc02'."},
                        "key": {"type": "string"},
                        "times": {"type": "integer"},
                        "element": {"type": "string", "description": "A label from the map."},
                        "at": {"type": "array", "items": {"type": "number"},
                               "description": "Fractional [x, y], both 0.0 to 1.0. "
                                              "Never pixels."},
                        "to": {"type": "array", "items": {"type": "number"},
                               "description": "Where a drag ends, as fractional [x, y]."},
                        "notches": {"type": "integer",
                                    "description": f"Wheel notches for `scroll`: "
                                                   f"-{MAX_NOTCHES} to {MAX_NOTCHES}, "
                                                   f"positive up. Not zero."},
                        "horizontal": {"type": "boolean",
                                       "description": "Scroll sideways instead of up."},
                        "button": {"type": "string", "enum": list(MOUSE_BUTTONS),
                                   "description": "Mouse button for `click` or `drag`; "
                                                  "left if omitted."},
                        "modifiers": {"type": "array",
                                      "items": {"type": "string", "enum": list(MODIFIERS)},
                                      "description": "Keys held down while the action is "
                                                     "sent, e.g. ['shift'] for a "
                                                     "shift+scroll."},
                        "that": {"type": "string", "enum": ["new", "changed"]},
                        "seconds": {"type": "number"},
                        "note": {"type": "string",
                                 "description": "What you expect this step to do."},
                    },
                    "required": ["do"],
                },
            },
            "success": {"type": "string",
                        "description": "What would show the mission achieved its goal."},
            "abandon_if": {"type": "string",
                           "description": "What would show it is not worth continuing."},
        },
        "required": ["goal", "why", "steps", "success"],
    },
}

MAX_STEPS = 12
# Repeats of one key in a single step, and seconds of doing nothing. Both are here to
# keep a plan from spending a whole mission inside one step: a plan that needs fifty
# presses has misunderstood something, and the report is more useful if it says so.
MAX_REPEAT = 12
MAX_WAIT = 15.0


def make_director(model: str | None = None, client=None):
    """A callable: (message content, what the map contains) -> a mission dict.

    Validation is where this earns its keep. A plan that names a screen or a control
    that does not exist is not a plan the harness can execute, and the failure would
    otherwise land at step 4 of 6 with the game halfway through a menu. Rejecting the
    tool call hands the model its own invented names back and costs a retry instead."""
    client = client or build_client()
    model = model or default_model()

    def plan(content: list[dict], known: dict) -> dict:
        def validate(payload: dict) -> list[str]:
            steps = payload.get("steps") or []
            errors = []
            if not steps:
                errors.append("a mission needs at least one step")
            if len(steps) > MAX_STEPS:
                errors.append(f"{len(steps)} steps is more than the {MAX_STEPS} allowed")
            if not any(step.get("do") == "expect" for step in steps):
                errors.append("no `expect` step: a mission has to be able to fail, so "
                              "state what you expect to be true and where")
            for index, step in enumerate(steps, 1):
                verb = step.get("do")
                where = f"step {index} ({verb})"
                if verb in ("go",) and step.get("screen") not in known["screens"]:
                    errors.append(f"{where} names screen {step.get('screen')!r}, which is "
                                  f"not on the map. Known: {', '.join(sorted(known['screens']))}")
                if verb == "expect" and not step.get("screen") and not step.get("that"):
                    errors.append(f"{where} checks nothing: give `screen` or `that`")
                if verb == "expect" and step.get("screen") \
                        and step["screen"] not in known["screens"]:
                    errors.append(f"{where} expects screen {step['screen']!r}, which is not "
                                  f"on the map - use `that`: 'new' for somewhere unmapped")
                if verb == "press":
                    key = (step.get("key") or "").lower()
                    # A single character is sent by its virtual-key code, so 'w' or '1'
                    # work on a game that binds them; anything longer has to be a name
                    # the harness knows.
                    if key not in known["keys"] and len(key) != 1:
                        errors.append(f"{where} sends {step.get('key')!r}; this harness can "
                                      f"send {', '.join(sorted(known['keys']))} or a single "
                                      f"character")
                    if not 1 <= int(step.get("times", 1) or 1) <= MAX_REPEAT:
                        errors.append(f"{where} repeats {step.get('times')} times; "
                                      f"1 to {MAX_REPEAT} allowed")
                if verb in ("click", "hover", "drag", "scroll"):
                    label, at = step.get("element"), step.get("at")
                    # A scroll is the one aimed action with a sensible default target:
                    # the middle of the window, which is where the explorer probes and
                    # what "scroll this screen" means when nothing is named.
                    if not label and not at and verb != "scroll":
                        errors.append(f"{where} has no target: give `element` or `at`")
                    if label and label.strip().lower() not in known["labels"]:
                        errors.append(
                            f"{where} targets {label!r}, which is not a label the map "
                            f"records. Known: {', '.join(sorted(known['labels'])) or '(none)'}")
                    if at and not is_fraction(at):
                        errors.append(f"{where} targets {at}, which is not a fractional "
                                      f"[x, y] inside the window")
                    bad = [m for m in (step.get("modifiers") or []) if m not in MODIFIERS]
                    if bad:
                        errors.append(f"{where} holds {', '.join(map(str, bad))}; this "
                                      f"harness holds {', '.join(MODIFIERS)}")
                    if step.get("button") and step["button"] not in MOUSE_BUTTONS:
                        errors.append(f"{where} uses the {step['button']!r} button; this "
                                      f"harness has {', '.join(MOUSE_BUTTONS)}")
                if verb == "drag":
                    end = step.get("to")
                    if not end:
                        errors.append(f"{where} is a drag with no `to`, so it is a click "
                                      f"with extra steps. Give where it ends.")
                    elif not is_fraction(end):
                        errors.append(f"{where} drags to {end}, which is not a fractional "
                                      f"[x, y] inside the window")
                    elif at and list(map(float, at)) == list(map(float, end)):
                        errors.append(f"{where} drags from {at} to the same point, which "
                                      f"sends no motion at all")
                if verb == "scroll":
                    notches = step.get("notches")
                    if not notches:
                        errors.append(f"{where} scrolls {notches!r} notches; give a "
                                      f"non-zero number, positive for up")
                    elif abs(int(notches)) > MAX_NOTCHES:
                        errors.append(f"{where} scrolls {notches} notches; "
                                      f"-{MAX_NOTCHES} to {MAX_NOTCHES} allowed")
                if verb == "wait" and not 0 < float(step.get("seconds", 0) or 0) <= MAX_WAIT:
                    errors.append(f"{where} waits {step.get('seconds')}s; up to "
                                  f"{MAX_WAIT:.0f} allowed")
            return errors

        return call_tool_with_retry(
            client, model=model, system=DIRECTOR_SYSTEM, tools=[PLAN_TOOL],
            tool_name="plan_mission", user_message=content, validate_fn=validate,
            max_tokens=PLAN_MAX_TOKENS, cache_static_content=True)

    return plan


# --- annotation (after the session) ----------------------------------------

EFFECTS = {"none": "nothing visible changed",
           "variant": "the same screen, but its appearance changed",
           "screen": "moved to a different screen"}


def _evidence_text(screen: dict, transitions: list[dict], screens: list[dict]) -> str:
    names = {s["id"]: (s.get("name") or s["id"]) for s in screens}
    lines = [f"Screen {screen['id']}. Seen {screen['observations']} times.",
             f"A preliminary look during exploration called it "
             f"{(screen.get('name') or 'unnamed')!r}: {screen.get('purpose') or '-'}",
             "",
             "Where content moved between visits ('#' = this cell never held still, "
             "so something dynamic lives there):"]
    lines += screen["volatile_map"]
    lines.append("")
    if screen.get("animated_cells"):
        # Said explicitly because the map above cannot distinguish them, and a reader
        # who cannot will attribute a mascot's next frame to whatever was pressed.
        lines.append(f"{screen['animated_cells']} cells were measured moving with no input "
                     f"at all, so a change confined to them is not something an action did:")
        lines += screen["animated_map"]
        lines.append("")
    if screen["hover"]["inert"]:
        lines.append(f"The cursor was swept over {screen['hover']['probed']} points and "
                     f"nothing reacted: this screen ignores hover entirely.")
    else:
        lines.append(f"Of {screen['hover']['probed']} points the cursor was moved to, "
                     f"these reacted visibly: "
                     + ", ".join(f"({x:.2f}, {y:.2f})"
                                 for x, y in screen["hover"]["reacting_points"]))
    lines += ["", "Transitions observed from this screen:"]
    mine = [t for t in transitions if t["from"] == screen["id"]]
    if not mine:
        lines.append("(none - nothing was ever successfully sent from here)")
    for t in mine:
        destination = f" -> {names.get(t['to'], t['to'])} ({t['to']})" if t["effect"] == "screen" else ""
        lines.append(f"- {t['id']}: {t['action']['id']} => {EFFECTS[t['effect']]}"
                     f"{destination}; {t['changed_cells']} of 576 grid cells changed, "
                     f"settled in {t['settle_ms']}ms, taken {t['times_taken']}x")
    return "\n".join(lines)


ANNOTATE_CROPS = 8       # close-ups one screen's description may carry, on top of its
                         # appearances. The cap is the image budget; the ordering below is
                         # what makes the cap cheap to live with


def _crop_blocks(out: Path, mine: list[dict]) -> list[dict]:
    """Close-ups of the transitions this screen is being described from.

    Smallest change first, which is the opposite of what looks natural and is the whole
    reason these exist: a transition that repainted 300 cells is already legible in the
    full-window pictures, while the 4-cell one - a checkbox ticking, a counter advancing,
    a button going dark - is the one the model has been describing blind. Those are also
    exactly the transitions whose `effect` is easiest to get wrong in prose."""
    ranked = sorted((t for t in mine if (t.get("crops") or {})),
                    key=lambda t: t["changed_cells"])
    blocks: list[dict] = []
    spent = 0
    for transition in ranked:
        slots = [(slot, out / transition["crops"][slot])
                 for slot in CROP_SLOTS
                 if transition["crops"].get(slot)]
        slots = [(slot, path) for slot, path in slots if path.exists()]
        if not slots or spent + len(slots) > ANNOTATE_CROPS:
            continue
        spent += len(slots)
        blocks.append({"type": "text", "text":
                       f"\n{transition['id']} ({transition['action']['id']}, "
                       f"{transition['changed_cells']} cells changed) at full resolution, "
                       f"cropped to the part of the window that took part - "
                       + ", then ".join(slot for slot, _ in slots)
                       + ". `pressed` is the frame with the mouse button still down:"})
        for _, path in slots:
            blocks.append(image_block(path))
    return blocks


def annotate(out: Path, model: str | None = None, client=None, limit: int = 0) -> Path:
    """Read a session's ontology.json, describe every screen, write it back.

    One call per screen rather than one for the whole graph: a screen plus its images
    is a self-contained question, and a single call carrying every screenshot would
    both blow the image budget and invite the model to describe screens using
    evidence that belongs to other ones."""
    path = out / "ontology.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    client = client or build_client()
    model = model or default_model()

    valid_ids = {t["id"] for t in data["transitions"]}
    screens = data["screens"][:limit] if limit else data["screens"]

    for index, screen in enumerate(screens, 1):
        mine = {t["id"] for t in data["transitions"] if t["from"] == screen["id"]}
        images = [screen["image"]] + [v["image"] for v in screen["variants"][:5]]
        images = [out / rel for rel in dict.fromkeys(filter(None, images))]

        content: list[dict] = [{"type": "text", "text": _evidence_text(
            screen, data["transitions"], data["screens"])}]
        for image in images:
            if image.exists():
                content.append({"type": "text", "text": f"\nAppearance `{image.stem}`:"})
                content.append(image_block(image))
        for shot in (out / rel for rel in screen.get("animation", [])):
            if shot.exists():
                content.append({"type": "text", "text":
                                f"\nFrame {shot.stem[-1]} of what this screen moves with no "
                                f"input at all, cropped to the cells that move:"})
                content.append(image_block(shot))
        content += _crop_blocks(out, [t for t in data["transitions"]
                                      if t["from"] == screen["id"]])
        content.append({"type": "text", "text":
                        "\nDescribe this screen and its elements. Cite only these "
                        f"transition IDs: {', '.join(sorted(mine)) or '(none available)'}. "
                        "Any behaviour you cannot support with one of them must set "
                        "hypothesis to true."})

        def validate(payload: dict, allowed: set[str] = mine) -> list[str]:
            errors = []
            # Every field the code below this call reads with `[...]` rather than `.get`.
            # Checked here so that a payload missing one costs a retry with the name of the
            # field in it, instead of a KeyError that ends the whole pass and takes the
            # screens after this one with it - which is how the `'str' object has no
            # attribute 'get'` failure played out, from the same cause: work done on a
            # payload the validator had not established the shape of.
            for field in ("name", "role", "description"):
                if not payload.get(field):
                    errors.append(f"no {field!r}, which is required")
            for element in payload.get("elements", []):
                # A schema is a request, not a guarantee: one call returned a bare string
                # where an element object belongs and this pass died inside its own
                # validator, taking the screens after it with it. Said back to the model
                # instead, which is what the retry is for.
                if not isinstance(element, dict):
                    errors.append(f"elements contains {element!r}, which is not an object "
                                  f"with label, what and behaviour")
                    continue
                for field in ("label", "what"):
                    if not element.get(field):
                        errors.append(f"an element has no {field!r}: "
                                      f"{json.dumps(element)[:120]}")
                at = element.get("at")
                if at is not None and not is_fraction(at):
                    # A coordinate is the one field in here that something downstream
                    # *acts* on: a mission clicks an element by label and gets sent
                    # wherever this says. One real map came back with `at: [697, 190]`,
                    # pixels of a 1400px-wide screenshot, which as a fraction is a
                    # thousand windows to the right of the game. A wrong description is
                    # read by a person; a wrong coordinate is pressed.
                    errors.append(f"element {element.get('label', '?')!r} is at {at!r}, "
                                  f"which is not [x, y] with both between 0.0 and 1.0. "
                                  f"Those look like pixels; divide by the image's width "
                                  f"and height, or omit `at` if you cannot place it")
                for entry in element.get("behaviour", []):
                    if not isinstance(entry, dict):
                        errors.append(f"element {element.get('label', '?')!r} has behaviour "
                                      f"entry {entry!r}, which is not an object with "
                                      f"modality, effect and evidence")
                        continue
                    for field in ("modality", "effect"):
                        if not entry.get(field):
                            errors.append(f"element {element.get('label', '?')!r} has a "
                                          f"behaviour entry with no {field!r}")
                    cited = entry.get("evidence") or []
                    bad = [c for c in cited if c not in allowed]
                    if bad:
                        # The whole point of the pass. An ID that is not in the
                        # evidence is either a different screen's transition or
                        # something that was never observed at all, and both read as
                        # a measurement once they are in the file.
                        known = " (that transition exists, but not from this screen)" \
                            if any(c in valid_ids for c in bad) else " (no such transition)"
                        errors.append(
                            f"element {element.get('label', '?')!r}, modality "
                            f"{entry.get('modality', '?')!r} cites {', '.join(bad)}"
                            f"{known}")
                    if not cited and not entry.get("hypothesis"):
                        errors.append(
                            f"element {element.get('label', '?')!r}, modality "
                            f"{entry.get('modality', '?')!r} cites no evidence, so it "
                            f"must set hypothesis to true")
            return errors

        print(f"[{index}/{len(screens)}] describing {screen['id']} "
              f"({len(images)} images, {len(mine)} transitions)")
        payload = call_tool_with_retry(
            client, model=model, system=ANNOTATE_SYSTEM, tools=[ANNOTATE_TOOL],
            tool_name="describe_screen", user_message=content, validate_fn=validate,
            max_tokens=ANNOTATE_MAX_TOKENS, cache_static_content=True)

        screen["name"] = payload["name"]
        screen["role"] = payload["role"]
        screen["purpose"] = payload["description"]
        screen["elements"] = [
            {
                "label": element["label"],
                "what": element["what"],
                "at": element.get("at"),
                "behaviour": {
                    entry["modality"]: {
                        "effect": entry["effect"],
                        "evidence": entry.get("evidence") or [],
                        "hypothesis": bool(entry.get("hypothesis")) or not entry.get("evidence"),
                    }
                    for entry in element.get("behaviour", [])
                },
            }
            for element in payload.get("elements", [])
        ]
        screen["notes"] = payload.get("notes", [])
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    observed = sum(1 for s in data["screens"] for e in s.get("elements", [])
                   for b in e["behaviour"].values() if not b["hypothesis"])
    guessed = sum(1 for s in data["screens"] for e in s.get("elements", [])
                  for b in e["behaviour"].values() if b["hypothesis"])
    data["session"]["annotated"] = {"screens": len(screens),
                                    "observed_claims": observed,
                                    "hypothesised_claims": guessed}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n{observed} behaviour claims backed by a transition, {guessed} hypothesised")
    return path


def main() -> None:
    readable_output()
    parser = argparse.ArgumentParser(description="Annotate a recon session's ontology.")
    parser.add_argument("out", help="a session directory containing ontology.json")
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=0, help="only the first N screens")
    args = parser.parse_args()

    out = Path(args.out)
    annotate(out, model=args.model, limit=args.limit)

    import recon
    data = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    print(f"wrote {recon.write_report(data, out)}")


if __name__ == "__main__":
    main()
