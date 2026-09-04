"""Writes a wiki about a *game* from a game-ontology pass directory.

`generate.py` proves the wiki mechanics on text sources - one file in, one
Source Summary out. This is the same mechanics pointed at the other experiment's
output, and the difference is entirely in what counts as a source: not a file,
but a *place in the game*. `ontology_source.py` does that regrouping and strips
the harness's voice out; everything here is calls and rendering.

Three passes, all tool-forced (the call->validate->retry shape from
`engine/client.py`, so this authenticates the same way the exploration did -
Bedrock or a key, whichever the .env says):

  1. One call per place -> wiki/entities/<place>.md (an Entity page, kind
     `screen`). A place is a thing the rest of the wiki refers to repeatedly,
     which is what AGENTS.md says an Entity page is for.
  2. One call over the navigation graph -> wiki/concepts/<rule>.md, one Quality
     Concept page per rule. A rule ("Escape backs out", "nothing observed ever
     returned from settings") only exists across places, so it cannot come out
     of the per-place pass however good that pass is.
  3. One call over the results of both -> wiki/overview.md.

Facts stay in Python. Where a page states something the map already knows for
certain - which routes lead out of a place, how you get in, which controls were
never clicked - it is rendered from the map, not asked of the model. The model
is asked only for prose and for judgement about what matters. Same
"structured call, deterministic render" split as `generate.py` and
`engine/report.py`, applied to the boundary between fact and interpretation as
well as to markdown.

No page gets a `verified:` stamp. Nobody has confirmed any of this against the
game, and per AGENTS.md the absence of the field is what says so.

Run:
  py generate_game_wiki.py --pass-dir "../game-ontology/out/<run>/pass5" --dry-run
  py generate_game_wiki.py --pass-dir "../game-ontology/out/<run>/pass5"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ontology_source
from generate import (append_log, ensure_workspace, git_user, now_iso, rebuild_index,
                      repo_relative, slugify)

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine.client import build_client, call_tool_with_retry, default_model, summarize_usage  # noqa: E402

# The wiki says a person wrote it only when a person did. These pages are
# written by this script from a model's output, so the actor is the automation -
# AGENTS.md's `process:<id>` form. git_user() is still read, for the log.
AUTHOR = "process:wiki-from-ontology"

NO_INVENTION = (
    "Everything you are given was observed by automatically exploring the running game. "
    "Write about the GAME as a player would find it. Never mention screens by internal id, "
    "coordinates, pixels, grids, thresholds, probes, or the exploration itself - a reader wants "
    "to know how the game works, not how it was looked at. State nothing the given material does "
    "not support: where it is silent, say the thing is unknown rather than guessing. Where a "
    "route or effect was seen only once (\"seen: 1\"), say it was seen once rather than stating it "
    "as settled - a single observation of something surprising is as likely to be a misreading. "
    "A control's description may mention which entry happened to be highlighted at the moment it "
    "was looked at; that is a passing detail, not a property of the control. Never state how many "
    "times something was seen or how many appearances it had, in digits or in words, in the body or "
    "in the one-line description - that measures the exploration, not the game; use it to judge how "
    "sure to sound, and nothing else. \"Seen once\" is the sole exception, because it is a warning "
    "rather than a measurement."
)

# A place the exploration never described gets its title and description written
# here rather than by the model. Asked for a title, a model will supply a good
# one - "Tile Slide Overlay" - and a plausible name for something nobody
# identified is the most damaging thing this pipeline can produce: the page body
# hedges honestly, but the title and the one-line description are what the index
# and the overview quote, and they quote them as settled. The body still holds
# the model's guesses about what the place might be, hedged, where they belong.
UNNAMED_TITLE = "Unidentified screen"
UNNAMED_DESCRIPTION = ("A screen the exploration reached but never identified; what it is and what "
                       "it is for are not known.")

PLACE_TOOL = {
    "name": "submit_place_page",
    "description": "Describe one place in the game - a screen, menu, or board - as an OKF Entity page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What a player would call this place, in the game's own words, e.g. 'Settings'. Title case. No internal ids."},
            "description": {"type": "string", "description": "ONE sentence: what this place is and what it is for."},
            "what_it_is": {"type": "array", "items": {"type": "string"},
                           "description": "What this place is and where it sits in the game. 1-4 points."},
            "whats_here": {"type": "array", "items": {"type": "string"},
                           "description": "What a player sees and can operate here, in their own terms. One point per control or group of like controls; group a long list (fourteen challenges, twenty tiles) rather than enumerating it."},
            "what_happens": {"type": "array", "items": {"type": "string"},
                             "description": "What the given actions do here - keys, clicks, the wheel, dragging - including what demonstrably does nothing, which is as useful to know."},
            "unknowns": {"type": "array", "items": {"type": "string"},
                         "description": "What is still not known about this place, and why - a control never activated, an action deliberately not taken because it looked irreversible. Say what it might do, if the material says."},
        },
        "required": ["title", "description", "what_it_is", "whats_here", "what_happens", "unknowns"],
    },
}

RULES_TOOL = {
    "name": "submit_rules",
    "description": "Report the rules of the game's navigation and input model, synthesized across all its places.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "description": "Between 3 and 8 rules. A rule is something true across more than one place, or a structural fact about the game as a whole - what a key does everywhere, which places are one-way, what nothing observed ever reached. Not a restatement of one place's own behaviour.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short name for the rule, e.g. 'Escape backs out of sub-screens'."},
                        "description": {"type": "string", "description": "ONE sentence stating the rule."},
                        "statement": {"type": "array", "items": {"type": "string"},
                                      "description": "The rule, and the observations that support it. 1-4 points."},
                        "exceptions": {"type": "array", "items": {"type": "string"},
                                       "description": "Places or cases where the rule does not hold, or where the evidence contradicts itself. Empty if none."},
                        "open_questions": {"type": "array", "items": {"type": "string"},
                                           "description": "What a tester should check next to settle this rule. Empty if none."},
                    },
                    "required": ["title", "description", "statement", "exceptions", "open_questions"],
                },
            },
        },
        "required": ["rules"],
    },
}

OVERVIEW_TOOL = {
    "name": "submit_overview",
    "description": "Describe the game at a glance, as an OKF Product Overview page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string", "description": "ONE sentence: what this game is."},
            "what_it_is": {"type": "array", "items": {"type": "string"}, "description": "What the game is and what a player does in it. 2-5 points."},
            "how_it_is_structured": {"type": "array", "items": {"type": "string"}, "description": "How the game's places fit together, in a player's terms."},
            "not_known": {"type": "array", "items": {"type": "string"}, "description": "The largest gaps - parts of the game nothing has reached or exercised yet."},
        },
        "required": ["title", "description", "what_it_is", "how_it_is_structured", "not_known"],
    },
}


def strings(data, field, errors) -> None:
    if not isinstance(data.get(field), list) or not all(isinstance(x, str) and x for x in data.get(field, [])):
        errors.append(f"'{field}' must be a list of non-empty strings")


def sentences(data, fields, errors) -> None:
    for field in fields:
        if not isinstance(data.get(field), str) or not data[field]:
            errors.append(f"'{field}' must be a non-empty string")


def validate_place(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors: list[str] = []
    sentences(data, ("title", "description"), errors)
    for field in ("what_it_is", "whats_here", "what_happens", "unknowns"):
        strings(data, field, errors)
    return errors


def validate_rules(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["'rules' must be a non-empty list"]
    errors: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{index}] must be an object")
            continue
        inner: list[str] = []
        sentences(rule, ("title", "description"), inner)
        strings(rule, "statement", inner)
        for field in ("exceptions", "open_questions"):
            if not isinstance(rule.get(field), list):
                inner.append(f"'{field}' must be a list")
        errors += [f"rules[{index}]: {e}" for e in inner]
    return errors


def validate_overview(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors: list[str] = []
    sentences(data, ("title", "description"), errors)
    for field in ("what_it_is", "how_it_is_structured", "not_known"):
        strings(data, field, errors)
    return errors


def frontmatter(page_type: str, data: dict, tags: list[str], sources: list[dict],
                timestamp: str, extra: str = "") -> str:
    lines = [f"type: {page_type}", f'title: "{data["title"]}"', f"description: {data['description']}"]
    if extra:
        lines.append(extra)
    lines += [f"tags: [{', '.join(tags)}]", "status: draft",
              f'generated: {{ by: {AUTHOR}, at: "{timestamp}" }}', "sources:"]
    for source in sources:
        lines.append(f"  - id: {source['id']}")
        lines.append(f"    resource: {source['resource']}")
        lines.append(f'    title: "{source["title"]}"')
    return "---\n" + "\n".join(lines) + "\n---\n"


def bullets(items, cite: str) -> str:
    return "\n".join(f"- {item}[^{cite}]" for item in items) or "_none noted_"


def render_place_page(data: dict, source: dict, sources: list[dict], product: str, timestamp: str) -> str:
    cite = sources[0]["id"]

    def route_table(rows, first_column: str, key: str) -> str:
        if not rows:
            return "_No route was observed._"
        head = f"| {first_column} | By |\n|---|---|\n"
        return head + "\n".join(
            f"| {row[key]} | {row['by']}{'' if row['seen'] > 1 else ' _(seen once)_'} |" for row in rows)

    # Rendered from the map, not asked of the model: which routes exist, how you
    # arrive, which controls were never activated and which values a control was
    # seen holding are all things the map states outright. Asking would only add
    # a chance of the answer coming back different.
    states = "\n".join(
        f"- **{control}** was seen as " + ", ".join(f"`{value}`" for value in values) + f"[^{cite}]"
        for control, values in sorted(source["controls_with_state"].items())) or "_None observed changing._"
    never = "\n".join(f"- {label}[^{cite}]" for label in source["never_clicked"]) or "_None._"
    footnotes = "\n".join(f"[^{s['id']}]: {s['resource']}" for s in sources)

    return f"""{frontmatter("Entity", data, [product, "screen"], sources, timestamp, extra="entity_kind: screen")}
