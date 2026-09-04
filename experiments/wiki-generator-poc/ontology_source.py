"""Turns a game-ontology pass directory into raw sources a wiki can be written
from - one source per screen, plus the navigation graph as a whole.

This is the adapter between two experiments that were built apart:
`game-ontology/recon.py` writes a map of a game it explored, and
`wiki-generator-poc/generate.py` writes wiki pages from raw sources. The map is
not shaped like a raw source - it is one 400KB JSON file, and a wiki generator
that iterates files would see it as a single source and flatten nine screens
into one page. What this module does is regroup it: a screen is a source.

Two rules govern everything here, and they are the whole reason the module
exists rather than the map being fed in as-is:

1. **The harness gets no voice.** Cell counts, settle times, match thresholds,
   screen ids, fractional coordinates and vetting bookkeeping are facts about
   how the game was explored, not facts about the game. None of them leave this
   module. A wiki page reading "514 of 576 cells held still" is a page about the
   test harness; the reader would learn nothing about the game from it.
2. **Actions are named the way a player would name them.** The map records
   `click:0.438,0.700`; a player would say "clicking SETTINGS". Resolving the
   one into the other is what turns a click-by-click log into a description of
   a game, and it is done here, deterministically, rather than being asked of a
   model that would have to guess.

Nothing in here calls a model. The output is plain dicts, so a caller can print
them and check what it would send before spending anything.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

# Refusal reasons that are the harness talking to itself rather than a judgement
# about the game. Everything else in blocked_actions is a real product-facing
# statement - "QUIT is currently highlighted, so Enter would close the game" is
# knowledge about the game, and it is the honest explanation for why what Enter
# does there is still unknown. These two are not: they say only that the
# harness had no ruling yet. Matched exactly, because a substring match would
# swallow a genuine reason that happens to quote one of them.
HARNESS_REFUSALS = frozenset({
    "no verdict for this action",
    "screen not vetted, so committing actions stay locked",
    "shown to the model, which returned no verdict for it",
})

# Phrases that mean a sentence is describing the exploration rather than the
# game. Refusal reasons are free prose written during the run, so some of them
# reason out loud in the harness's own terms - "at approximately y=0.90 and
# leftward x, this likely hit..." - and a reason that only makes sense against a
# coordinate grid tells a reader of the wiki nothing. Used to drop those, and by
# selftest_game_wiki.py to check no page body contains any of them.
#
# The coordinate pattern is deliberately restricted to values below one: every
# coordinate in the map is a fraction, while "obtain 2.000 points" is one of the
# game's own challenge names and must survive.
HARNESS_TALK = (
    r"\b0\.\d{2,}\b",
    r"\b[xy]\s*=\s*[\d.]",
    r"close-?ups?",
    r"\bcrops?\b",
    r"\bcells?\b",
    r"\bpixels?\b",
)


def speaks_harness(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in HARNESS_TALK)

# How a key's map name reads in a sentence a player would recognise. Anything
# not listed falls through as-is, so an unmapped key still produces a usable
# phrase rather than an exception.
KEY_NAMES = {
    "up": "the Up arrow", "down": "the Down arrow",
    "left": "the Left arrow", "right": "the Right arrow",
    "enter": "Enter", "esc": "Escape", "space": "Space", "tab": "Tab",
}

THIRDS = (("left", "centre", "right"), ("top", "middle", "bottom"))


def load(pass_dir: Path) -> dict:
    """Reads a pass directory's ontology.json. Kept separate from build_sources
    so a caller can hold the raw map for its own checks without re-reading."""
    return json.loads((pass_dir / "ontology.json").read_text(encoding="utf-8"))


def _distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _hit_radius(elements: list[dict]) -> float | None:
    """How close an action has to land to an element before we are willing to
    say it hit that element - the median distance between neighbouring elements
    on this screen.

    Derived from the screen's own layout rather than picked, because the right
    answer differs per screen by an order of magnitude: a five-entry main menu
    spaces its items ~0.09 apart, while a 22-element collection grid packs them
    far tighter, and one number cannot be both generous enough for the menu and
    strict enough for the grid.

    A full spacing rather than a fraction of one, because neither coordinate
    being compared is exact. The recorded point is where the harness aimed - a
    grid-cell centre found by sweeping for a reaction - not the element's own
    centre, and the element's position is a model's estimate from a screenshot.
    On Tile Tale's main menu those two disagree by 0.06 for a click that
    unambiguously opened Settings, which a half-spacing radius of 0.045 rejects.
    One spacing is where the nearest element genuinely stops being the obvious
    answer, since past it a neighbour is nearer to the midpoint than this one.

    None when the screen has fewer than two described elements: with nothing to
    measure spacing against there is no honest radius, and a screen with no
    elements has nothing to attribute an action to anyway.
    """
    points = [tuple(e["at"]) for e in elements if e.get("at")]
    if len(points) < 2:
        return None
    nearest = [min(_distance(p, q) for q in points if q != p) for p in points]
    nearest.sort()
    middle = len(nearest) // 2
    return nearest[middle] if len(nearest) % 2 else (nearest[middle - 1] + nearest[middle]) / 2


def _where(at) -> str:
    """A position said in words instead of coordinates - "the lower left", "the
    middle". Used when an action landed nowhere near a described element, so the
    page can still say where it happened without printing a fraction at a reader
    who has no grid to read it against."""
    if not at:
        return "the screen"
    column = THIRDS[0][min(int(at[0] * 3), 2)]
    row = THIRDS[1][min(int(at[1] * 3), 2)]
    if column == "centre" and row == "middle":
        return "the middle of the screen"
    if column == "centre":
        return f"the {row} of the screen"
    return f"the {row} {column}" if row != "middle" else f"the {column} side"


def _element_at(at, elements: list[dict], radius: float | None) -> str | None:
    if not at or radius is None:
        return None
    labelled = [e for e in elements if e.get("at") and e.get("label")]
    if not labelled:
        return None
    nearest = min(labelled, key=lambda e: _distance(at, tuple(e["at"])))
    return nearest["label"] if _distance(at, tuple(nearest["at"])) <= radius else None


def phrase(action: dict, elements: list[dict], radius: float | None,
           rename=None) -> str:
    """The action as a player would describe doing it. This is the single place
    a coordinate is allowed to turn into a name; everything downstream sees only
    the phrase.

    Only clicks and hovers are named after an element. A player aims a click at
    a control, so "clicking SETTINGS" is what they did; nobody aims the wheel or
    a drag at a menu entry, and the harness turns the wheel at the middle of the
    screen regardless of what happens to sit there - saying "scrolling over New
    Game" would invent an intent that neither the player nor the harness had.

    `rename` maps the label the resolved element happened to be described by onto
    the one name its place calls it. Without it, one act comes out as several:
    the same click on the same settings row read as "clicking SCREEN: FULLSCREEN",
    "clicking Screen mode setting" and "clicking Screen: Fullscreen menu item",
    because each visit described that row afresh.
    """
    kind = action.get("kind")
    at = action.get("at")
    label = _element_at(at, elements, radius)
    if label and rename:
        label = rename(label)
    target = label or _where(at)

    if kind == "key":
        return f"pressing {KEY_NAMES.get(action.get('key', ''), action.get('key', 'a key'))}"
    if kind == "hover":
        return f"pointing at {target}" if label else f"moving the cursor to {target}"
    if kind == "click":
        return f"clicking {target}"
    if kind == "scroll":
        # notches carries the direction in its sign; its magnitude is how hard
        # the harness turned the wheel, which is a fact about the harness.
        notches = action.get("notches") or 0
        return "scrolling the wheel " + ("up" if notches > 0 else "down" if notches < 0 else "either way")
    if kind == "drag":
        end = action.get("to")
        if end and at:
            way = ("right" if end[0] > at[0] else "left" if end[0] < at[0]
                   else "down" if end[1] > at[1] else "up")
            return f"dragging {way} across the screen"
        return "dragging across the screen"
    return f"{kind} at {target}"


def _screen_name(screen: dict) -> str:
    """A screen's own name, or an honest placeholder. sc04 in the Tile Tale map
    has name None - it was reached but never described, and saying so is more
    use to a reader than leaving a hole in the navigation graph."""
    return screen.get("name") or "an unidentified screen"


def _stem(label: str) -> str:
    """A control's identity with its current value stripped off: "MUSIC: 20%"
    and "MUSIC: OFF" are the same control showing different things."""
    return label.split(":")[0].strip() or label


def _value(label: str) -> str:
    """What a control was holding, if the label recorded it: "MUSIC: 20%" ->
    "20%". Empty when the label carries no value, which is not the same as the
    control having none - only that this description did not say."""
    _, colon, rest = label.partition(":")
    if not colon:
        return ""
    return " ".join(w for w in rest.strip().split() if w.lower() not in ROLE_WORDS)


def _one_spelling(values: list[str]) -> list[str]:
    """Collapses values that differ only in case. "FULLSCREEN" and "Fullscreen"
    are one setting written by two describers, and reporting them as two states
    of the control would be reporting the wiki's own inconsistency as behaviour
    the game exhibits. The spelling kept is the commonest."""
    by_meaning: dict[str, list[str]] = {}
    for value in values:
        by_meaning.setdefault(value.lower(), []).append(value)
    return sorted(min(sorted(set(group)), key=lambda v: (-group.count(v), v))
                  for group in by_meaning.values())


# Words that say what *kind* of thing a label names rather than which thing it
# is. Stripping them is what lets one screen be recognised across several visits:
# the same settings row came back as "Music: OFF menu item", "Music volume
# setting", "Music menu item" and "MUSIC: OFF" on four of them, because a
# fresh description was written each time and nothing holds the wording steady.
#
# Generic interface vocabulary, not this game's - the same reason KEY_NAMES and
# THIRDS are allowed to be written down here. Nothing in the list could only
# appear in one game, and the cost of not having it is six near-identical
# settings pages, each looking like a separate screen a player never saw.
ROLE_WORDS = frozenset({
    "menu", "item", "items", "button", "buttons", "setting", "toggle", "option", "options",
    "action", "control", "controls", "entry", "entries", "mode", "volume", "slider", "field",
    # Decoration is described more loosely than anything else, because nothing
    # about it matters to the describer: one game's title graphic came back as
    # "Tile Tale logo", "Tile Tale logo banner", "Tile Tale banner", "TILE TALE
    # logo" and "TILE TALE" across six visits to one screen, and listing it five
    # times would put five things on the page that a player sees as one.
    "logo", "banner", "title",
})

# The same, for a screen's name: "Settings Menu", "settings menu" and "Settings
# Menu (Tile Tale)" are one screen named three ways. The parenthetical goes too -
# a describer appending the game's own name to a screen name is saying nothing
# about which screen it is.
NAME_ROLE_WORDS = frozenset({"menu", "screen", "page", "view", "window", "dialog", "overlay"})


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9%]+", text.lower()) if w]


def _control_key(label: str) -> str:
    """What two descriptions of the same control agree on. Empty when a label is
    nothing but role words ("Menu item"), in which case it identifies nothing and
    is not allowed to make two screens look alike."""
    return " ".join(w for w in _words(_stem(label)) if w not in ROLE_WORDS)


def _name_key(name: str) -> str:
    base = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    kept = [w for w in _words(base) if w not in NAME_ROLE_WORDS]
    return " ".join(kept) or " ".join(_words(base)) or name.strip().lower()


def _identity_controls(screen: dict) -> set[str]:
    """The controls a screen can be recognised by.

    Only elements the describer gave a position to. The ones without a position
    are not things on the screen at all - they are notes about the keyboard
    ("Menu focus - key:down"), written on some visits and not others, so counting
    them would make one screen look unlike itself.
    """
    return {key for element in (screen.get("elements") or [])
            if element.get("label") and element.get("at")
            for key in [_control_key(element["label"])] if key}


def places(screens: dict[str, dict]) -> list[dict]:
    """Groups screen ids into the places a *player* would count.

    The Tile Tale map holds four screens named "settings menu". That is not four
    settings screens: the harness identifies a screen by its pixels, so once the
    player turns dark mode on, the settings screen no longer looks like the one
    the harness already knew and becomes a new screen. Their element labels say
    so outright - MUSIC: OFF against MUSIC: 20%, DARK MODE: OFF against DARK
    MODE: ON, and otherwise the same seven controls in the same order.

    So the grouping rule is evidence, not a guess: the same name, *and* a control
    the two screens can be shown to have in common. Two screens that merely share
    a name are left apart, because a shared name over nothing in common is as
    likely to mean the namer was being coarse.

    One shared control and not the identical set, which an earlier version
    required. Six visits to Tile Tale's settings screen produced six control
    lists that no two of which matched exactly: each visit was described afresh,
    so "Music volume setting", "Music menu item" and "MUSIC: OFF" are the same
    row written three ways, and some visits noticed the decorative banner or the
    background while others did not. Demanding an exact match let the describer's
    inconsistency decide how many screens the game has, which produced six
    settings pages. Demanding one shared control after the wording is normalised
    away asks for the least evidence that is still evidence, and it is the reader
    who is protected by the weaker rule rather than the stricter one: over-merging
    shows up on the page as a place with contradictory controls, while
    under-merging quietly produces several confident pages about one screen.

    Leaving them split would also render a settings state change as travel
    between screens - "clicking BACK opens the settings menu". Grouped, the
    differing values become what they are: the states this one screen was seen in.
    """
    by_name: dict[str, list[str]] = {}
    for sid, screen in screens.items():
        by_name.setdefault(_name_key(_screen_name(screen)), []).append(sid)

    grouped: list[dict] = []
    for sids in by_name.values():
        # Transitive within a name: if A shares a control with B and B with C,
        # all three are one screen. Nothing here can join across names.
        merged: list[dict] = []
        for sid in sorted(sids):
            controls = _identity_controls(screens[sid])
            touching = [g for g in merged if controls & g["controls"]] if controls else []
            joined = {"ids": [sid], "controls": set(controls)}
            for group in touching:
                joined["ids"] += group["ids"]
                joined["controls"] |= group["controls"]
                merged.remove(group)
            merged.append(joined)
        grouped += merged

    # A name shared by groups with nothing in common still has to produce
    # distinct pages, so the later ones are marked. A crutch, and one that should
    # be rare enough to notice: it means the exploration named two different
    # screens the same thing, which is worth a reader's suspicion.
    seen_names: dict[str, int] = {}
    out = []
    for group in grouped:
        ids = sorted(group["ids"])
        # The name the most visits gave it, shortest to break a tie - the longer
        # forms are the ones carrying an aside ("Settings Menu (Tile Tale)").
        candidates = [_screen_name(screens[sid]) for sid in ids]
        name = min(sorted(set(candidates)), key=lambda n: (-candidates.count(n), len(n)))
        seen_names[name] = seen_names.get(name, 0) + 1
        label = name if seen_names[name] == 1 else f"{name} (a second screen with the same name)"
        out.append({"name": label, "ids": ids, "controls": group["controls"]})
    return out


class Reader:
    """Holds one pass's map and answers questions about it in the game's own
    terms. A class rather than functions because every answer needs the same
    three derived things - the places, which screen id belongs to which place,
    and each screen's hit radius - and recomputing them per call would make the
    grouping rule easy to apply in one place and forget in another.
    """

    def __init__(self, data: dict):
        self.data = data
        self.screens = {s["id"]: s for s in data["screens"]}
        self.radii = {sid: _hit_radius(s.get("elements") or []) for sid, s in self.screens.items()}
        self.places = places(self.screens)
        self.place_of = {sid: place["name"] for place in self.places for sid in place["ids"]}
        self.spoken_label = self._spoken_labels()
        # Counted, not silently swallowed: how many refusal reasons were dropped
        # for talking in the harness's terms is the caller's business, since a
        # dropped reason is a known unknown the wiki now cannot mention.
        self.warnings_dropped = 0

    def _controls_of(self, sid: str) -> dict[str, dict[str, set[str]]]:
        """control key -> which screens described it -> the labels they used."""
        found: dict[str, dict[str, set[str]]] = {}
        for element in self.screens[sid].get("elements") or []:
            label = element.get("label")
            if label:
                found.setdefault(_control_key(label) or _stem(label), {}).setdefault(sid, set()).add(label)
        return found

    def _spoken_labels(self) -> dict[str, dict[str, str]]:
        """Per place, the one name to call each control that several visits named
        differently.

        Only those controls. A control described once keeps its full label, values
        and all, because there the extra words are the content: the collection
        screen lists fourteen separate goals as "challenge: obtain 250 points" and
        friends, and shortening each to the name they share would leave the page
        saying "challenge" fourteen times.

        The name chosen is the shortest of the value-stripped forms, which is the
        one closest to what the screen itself reads - "MUSIC", not "Music volume
        setting".
        """
        out = {}
        for place in self.places:
            seen: dict[str, dict[str, set[str]]] = {}
            for sid in place["ids"]:
                for key, per_screen in self._controls_of(sid).items():
                    seen.setdefault(key, {}).update(per_screen)
            names = {}
            for key, per_screen in seen.items():
                labels = {label for group in per_screen.values() for label in group}
                if len(labels) > 1 and len(per_screen) > 1:
                    names[key] = min(sorted({_stem(label) for label in labels}), key=len)
            out[place["name"]] = names
        return out

    def _rename(self, sid: str):
        names = self.spoken_label.get(self.place_of.get(sid), {})
        return lambda label: names.get(_control_key(label) or _stem(label), label)

    def said(self, sid: str, action: dict) -> str:
        screen = self.screens.get(sid, {})
        return phrase(action, screen.get("elements") or [], self.radii.get(sid), self._rename(sid))

    def _routes(self) -> dict[tuple[str, str, str], int]:
        """Every observed move between two places, counted.

        Counted rather than just listed because several probes produce the same
        sentence, and because how often a route was walked is the reader's only
        guide to how much weight it carries: a route seen once sitting next to
        one seen nine times is where a misread observation shows up.

        A transition the map calls a screen change but that stays inside one
        place is dropped here and picked up as an in-place change instead - that
        is the whole point of grouping.
        """
        counted: dict[tuple[str, str, str], int] = {}
        for transition in self.data["transitions"]:
            if transition["effect"] != "screen":
                continue
            here, there = self.place_of.get(transition["from"]), self.place_of.get(transition["to"])
            if here is None or there is None or here == there:
                continue
            key = (here, self.said(transition["from"], transition["action"]), there)
            counted[key] = counted.get(key, 0) + (transition.get("times_taken") or 1)
        return counted

    def sources(self) -> list[dict]:
        """One source per place, holding only game-facing material.

        Each place's transitions are split three ways because a reader asks
        three separate questions: what happens here without leaving, where this
        leads, and how you get here. The map stores them as one flat list keyed
        on screen ids.
        """
        routes = self._routes()
        self.warnings_dropped = 0  # idempotent: graph() calls this too
        out = []
        for place in self.places:
            ids, name = place["ids"], place["name"]
            warnings, clicked = set(), set()
            # spoken action -> the outcomes it was seen having. A set, because
            # one action can honestly have had more than one: a place made of
            # several screens was in several states, and the Up arrow moving a
            # selection on one of them while doing nothing on another is a fact
            # about the game, not a contradiction to be resolved by picking one.
            outcomes: dict[str, set[str]] = {}
            # control key -> which screens showed it -> the exact labels they showed
            seen: dict[str, dict[str, set[str]]] = {}
            described: dict[str, str] = {}
            order: list[str] = []

            for sid in ids:
                for element in self.screens[sid].get("elements") or []:
                    label = element.get("label", "")
                    # No position means it is not a thing on the screen. What the
                    # describer put there instead is a note about the keyboard -
                    # "Menu focus - key:down", "key:up (global)" - written on some
                    # visits and not others, and a player looking at the screen
                    # sees no such object. What those notes say about the keys is
                    # not lost: it arrives through the transitions instead, as
                    # what actually happened when the key was pressed.
                    if not label or not element.get("at"):
                        continue
                    key = _control_key(label) or _stem(label)
                    seen.setdefault(key, {}).setdefault(sid, set()).add(label)
                    described.setdefault(label, element.get("what", ""))
                    if key not in order:
                        order.append(key)
                for blocked in self.data.get("blocked_actions", []):
                    why = blocked.get("why", "")
                    if not blocked.get("what", "").startswith((f"{sid} ", f"{sid}-v")):
                        continue
                    if why in HARNESS_REFUSALS:
                        continue
                    if speaks_harness(why):
                        self.warnings_dropped += 1
                        continue
                    warnings.add(why)

            # A colon in a label only means "control: its current value" when the
            # same control was seen holding different values on *different*
            # screens - that is what a toggle looks like once the harness has
            # split it in two. Within one screen a colon means nothing of the
            # kind: the collection screen lists fourteen separate goals as
            # "challenge: obtain 250 points" and friends, and merging those into
            # one control called "challenge" would delete thirteen of them.
            elements, states, key_of = [], {}, {}
            for key in order:
                per_screen = seen[key]
                labels = sorted({label for group in per_screen.values() for label in group})
                if len(labels) > 1 and len(per_screen) > 1:
                    # One control, described differently on different visits.
                    shown = self.spoken_label[name][key]
                    elements.append({"label": shown, "what": described[labels[0]]})
                    key_of[shown] = key
                    # The values it was seen holding - not the labels. A control
                    # written up four ways was not seen in four states; saying so
                    # would report the describer's vocabulary as the game's
                    # behaviour. Two values or more, or there is no change to show.
                    values = _one_spelling([v for label in labels if (v := _value(label))])
                    if len(values) > 1:
                        states[shown] = values
                else:
                    for label in labels:
                        elements.append({"label": label, "what": described[label]})
                        key_of[label] = key

            reached: dict[tuple[str, str], int] = {}
            leads: dict[tuple[str, str], int] = {}
            for (here, by, there), times in routes.items():
                if here == name:
                    leads[(by, there)] = leads.get((by, there), 0) + times
                if there == name:
                    reached[(here, by)] = reached.get((here, by), 0) + times

            for transition in self.data["transitions"]:
                sid = transition["from"]
                if sid not in ids:
                    continue
                action = transition["action"]
                spoken = self.said(sid, action)
                if action["kind"] == "click":
                    # Clicks alone mark a control as tried: activating a control
                    # is what a click is for, and pointing at a menu entry tells
                    # you nothing about what choosing it does.
                    label = _element_at(action.get("at"), self.screens[sid].get("elements") or [], self.radii.get(sid))
                    if label:
                        # By normalised identity, not by label. The control that
                        # was clicked may be listed under another visit's wording
                        # of it, and a control reported as never activated when it
                        # was activated is the kind of error that sends a reader
                        # to test something already known.
                        clicked.add(_control_key(label) or _stem(label))
                if transition["effect"] == "none":
                    outcomes.setdefault(spoken, set()).add("nothing")
                elif self.place_of.get(transition["to"]) == name:
                    outcomes.setdefault(spoken, set()).add("changes")

            here = []
            for spoken, seen_outcomes in sorted(outcomes.items()):
                if seen_outcomes == {"changes"}:
                    here.append(f"{spoken} changes what is shown, without leaving")
                elif seen_outcomes == {"nothing"}:
                    here.append(f"{spoken} does nothing visible")
                else:
                    here.append(f"{spoken} sometimes changes what is shown and sometimes does nothing, "
                                f"depending on the state this place is in")

            out.append({
                "name": name,
                "screen_ids": ids,
                "purpose": next((self.screens[s].get("purpose") for s in ids if self.screens[s].get("purpose")), ""),
                "image": next((self.screens[s].get("image") for s in ids if self.screens[s].get("image")), ""),
                "described": any(self.screens[s].get("name") for s in ids),
                # Whether this place was ever seen looking different from itself.
                # A flag and not the count, because the count is a fact about
                # the exploration - ten appearances rather than two says the
                # explorer poked this place harder, not that the game has more
                # to show - and a number in the payload is a number that ends up
                # quoted in the prose as though it were about the game.
                "appearance_varies": sum(len(self.screens[s].get("variants") or []) for s in ids) > 1,
                "controls": elements,
                "controls_with_state": states,
                "never_clicked": sorted(e["label"] for e in elements
                                        if key_of.get(e["label"], e["label"]) not in clicked),
                "what_actions_do": here,
                "leads_to": [{"by": by, "to": to, "seen": n} for (by, to), n in sorted(leads.items())],
                "reached_by": [{"from": f, "by": by, "seen": n} for (f, by), n in sorted(reached.items())],
                "warnings": sorted(warnings),
            })
        return out

    def graph(self) -> dict:
        """The navigation model as a whole - the input for pages about rules
        rather than about places. A rule only exists across screens ("Escape
        backs out everywhere", "the board is only reachable through New Game"),
        so no per-screen pass can find one however good it is.
        """
        routes = self._routes()
        edges = [{"from": f, "by": by, "to": t, "seen": n} for (f, by, t), n in sorted(routes.items())]

        # What every place answers to, laid side by side: a rule about a key
        # reads as a column that says the same thing all the way down, and an
        # exception is the one row that doesn't.
        responses: dict[str, dict[str, str]] = {}
        for place in self.places:
            per_place = responses.setdefault(place["name"], {})
            for transition in self.data["transitions"]:
                if transition["from"] not in place["ids"] or transition["action"]["kind"] != "key":
                    continue
                key = KEY_NAMES.get(transition["action"].get("key", ""), transition["action"].get("key", ""))
                there = self.place_of.get(transition["to"])
                per_place[key] = ("leaves for " + there if transition["effect"] == "screen" and there != place["name"]
                                  else "changes what is shown" if transition["effect"] != "none" else "does nothing")

        names = [p["name"] for p in self.places]
        entered = {e["to"] for e in edges}
        left = {e["from"] for e in edges}
        return {
            "places": [{"name": p["name"], "purpose": s["purpose"], "described": s["described"],
                        "controls": [c["label"] for c in s["controls"]]}
                       for p, s in zip(self.places, self.sources())],
            "routes": edges,
            "key_responses": responses,
            "no_way_out_observed": sorted(n for n in names if n not in left),
            "never_arrived_at": sorted(n for n in names if n not in entered),
            "screens_merged": {p["name"]: p["ids"] for p in self.places if len(p["ids"]) > 1},
        }
