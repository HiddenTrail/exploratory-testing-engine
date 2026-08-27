"""The intelligence half: look at what recon collected and say what it means.

Two jobs, deliberately separate because they answer to different pressures.

**Vetting** runs inside the loop, once per newly discovered screen, and exists to
decide what the explorer is allowed to press. It is a safety gate, so it is small,
fast, and biased: `SAFETY_BRIEF` tells the model that the two ways of being wrong do
not cost the same, and that uncertainty resolves toward "dangerous".

**Annotation** runs afterwards over the finished graph and writes the ontology proper
- names, roles, and for each element what it does *per input modality*, since
"clicked" and "scrolled to with the keyboard" are different behaviours of the same
control and a description that merges them has lost the thing worth knowing.

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
You must return a verdict for every action you are given, using the exact action_id
strings supplied.
"""

ANNOTATE_SYSTEM = """\
You are writing the ontology of a video game's user interface from evidence gathered
by an automated explorer. You get one screen at a time: images of how it looked, and
the complete list of transitions observed from it - which input was sent, and whether
it changed nothing, changed the screen's appearance, or moved to a different screen.

Describe each interactive element you can identify, and for each one record its
behaviour SEPARATELY PER INPUT MODALITY. This matters more than anything else in the
task: a control reached by keyboard and a control reached by clicking are different
behaviours of the same thing, and a game may respond to one and ignore the other. Use
modality strings like "click", "hover", "key:down", "key:enter".

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
            "name": {"type": "string"},
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
                        "at": {"type": "array", "items": {"type": "number"}},
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
    """A callable for `Recon`: (image path, screen, candidate actions) -> verdict dict.

    Built as a closure so the client is constructed once for the session rather than
    per screen, and so `recon.py` can be handed a plain callable and stay unaware of
    which provider is behind it - or whether there is one at all."""
    client = client or build_client()
    model = model or default_model()

    def vet(image_path: Path, screen, variant, candidates) -> dict:
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
            {"type": "text", "text":
                f"Rule on each of these candidate actions:\n{listing}\n\n"
                f"Return a verdict for every action_id above, exactly as written, and "
                f"report what is currently selected."},
        ]

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
        content.append({"type": "text", "text":
                        "\nDescribe this screen and its elements. Cite only these "
                        f"transition IDs: {', '.join(sorted(mine)) or '(none available)'}. "
                        "Any behaviour you cannot support with one of them must set "
                        "hypothesis to true."})

        def validate(payload: dict, allowed: set[str] = mine) -> list[str]:
            errors = []
            for element in payload.get("elements", []):
                for entry in element.get("behaviour", []):
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