# {data['title']}

## What it is

{bullets(data['what_it_is'], cite)}

## What's here

{bullets(data['whats_here'], cite)}

## Settings and states observed here

{states}

## What happens when you act

{bullets(data['what_happens'], cite)}

## Where it leads

{route_table(source['leads_to'], 'To', 'to')}

## How you get here

{route_table(source['reached_by'], 'From', 'from')}

## Never activated

{never}

## Unknowns

{bullets(data['unknowns'], cite)}

{footnotes}
"""


def render_rule_page(rule: dict, sources: list[dict], product: str, timestamp: str) -> str:
    cite = sources[0]["id"]
    footnotes = "\n".join(f"[^{s['id']}]: {s['resource']}" for s in sources)
    return f"""{frontmatter("Quality Concept", rule, [product, "rules"], sources, timestamp)}
# {rule['title']}

## The rule

{bullets(rule['statement'], cite)}

## Exceptions

{bullets(rule['exceptions'], cite)}

## Open questions

{bullets(rule['open_questions'], cite)}

{footnotes}
"""


def render_overview_page(data: dict, places: list[dict], sources: list[dict],
                         product: str, timestamp: str) -> str:
    cite = sources[0]["id"]
    listing = "\n".join(
        f"- **[{place['title']}](entities/{place['slug']}.md)** - {place['description']}" for place in places)
    footnotes = "\n".join(f"[^{s['id']}]: {s['resource']}" for s in sources)
    return f"""{frontmatter("Product Overview", data, [product], sources, timestamp)}
