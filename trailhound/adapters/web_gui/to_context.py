"""Spoor's map, as screens in the product's context, for the oracle to build on (#311).

Spoor's job is to tell the engine about the product. Its converted map (from_spoor)
knows every screen it reached: the route, the heading, every control and field, and
where each action leads. This turns that into the product's screens, in the same shape
as a wiki Entity page (AGENTS.md's product layer: features and facts), and writes them
into the product's context (`context_<product>.json`, under "screens"). The seeder
builds oracle ideas from them next to the wiki's pages, and the oracle ranks ideas on
screens it knows how to reach higher, with the route to start from.

Why the context and not the wiki: the wiki is the curated layer, and a page a person
wrote is never overwritten. Generated screens change with every map, and CI can't
commit them, so they live where the engine learns: the context.

Screens that share a route and a control set are one screen: Juice Shop's twelve
product dialogs differ only in their heading, so they're one "product dialog" with
twelve examples. Features come from the controls (a password field, Add to Basket, a
paging control), using only tags from the vocabulary. Facts say only what the map saw.

    python -m trailhound.adapters.web_gui.to_context --map runs/ci/map.json --product juice-shop
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from trailhound.adapters.web_gui import reference as ref_mod
from trailhound.ontology.oracle_creator import context_path, load_context, load_vocabulary

# Tags a screen gets from what's on it: (feature tag, a pattern on "role:name" keys).
# Names are lowercase. Only tags from the vocabulary's feature list are used.
_FEATURE_RULES = (
    ("text-field", r"^(textbox|searchbox):"),
    ("input-field", r"^(textbox|searchbox|combobox|checkbox|radio|slider):"),
    ("search", r"^searchbox:|search"),
    ("login", r"\blog ?in\b|sign ?in"),
    ("registration", r"register|sign ?up|repeat password|security question"),
    ("password-reset", r"forgot (your )?password|reset password"),
    ("account", r"account|profile"),
    ("cart", r"basket|cart|checkout"),
    ("payment", r"\bpay|payment|card number|credit card|wallet"),
    ("money", r"price|total|¤|€|\$|wallet|deposit|withdraw"),
    ("numeric-field", r"quantity|amount|number"),
    ("email", r"e-?mail"),
    ("list-paging", r"next page|previous page|items per page"),
    ("menu", r"^menuitem:|menu"),
    ("dialog", r"^dialog:|close dialog"),
    ("localization", r"language"),
    ("file-upload", r"upload|choose file"),
    ("table", r"^(table|row|cell|columnheader):"),
    ("link", r"^link:"),
    ("navigation", r"^link:|back to homepage|sidenav"),
    ("date-time", r"\bdate\b|\btime\b"),
)
_FIELD_ROLES = ref_mod.FIELD_ROLES
_SUBMITS = re.compile(r"\b(submit|send|save|register|log ?in|sign ?in|checkout|pay|place order|confirm)\b")
_MAX_LISTED = 8
_MAX_NAME = 40
_MAX_LEADS_TO = 6
# States on one route that share this much of their controls are one screen.
_SAME_SCREEN = 0.8
# A control on this share of all states is the toolbar's, not a screen's.
_EVERYWHERE = 0.8


def _route(url: str) -> str:
    """A screen's route: the path and the fragment, without a query in either, the way a
    test's start is an area (#328). "/#/search?q=apple" is "/#/search"."""
    parts = urlsplit(url or "")
    return (parts.path or "/") + (f"#{parts.fragment.split('?', 1)[0]}" if parts.fragment else "")


def _heading(state: dict) -> str:
    parts = (state.get("signature") or "").split("|")
    return parts[2].split(";")[0] if len(parts) > 2 and parts[2] else ""


def _controls(state: dict) -> set[str]:
    """A state's controls, with numbers taken out of names ("reviews(1)" and "reviews(2)"
    are the same control)."""
    parts = (state.get("signature") or "").split("|")
    return {re.sub(r"\d+", "#", c) for c in (parts[1].split(";") if len(parts) > 1 else []) if c}


def _similar(a: set[str], b: set[str]) -> bool:
    return len(a & b) >= _SAME_SCREEN * max(len(a | b), 1)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "screen"


def _clean(heading: str) -> str:
    return re.sub(r"\s*\(?<(email|id)>\)?", "", heading).strip()


def _name(text: str) -> str:
    """A control's name as a fact or a title shows it: no emails or generated ids, and
    short (a menu's name can be all of its text)."""
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "", text or "")
    text = " ".join(text.split())
    return text if len(text) <= _MAX_NAME else text[:_MAX_NAME].rsplit(" ", 1)[0] + "..."


def _tokens(elements) -> list[str]:
    return sorted({ref_mod.control_token(e.get("role", ""), e.get("name", "")) for e in elements})


def features_of(elements: list[dict], headings: list[str], allowed: set[str]) -> list[str]:
    keys = [f"{e.get('role', '')}:{(e.get('name') or '').lower()}" for e in elements] + \
           [f"heading:{h.lower()}" for h in headings]
    found = [tag for tag, pattern in _FEATURE_RULES if any(re.search(pattern, k) for k in keys)]
    fields = [e for e in elements if e.get("role") in _FIELD_ROLES]
    if fields and any(_SUBMITS.search((e.get("name") or "").lower()) for e in elements):
        found.append("form")
    return [t for t in dict.fromkeys(found) if t in allowed]


