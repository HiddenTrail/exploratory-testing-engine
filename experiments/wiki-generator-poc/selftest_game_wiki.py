"""Checks everything about generate_game_wiki.py that does not need a model.

The model writes prose; this script writes stub prose in its place and exercises
the rest - the regrouping, the phrasing, the rendering, the slugs, the citations
and the index rebuild. It costs nothing and needs no game running, so it can run
on any change.

What it actually asserts, and why each one is worth asserting:

1. Every place gets exactly one page, and no two pages share a filename. A
   colliding slug silently overwrites a page, and the result looks like a
   smaller game rather than a broken run.
2. No harness vocabulary reaches a page body. This is the whole claim of
   ontology_source.py - that what comes out describes the game and not the
   exploration - and it is the one thing a reader cannot check for themselves.
3. Every sources[].resource points at a file that exists. AGENTS.md requires
   real paths; a citation nobody can open is worse than no citation.
4. Every page's frontmatter parses and carries the required fields, and no page
   claims to be verified.

Run:  py selftest_game_wiki.py --pass-dir <a game-ontology pass directory>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import generate_game_wiki as gen
import ontology_source
from generate import ensure_workspace, rebuild_index

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent

# What it means for the harness to have leaked into a page about the game. The
# vocabulary of pixel comparison and coordinates comes straight from
# ontology_source, so the module's own definition of "harness talk" and the check
# that none of it escapes cannot drift apart. The rest is specific to pages:
# internal ids and the harness's own words for the things it tracks.
LEAKS = [(pattern, "exploration machinery") for pattern in ontology_source.HARNESS_TALK] + [
    (r"\bsc\d\d\b", "an internal screen id"),
    # Phrases, not words. A first attempt matched bare "settle" and "threshold"
    # and flagged "not yet settled" and "point-threshold challenges" - both
    # ordinary English, and a check that cries wolf on good prose is a check
    # that gets switched off.
    (r"settl\w*\s+(?:time|ms\b)|\bmatch\s+threshold\b|\bfingerprint|\bvetted\b|\bprobed\b",
     "the exploration's bookkeeping"),
    (r"\bvariant\b", "the harness's word for an appearance"),
    # How often something was seen measures how hard the explorer looked, not
    # the game. It reads as a fact about the game though - "visited 20 times
    # across 10 distinct visual states" - which is why it is checked for rather
    # than trusted to the instruction that says not to write it.
    #
    # Words count as much as digits: a rule page's own description read "the most
    # reliably observed route into the settings menu, having been seen three
    # times", which a digits-only pattern waves through. "Seen once" is the one
    # allowed form, and deliberately so - it is how the pages mark an
    # observation too thin to trust, so it is a hedge rather than a measurement.
    (r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+times\b|\btwice\b",
     "a count of how often the explorer was there"),
    (r"\b\d+\s+(?:distinct|different|separate)\s+(?:visual\s+)?(?:states?|appearances?|looks?)\b",
     "a count of appearances"),
]


def stub_place(source: dict) -> dict:
    """Stands in for the model, using only what it would have been given, so a
    leak in the rendered page can only have come from the reader or the
    renderer - the two things this script exists to check."""
    return {
        "title": source["name"].title(),
        "description": f"Stub description of {source['name']}.",
        "what_it_is": [f"A place in the game called {source['name']}."],
        "whats_here": [control["label"] for control in source["controls"]] or ["Nothing was described here."],
        "what_happens": source["what_actions_do"] or ["Nothing was observed."],
        "unknowns": source["warnings"] or ["Nothing flagged."],
    }


def stub_rules(graph: dict) -> dict:
    return {"rules": [{
        "title": "Stub rule about routes",
        "description": "A stub rule so the renderer has something to render.",
        "statement": [f"{edge['from']} leads to {edge['to']} by {edge['by']}." for edge in graph["routes"]] or ["No routes."],
        "exceptions": graph["no_way_out_observed"],
        "open_questions": graph["never_arrived_at"],
    }]}


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise AssertionError("page does not start with frontmatter")
    end = text.index("\n---\n", 3)
    raw, body = text[4:end], text[end + 5:]
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if re.match(r"^[a-z_]+:", line):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, body


def check_pages(paths: list[Path]) -> list[str]:
    """The page-level checks, separated so they can also be run over a real
    run's output - where the prose is the model's and a leak is likeliest. The
    stub run can only catch leaks from the reader and the renderer."""
    failures = []
    for path in paths:
        fields, body = split_frontmatter(path.read_text(encoding="utf-8"))
        required = ["type", "title", "description", "generated", "sources"]
        # A Log Entry page records what a run did, so it has no source material to
        # cite - the run itself is the subject. Every other page type is making a
        # claim about the game and has to say where the claim came from.
        if fields.get("type") == "Log Entry":
            required.remove("sources")
        for field in required:
            if field not in fields:
                failures.append(f"{path.name}: frontmatter has no '{field}'")
        if "verified" in fields:
            failures.append(f"{path.name}: claims to be verified, and nothing has been")
        # Footnote definitions and the sources block legitimately carry real
        # file paths, which contain run directory names; the prose must not.
        #
        # The title and description are checked with the body, and they matter
        # more than the body does: they are what the derived index and the
        # overview quote, so a leak there is repeated on pages that never made
        # the claim. Checking only the body let "having been seen three times"
        # through into the index.
        prose = "\n".join([fields.get("title", ""), fields.get("description", "")]
                          + [line for line in body.splitlines() if not line.startswith("[^")])
        for pattern, what in LEAKS:
            found = re.findall(pattern, prose, flags=re.IGNORECASE)
            if found:
                failures.append(f"{path.name}: leaks {what} ({sorted(set(str(f) for f in found))[:3]})")
        for match in re.finditer(r"^    resource: (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE):
            if not (gen.REPO_ROOT / match.group(1)).exists():
                failures.append(f"{path.name}: cites '{match.group(1)}', which does not exist")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pass-dir", required=True)
    parser.add_argument("--dest", default="results/selftest-wiki/wiki")
    parser.add_argument("--check-only", action="store_true",
                        help="Skip generation and run the page checks over whatever markdown is "
                             "already in --dest, e.g. a real run's output.")
    args = parser.parse_args()

    if args.check_only:
        pages = sorted(p for p in (HERE / args.dest).resolve().rglob("*.md") if p.name != "index.md")
        failures = check_pages(pages)
        print(f"checked {len(pages)} pages already in {args.dest}")
        if failures:
            print("\nFAIL")
            for failure in failures:
                print(f"  - {failure}")
            raise SystemExit(1)
        print("\nOK - no harness vocabulary in any page body, every citation resolves, "
              "no page claims verification")
        return

    pass_dir = Path(args.pass_dir).resolve() if Path(args.pass_dir).is_absolute() else (HERE / args.pass_dir).resolve()
    data = ontology_source.load(pass_dir)
    reader = ontology_source.Reader(data)
    sources_in, graph = reader.sources(), reader.graph()
    game = data.get("target", {}).get("name") or pass_dir.name
    product = gen.slugify(game)
    map_source = {"id": "map", "resource": gen.repo_relative(pass_dir / "ontology.json"), "title": game}

    # Clearing the markdown rather than the directory tree: on Windows a shell
    # sitting in the output directory holds a lock on it, and a self-test that
    # fails because someone was looking at last run's pages is a self-test
    # people stop trusting. Stale pages would still be caught - the index count
    # is compared against the number written.
    dest = (HERE / args.dest).resolve()
    ensure_workspace(dest)
    for stale in dest.rglob("*.md"):
        stale.unlink()
    timestamp = "2026-01-01T00:00:00Z"

    print(f"{game}: {len(sources_in)} places from {len(data['screens'])} screens, "
          f"{len(graph['routes'])} routes")
    for name, ids in graph["screens_merged"].items():
        print(f"  merged into '{name}': {', '.join(ids)}")

    taken, pages, written = set(), [], []
    for source in sources_in:
        stub = stub_place(source)
        page_sources = [map_source]
        shot = pass_dir / source["image"] if source["image"] else None
        if shot and shot.is_file():
            page_sources.append({"id": f"{gen.slugify(source['name'])}-seen",
                                 "resource": gen.repo_relative(shot), "title": source["name"]})
        slug = gen.unique(gen.slugify(stub["title"]), taken)
        path = dest / "entities" / f"{slug}.md"
        path.write_text(gen.render_place_page(stub, source, page_sources, product, timestamp), encoding="utf-8")
        written.append(path)
        pages.append({"title": stub["title"], "description": stub["description"], "slug": slug})

    rules = stub_rules(graph)
    for rule in rules["rules"]:
        slug = gen.unique(gen.slugify(rule["title"]), taken)
        path = dest / "concepts" / f"{slug}.md"
        path.write_text(gen.render_rule_page(rule, [map_source], product, timestamp), encoding="utf-8")
        written.append(path)

    overview = {"title": game, "description": f"Stub overview of {game}.",
                "what_it_is": ["A game."], "how_it_is_structured": ["It has places."],
                "not_known": ["Almost everything."]}
    path = dest / "overview.md"
    path.write_text(gen.render_overview_page(overview, pages, [map_source], product, timestamp), encoding="utf-8")
    written.append(path)

    failures = []
    if len(pages) != len(sources_in):
        failures.append(f"{len(sources_in)} places produced {len(pages)} pages")
    if len({p['slug'] for p in pages}) != len(pages):
        failures.append("two places share a filename")

    failures += check_pages(written)

    print(f"pages written: {len(written)}, refusal reasons dropped for talking "
          f"in the harness's terms: {reader.warnings_dropped}")
    rebuild_index(dest)
    index = dest / "index.md"
    if index.is_file():
        listed = sum(1 for line in index.read_text(encoding="utf-8").splitlines() if line.strip().startswith("* ["))
        if listed != len(written):
            failures.append(f"{len(written)} pages written but index.md lists {listed}")
        print(f"index.md rebuilt, listing {listed} pages")
    else:
        print("! index.md was not produced (node or the rebuild script is missing) - pages are still usable")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("\nOK - no harness vocabulary in any page body, every citation resolves, no page claims verification")


if __name__ == "__main__":
    main()