# {data['title']}

## What it is

{bullets(data['what_it_is'], cite)}

## How it is structured

{bullets(data['how_it_is_structured'], cite)}

## Places

{listing}

## What is not known

{bullets(data['not_known'], cite)}

{footnotes}
"""


def name_honestly(result: dict, source: dict) -> dict:
    """Overwrites the title and description of a place nobody identified. Keeps
    the reached-from clause in the title so the page is still findable and does
    not collide with another unidentified screen."""
    if source["described"]:
        return result
    reached = source["reached_by"][0]["from"] if source["reached_by"] else ""
    result["title"] = f"{UNNAMED_TITLE} reached from the {reached}" if reached else UNNAMED_TITLE
    result["description"] = UNNAMED_DESCRIPTION
    return result


def for_model(source: dict) -> str:
    """A place as the model sees it. The screen ids it was assembled from and the
    filename of its screenshot are bookkeeping - the ids belong to the harness,
    and the filename would only tempt the model into naming the place after it.
    Both are still used here, for the page's `sources:` entries."""
    return json.dumps({k: v for k, v in source.items() if k not in ("screen_ids", "image")},
                      ensure_ascii=False, indent=1)


def unique(slug: str, taken: set[str]) -> str:
    """Two places can end up with the same title, and a page silently
    overwriting another is the worst possible failure here - it looks like a
    smaller game rather than a broken run."""
    candidate, n = slug, 1
    while candidate in taken:
        n += 1
        candidate = f"{slug}-{n}"
    taken.add(candidate)
    return candidate