def screens_from_map(reference: ref_mod.Reference, product: str, source: str) -> list[dict]:
    """The map's states as the product's screens: Entity-shaped dicts with a route, a
    path to reach them, features, facts and examples. States on one route whose
    controls mostly overlap are one screen."""
    allowed = set(load_vocabulary()["tags"]["feature"])
    states = [s for s in reference.states if s["id"] in reference._paths]
    groups: list[dict] = []
    for state in states:
        route, controls = _route(state.get("url", "")), _controls(state)
        group = next((g for g in groups if g["route"] == route and _similar(g["controls"], controls)), None)
        if group is None:
            groups.append({"route": route, "controls": controls, "states": [state]})
        else:
            group["states"].append(state)
    # The toolbar's controls are on nearly every screen: they say nothing about a screen,
    # so they only count on the start screen.
    counts: dict[str, int] = {}
    for s in states:
        for c in _controls(s):
            counts[c] = counts.get(c, 0) + 1
    everywhere = {c for c, n in counts.items() if n >= _EVERYWHERE * len(states)}
    entry = reference.entry()
    title_of: dict[str, str] = {}
    screens, slugs = [], set()
    for g in groups:
        headings = [h for h in dict.fromkeys(_clean(_heading(s)) for s in g["states"]) if h]
        is_entry = any(s["id"] == entry for s in g["states"])
        elements = [e for e in g["states"][0].get("elements", []) if e.get("role") not in (None, "", "generic")]
        own = elements if is_entry else [
            e for e in elements if re.sub(r"\d+", "#", f"{e['role']}:{(e.get('name') or '').lower()}") not in everywhere]
        place = "start page" if g["route"] in ("/", "/#/") else g["route"]
        # No heading of its own: named after the step that reaches it (a menu opened, say).
        path = reference._paths[g["states"][0]["id"]]
        step = _name(path[-1].get("name", "")) if path else ""
        if is_entry:
            first = place                     # the start, whatever banner sits on it
        else:
            first = headings[0] if headings else (f"{place}, after {step}" if step else place)
        title = f"{product} {first}" + (f" and {len(headings) - 1} more like it" if len(headings) > 1 else "")
        slug, n = f"screen-{_slug(first)}", 2
        while slug in slugs:
            slug, n = f"screen-{_slug(first)}-{n}", n + 1
        slugs.add(slug)
        for s in g["states"]:
            title_of[s["id"]] = title
        on_this = own
        screens.append({"slug": slug, "title": title, "route": g["route"], "states": [s["id"] for s in g["states"]],
                        "path": reference._paths[g["states"][0]["id"]], "examples": headings,
                        "features": features_of(on_this, headings, allowed), "elements": on_this,
                        # Coverage tokens (#328): what a run can try here, its fields, and
                        # what changes data, so the context can say what was never tried.
                        "controls": _tokens(on_this),
                        "fields": _tokens(e for e in on_this if e.get("role") in _FIELD_ROLES),
                        "changes_data": _tokens(e for e in on_this if e.get("changes_data")),
                        "generated": True, "source": source})
    for screen in screens:
        screen["facts"] = _facts(screen, reference, title_of)
        del screen["elements"]
    return screens


def _facts(screen: dict, reference: ref_mod.Reference, title_of: dict[str, str]) -> list[dict]:
    """Only what the map saw: the screen's fields, what changes data there, where its
    controls lead, and the other screens like it."""
    facts = []
    fields = list(dict.fromkeys(_name(e.get("name")) for e in screen["elements"]
                                if e.get("role") in _FIELD_ROLES and _name(e.get("name"))))
    if fields:
        facts.append(f"{screen['title']} has the fields {', '.join(fields[:_MAX_LISTED])}.")
    changing = list(dict.fromkeys(_name(e.get("name")) for e in screen["elements"]
                                  if e.get("changes_data") and _name(e.get("name"))))
    if changing:
        facts.append(f"On {screen['title']}, these change data: {', '.join(changing[:_MAX_LISTED])}.")
    leads = []
    for t in reference.transitions:
        if t.get("source") in screen["states"] and title_of.get(t.get("dest")) not in (None, screen["title"]):
            control = _name(t["action"]["element_key"].split(":", 1)[-1]) or t["action"]["element_key"]
            leads.append(f"{control} on {screen['title']} leads to {title_of[t['dest']]}.")
    facts += list(dict.fromkeys(leads))[:_MAX_LEADS_TO]
    if len(screen["examples"]) > 1:
        facts.append(f"{screen['title']} is one screen shown for: {', '.join(screen['examples'][:_MAX_LISTED])}.")
    return [{"id": f"G{i}", "kind": "shown", "text": text, "source": screen["source"]}
            for i, text in enumerate(facts, start=1)]


def write(product: str, screens: list[dict]) -> Path:
    """Replace the product's generated screens in its context; everything else in the
    context (results, discoveries, objections) stays."""
    context = load_context(product)
    context["screens"] = screens
    path = context_path(product)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a converted Spoor map into a product's context as screens (#311).")
    ap.add_argument("--map", required=True, help="the converted map, from_spoor's --out")
    ap.add_argument("--product", required=True, help="the product's slug, e.g. juice-shop")
    args = ap.parse_args()
    reference = ref_mod.load(args.map)
    source = f"spoor-map {Path(args.map).as_posix()} {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    screens = screens_from_map(reference, args.product, source)
    path = write(args.product, screens)
    print(f"Wrote {len(screens)} screen(s) from {len(reference.states)} state(s) into {path}:")
    for s in screens:
        print(f"  {s['title']} - route {s['route']} - {', '.join(s['features']) or 'no features'} - {len(s['facts'])} fact(s)")


if __name__ == "__main__":
    main()