def clear_own_pages(dest_dir: Path) -> list[str]:
    """Removes the pages a previous run of *this* script wrote.

    A run rewrites the whole wiki from one map, so anything left from an earlier
    one is not extra knowledge - it is a second, contradictory account. Left in
    place they accumulate under `unique()`'s suffixes: a run against a newer map
    produced `settings-menu-2.md` and `settings-menu-3.md` beside the page they
    were meant to replace, and the derived index then listed one settings screen
    six times, which reads as a fact about the game.

    `log/` is left alone. It is append-only by design - a record of which runs
    happened, which is exactly the thing a rewrite must not erase. `summaries/`
    is left alone too: it belongs to generate.py, not to this script.
    """
    removed = []
    for owned in sorted(list(dest_dir.glob("entities/*.md")) + list(dest_dir.glob("concepts/*.md"))
                        + [dest_dir / "overview.md"]):
        if owned.is_file():
            owned.unlink()
            removed.append(str(owned.relative_to(dest_dir)).replace("\\", "/"))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pass-dir", required=True,
                        help="A game-ontology pass directory (holds ontology.json and images/)")
    parser.add_argument("--dest", default="results/game-wiki/wiki",
                        help="Destination wiki directory; must be named 'wiki' for the index rebuild (default: results/game-wiki/wiki)")
    parser.add_argument("--product", default=None, help="Product slug (default: the game's own name)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be sent and write nothing. Costs nothing.")
    args = parser.parse_args()

    pass_dir = Path(args.pass_dir).resolve() if Path(args.pass_dir).is_absolute() else (HERE / args.pass_dir).resolve()
    if not (pass_dir / "ontology.json").is_file():
        raise SystemExit(f"--pass-dir '{pass_dir}' has no ontology.json")
    data = ontology_source.load(pass_dir)
    reader = ontology_source.Reader(data)
    game = data.get("target", {}).get("name") or pass_dir.name
    product = args.product or slugify(game)

    sources_in = reader.sources()
    graph = reader.graph()
    map_source = {"id": "map", "resource": repo_relative(pass_dir / "ontology.json"),
                  "title": f"{game} - observed by exploration"}

    print(f"{game}: {len(sources_in)} places, {len(graph['routes'])} routes between them")
    if graph["screens_merged"]:
        for name, ids in graph["screens_merged"].items():
            print(f"  '{name}' was seen as {len(ids)} separate screens and is written as one place")
    if reader.warnings_dropped:
        print(f"  {reader.warnings_dropped} refusal reasons are not usable, because they explain "
              f"themselves in coordinates rather than in the game's terms")

    if args.dry_run:
        print("\n--- what each place call would be given ---")
        for source in sources_in:
            print(for_model(source))
        print("\n--- what the rules call would be given ---")
        print(json.dumps(graph, indent=1, ensure_ascii=False))
        print("\nDry run: nothing written, nothing spent.")
        return

    dest_dir = Path(args.dest).resolve() if Path(args.dest).is_absolute() else (HERE / args.dest).resolve()
    ensure_workspace(dest_dir)
    for stale in clear_own_pages(dest_dir):
        print(f"  removed a page from an earlier run: {stale}")
    client, model = build_client(), default_model()
    timestamp, usage = now_iso(), []
    log_entries, taken_slugs, pages = [], set(), []

    for source in sources_in:
        print(f"Writing up '{source['name']}'...")
        shot = pass_dir / source["image"] if source["image"] else None
        page_sources = [map_source]
        if shot and shot.is_file():
            page_sources.append({"id": f"{slugify(source['name'])}-seen",
                                 "resource": repo_relative(shot), "title": f"{source['name']} as seen"})
        result = call_tool_with_retry(
            client, model=model,
            system=(
                f"You are writing the wiki page for one place in the game '{game}' - a screen, menu, or "
                f"board a player can be in. {NO_INVENTION} The other places in this game are: "
                + ", ".join(f"'{other['name']}'" for other in sources_in if other is not source)
                + ". Refer to them by name where a route leads to one."
                + ("" if source["described"] else
                   " This place was never identified: nobody has said what it is. Do not name it or "
                   "assert what it does - its title and description will be written for you. Your "
                   "body text may say what it might be, said as a possibility.")
                + " Call submit_place_page."
            ),
            tools=[PLACE_TOOL], tool_name="submit_place_page",
            user_message=for_model(source),
            max_tokens=2048, validate_fn=validate_place, usage_sink=usage,
        )
        result = name_honestly(result, source)
        slug = unique(slugify(result["title"]), taken_slugs)
        (dest_dir / "entities" / f"{slug}.md").write_text(
            render_place_page(result, source, page_sources, product, timestamp), encoding="utf-8")
        print(f"  -> wiki/entities/{slug}.md")
        log_entries.append(f"**Place**: '{source['name']}' -> `wiki/entities/{slug}.md`")
        pages.append({"title": result["title"], "description": result["description"], "slug": slug})

    print("Working out the rules across all places...")
    rules = call_tool_with_retry(
        client, model=model,
        system=(
            f"You are writing the rules of '{game}' - what holds across its places rather than inside any "
            f"one of them. {NO_INVENTION} You are given every place, every observed route between them, "
            "what each place does with each key, which places nothing was ever observed leaving, which "
            "were never arrived at, and which separate-looking screens turned out to be one place in "
            "different states. Call submit_rules."
        ),
        tools=[RULES_TOOL], tool_name="submit_rules",
        user_message=json.dumps(graph, ensure_ascii=False, indent=1),
        max_tokens=3072, validate_fn=validate_rules, usage_sink=usage,
    )
    for rule in rules["rules"]:
        slug = unique(slugify(rule["title"]), taken_slugs)
        (dest_dir / "concepts" / f"{slug}.md").write_text(
            render_rule_page(rule, [map_source], product, timestamp), encoding="utf-8")
        print(f"  -> wiki/concepts/{slug}.md")
        log_entries.append(f"**Rule**: {rule['title']} -> `wiki/concepts/{slug}.md`")

    print("Writing the overview...")
    overview = call_tool_with_retry(
        client, model=model,
        system=(f"You are writing the front page for '{game}'. {NO_INVENTION} You are given every place's "
                "own page summary and every rule found across them. Call submit_overview."),
        tools=[OVERVIEW_TOOL], tool_name="submit_overview",
        user_message=json.dumps({"places": [{k: p[k] for k in ("title", "description")} for p in pages],
                                 "rules": [{k: r[k] for k in ("title", "description")} for r in rules["rules"]]},
                                ensure_ascii=False, indent=1),
        max_tokens=2048, validate_fn=validate_overview, usage_sink=usage,
    )
    (dest_dir / "overview.md").write_text(
        render_overview_page(overview, pages, [map_source], product, timestamp), encoding="utf-8")
    print("  -> wiki/overview.md")
    log_entries.append("**Overview**: all places and rules -> `wiki/overview.md`")

    rebuild_index(dest_dir)
    log_entries.append(f"**Rebuild**: `node .wiki-source/scripts/rebuild-index.mjs --dir "
                       f"{repo_relative(dest_dir.parent)}` -> `wiki/index.md`")
    append_log(dest_dir, product, log_entries, git_user(), timestamp)

    for name, totals in summarize_usage(usage).items():
        print(f"{name}: {totals['calls']} calls, {totals['input_tokens']} in, {totals['output_tokens']} out")
    print(f"\nDone. Wiki written to {dest_dir}")


if __name__ == "__main__":
    main()
