"""A recon pass's `ontology.json`, turned into an OKF wiki bundle without asking a model anything.

Why this is worth having as a script at all
-------------------------------------------
The wiki this replaces was written by an agent reading the run output and deciding what was
interesting. That works, and it produced a good wiki once, but it cannot be handed to
somebody else: it needs an LLM sitting in the loop, and what that LLM mostly does is patch
around whatever the run did differently this time. So the question this file answers is how
much of that wiki was actually *interpretation*, and the answer turned out to be less than
it looked.

Everything below is a measurement already present in the run output or an arithmetic
consequence of one. The per-screen pages are `ontology.json`'s own `name`, `purpose`,
element boxes and cell counts. The navigation map is a graph over the recorded transitions.
The refusal tally is `blocked_actions` grouped by its own `why` strings. And the page that
was the most interesting one in the hand-built wiki - the one showing that some transitions
report a change between two frames that are byte-identical - is a hash comparison, which is
the least interpretive operation in the file.

What that leaves for a model is genuine synthesis: what the shape of the graph *means*, what
the refusals say about the target's monetisation surface. That is `synthesize.py`, it is
optional, and every page here is complete and readable without it.

The honesty rules this holds itself to
--------------------------------------
**Nothing is claimed that the run did not record.** Where a page needs a rule to turn
measurements into a statement - which elements count as "never activated", which count as
"persistent across screens" - the rule and its tolerance are printed on the page next to the
number, so a reader can disagree with the rule rather than having to trust the count.

**A model's guess is never rendered as a measurement.** `ontology.json` marks each element's
`located` field, and an element the recon placed from a description rather than from pixels
says so in its own row. The recon report already made this distinction and dropping it here
would be the one change that turns this wiki into a confident wrong answer.

**The reference has a date on it and so does this.** Screen names come from fingerprints
measured against a client that updates itself. The overview page carries that provenance
rather than burying it, because a wiki that reads clean about a stale measurement is worse
than one that admits it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Elements are counted as activated if a probe landed inside their measured box, or within
# this fraction of their point when they have no box. A tolerance is unavoidable - the recon
# probes a grid of coordinates and separately names elements, so the two never coincide
# exactly - and the number is printed on the page that uses it so the count can be argued
# with rather than taken on trust.
REACH_TOLERANCE = 0.02

# Bands of the window that get their own section on the persistent-elements page. These are
# geometry, not interpretation: "elements measured in the top 6% of the window on five
# screens" is a thing the run measured, while "the top status bar" is a thing a person
# recognises. The page says the first and lets the reader conclude the second.
BANDS = (("top", 0.0, 0.06), ("bottom", 0.90, 1.0))

# A label has to appear on at least this many screens before the page calls it persistent.
# Two is a coincidence with 10 screens and 150 elements; three is a pattern.
PERSISTENT_ON = 3


# --- small text helpers -----------------------------------------------------------------

def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "untitled"


def one_line(text: str) -> str:
    """Collapse to a single line and strip the two characters the wiki toolchain chokes on.

    `index.md` puts a description on one line as `* [Title](url) - description`, so a newline
    breaks the index entry. Double quotes break the frontmatter, because these values are
    emitted quoted and the YAML subset the renderer ships has no escaping. Commas are left
    alone here and only stripped from the flow-mapping fields, which are the only place the
    renderer splits on them.
    """
    return re.sub(r"\s+", " ", str(text or "")).replace('"', "'").strip()


def _flow(value: str) -> str:
    """A value safe to put inside `{ key: value }`, which the renderer splits on commas."""
    return one_line(value).replace(",", ";")


def write(path: Path, text: str) -> None:
    """Write a page with LF line endings, on any platform.

    `newline="\\n"` and not the default, which on Windows translates every `\\n` into
    `\\r\\n`. That is not cosmetic. `render-html.mjs` splits a body on `"\\n"` alone, so every
    line then arrives with a trailing `\\r`; its list branch tests a line with one regex and
    re-matches it with a second ending `(.*)$`, and in JavaScript `.` does not match `\\r`. So
    a bullet ending in `\\r` passes the first test, fails the second, advances nothing, and the
    loop pushes until the output array hits its length limit.

    It cost an afternoon because of how it fails: `RangeError: Invalid array length` from a
    `push` call, with no mention of a line ending, on a bundle that `rebuild-index.mjs` had
    just processed happily. Written once here rather than passed at each call site so a page
    added later cannot reintroduce it.
    """
    path.write_text(text, encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class Source:
    id: str
    resource: str
    title: str


def frontmatter(kind: str, title: str, description: str, *, generated_by: str, at: str,
                sources: list[Source], tags: list[str] | None = None,
                entity_kind: str = "", stale_after: str = "") -> str:
    """The YAML block, emitted in the shape the renderer's own parser can read.

    Two constraints that are not obvious and are both load-bearing. `generated` is a flow
    mapping because that is what the templates use and what `render-html.mjs` unpacks, and
    its unpacker splits on commas - so neither the actor nor the timestamp may contain one.
    And `type` must be present and non-empty on every page: that single field is the whole of
    OKF conformance, and a page missing it is dropped from the bundle rather than repaired.
    """
    lines = [
        "---",
        f"type: {kind}",
    ]
    if entity_kind:
        lines.append(f"entity_kind: {entity_kind}")
    lines += [
        f'title: "{one_line(title)}"',
        f'description: "{one_line(description)}"',
        f"tags: [{', '.join(tags or [])}]",
        "status: draft",
        f'generated: {{ by: "{_flow(generated_by)}", at: "{_flow(at)}" }}',
    ]
    if stale_after:
        lines.append(f'stale_after: "{_flow(stale_after)}"')
    if not sources:
        # An empty block key parses as null and then every consumer has to guard for it, so
        # an empty list is emitted explicitly. Only the log entry reaches this: it cites the
        # runs listed in its own body rather than one source.
        lines.append("sources: []")
    else:
        lines.append("sources:")
        for source in sources:
            lines += [f"  - id: {source.id}",
                      f'    resource: "{one_line(source.resource)}"',
                      f'    title: "{one_line(source.title)}"']
    lines.append("---")
    return "\n".join(lines)


@dataclass
class Page:
    """One wiki page on its way to disk.

    Carries its own `description` separately from the rendered text because the index is
    built from frontmatter, and a page whose description is derived from its body would have
    to be parsed back out to build the index.
    """
    rel: str                     # path under wiki/, e.g. "entities/screen-sc01.md"
    kind: str
    title: str
    description: str
    body: str
    entity_kind: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Facts:
    """Everything the deterministic pass worked out, in one object.

    Exists so `synthesize.py` can be handed measurements rather than markdown. A model asked
    to comment on a rendered page would be reading numbers back out of prose it is about to
    replace, and the first thing it would get wrong is a count it misparsed.
    """
    target: dict
    session: dict
    screens: list[dict]
    transitions: list[dict]
    graph: dict
    refusals: dict
    persistent: dict
    frames: dict
    reach: dict
    clickable: list[dict]


# --- derivations ------------------------------------------------------------------------

def graph_facts(data: dict) -> dict:
    """The navigation graph, and the four shapes worth naming in it.

    Only `effect == "screen"` edges are navigation. A `variant` edge is the same place
    looking different and a `none` edge is an input that did nothing, and counting either as
    a route is how a map grows exits that do not exist.
    """
    screens = [s["id"] for s in data["screens"]]
    edges = [(t["from"], t["to"]) for t in data["transitions"] if t["effect"] == "screen"]
    out: dict[str, set[str]] = {s: set() for s in screens}
    into: dict[str, set[str]] = {s: set() for s in screens}
    for a, b in edges:
        out.setdefault(a, set()).add(b)
        into.setdefault(b, set()).add(a)

    start = screens[0] if screens else ""
    seen, frontier = {start} if start else set(), [start] if start else []
    while frontier:
        for nxt in out.get(frontier.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)

    return {
        "screens": screens,
        "edges": sorted(set(edges)),
        "edge_count": len(edges),
        "distinct_edges": len(set(edges)),
        "out": {k: sorted(v) for k, v in out.items()},
        "into": {k: sorted(v) for k, v in into.items()},
        "start": start,
        # A sink was entered and never left, which for a run that has to get home again is
        # the most expensive shape in the graph.
        "sinks": [s for s in screens if into.get(s) and not out.get(s)],
        # Nothing was ever seen to enter these. Either a route exists and the pass never
        # took it, or the screen was reached by something the pass did not record as an
        # edge - and both are worth knowing before concluding anything about coverage.
        "never_entered": [s for s in screens if s != start and not into.get(s)],
        "isolated": [s for s in screens if not into.get(s) and not out.get(s) and s != start],
        "unreachable_from_start": [s for s in screens if s not in seen],
        "variant_edges": sum(1 for t in data["transitions"] if t["effect"] == "variant"),
        "inert_edges": sum(1 for t in data["transitions"] if t["effect"] == "none"),
    }


def _reached(element: dict, tried: list[str]) -> bool:
    """Whether any probe this pass sent landed on this element.

    Inside the measured box where there is one, and within `REACH_TOLERANCE` of the point
    otherwise. The two cases are not the same claim and the page says which applies to which
    element: a box is a measurement, so a probe inside it demonstrably hit the thing, while a
    point with a tolerance around it is a guess about a guess.
    """
    box = element.get("box")
    at = element.get("at")
    for action in tried:
        match = re.search(r"(\d*\.?\d+),(\d*\.?\d+)", action)
        if not match:
            continue
        x, y = float(match.group(1)), float(match.group(2))
        if box and len(box) == 4:
            if box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]:
                return True
        elif at and len(at) == 2:
            if abs(x - at[0]) <= REACH_TOLERANCE and abs(y - at[1]) <= REACH_TOLERANCE:
                return True
    return False


def reach_facts(data: dict) -> dict:
    """How many named controls were actually pressed, per screen and overall."""
    per_screen, named, activated = {}, 0, 0
    for screen in data["screens"]:
        tried = list((screen.get("explored") or {}).get("tried") or [])
        hits = [e for e in (screen.get("elements") or []) if _reached(e, tried)]
        per_screen[screen["id"]] = {
            "named": len(screen.get("elements") or []),
            "activated": len(hits),
            "probes": len(tried),
            "boxed": sum(1 for e in (screen.get("elements") or []) if e.get("box")),
        }
        named += per_screen[screen["id"]]["named"]
        activated += len(hits)
    return {"per_screen": per_screen, "named": named, "activated": activated,
            "never_activated": named - activated, "tolerance": REACH_TOLERANCE}


def _verdict_for(element: dict, mouse_verdicts: dict) -> dict | None:
    """The vetting verdict, if any, whose action coordinate lands on this element.

    Same matching rule as `_reached`: inside the measured box where there is one, or
    within `REACH_TOLERANCE` of the point otherwise - kept as one rule rather than two
    so "was this pressed" and "was this vetted" agree about what counts as landing on
    an element."""
    box = element.get("box")
    at = element.get("at")
    for action, verdict in mouse_verdicts.items():
        match = re.search(r"(\d*\.?\d+),(\d*\.?\d+)", action)
        if not match:
            continue
        x, y = float(match.group(1)), float(match.group(2))
        if box and len(box) == 4:
            if box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]:
                return verdict
        elif at and len(at) == 2:
            if abs(x - at[0]) <= REACH_TOLERANCE and abs(y - at[1]) <= REACH_TOLERANCE:
                return verdict
    return None


def clickable_facts(data: dict) -> list[dict]:
    """Every named element across the whole run, one row each, with what happened to it.

    `reach_facts` counts how many were pressed per screen; `refusal_facts` groups what
    was declined by the reason given. This reads both mechanisms together, per element,
    for a reader who wants "what could this pass have clicked" as one list rather than
    assembled by hand from a page per screen.

    Four statuses, and they are not degrees of the same claim:
    - **pressed** - a probe actually landed on it (`_reached`).
    - **refused** - the vetting call looked at it and said not to, in its own words.
    - **cleared, not pressed** - the vetting call said it was safe, but the screen's
      vetting budget or the pass's clock ran out before its turn came.
    - **not vetted** - no verdict on record matches its position at all - it was named by
      the description call but never became a candidate, or is on a screen the model
      never got to vet at all.
    """
    rows = []
    for screen in data["screens"]:
        sid = screen["id"]
        tried = list((screen.get("explored") or {}).get("tried") or [])
        verdicts = screen.get("mouse_verdicts") or {}
        for element in screen.get("elements") or []:
            if _reached(element, tried):
                status, why = "pressed", ""
            else:
                verdict = _verdict_for(element, verdicts)
                if verdict is None:
                    status, why = "not vetted", ""
                elif verdict.get("safe", True):
                    status, why = "cleared, not pressed", ""
                else:
                    status, why = "refused", one_line(verdict.get("why", ""))
            rows.append({"screen": sid, "label": one_line(element.get("label", "?")),
                        "what": one_line(element.get("what", "")),
                        "status": status, "why": why})
    return rows


def clickable_page(facts: Facts, ctx: Ctx) -> Page:
    rows = facts.clickable
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    tally = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))

    body = [
        "# Everything named as clickable, and what happened to it", "",
        "- **Kind:** ui-inventory", "",
    ]
    if not rows:
        body += ["The pass named no elements on any screen, so there is nothing to list "
                 "here - see [what it refused to do](refused-and-unmodelled.md) for what "
                 "it declined instead.", "",
                 _footnotes(ctx, ["ontology"])]
        return Page(rel="concepts/clickable-elements.md", kind="Concept",
                    title="Everything named as clickable, and what happened to it",
                    description="No elements were named on any screen this pass reached.",
                    body="\n".join(body), tags=["clash-royale", "ui"])

    body += [
        f"{len(rows)} elements named across {len(facts.screens)} screens: {tally}.", "",
        "**Pressed** - a probe this pass sent landed on it (inside its measured box, or "
        f"within {REACH_TOLERANCE} of its point when there is no box). **Refused** - the "
        "vetting call looked at it and said not to, in its own words. **Cleared, not "
        "pressed** - the vetting call said it was safe, but the screen's vetting budget "
        "or the pass's clock ran out before its turn came. **Not vetted** - no verdict on "
        f"record matched its position at all.{_cite('ontology')}", "",
        "| Screen | Element | What | Status | Why refused |",
        "|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: (r["screen"], r["status"], r["label"])):
        body.append(f"| {row['screen']} | {row['label']} | {row['what']} | "
                    f"{row['status']} | {row['why']} |")
    body += ["", _footnotes(ctx, ["ontology"])]

    return Page(rel="concepts/clickable-elements.md", kind="Concept",
                title="Everything named as clickable, and what happened to it",
                description=f"{len(rows)} elements named across the run: {tally}.",
                body="\n".join(body), tags=["clash-royale", "ui"])


def refusal_facts(data: dict) -> dict:
    """Everything the pass declined to do, grouped by the reason it gave.

    Two different mechanisms end up here and the page keeps them apart. `blocked_actions` is
    the pass recording that it did not send something; `mouse_verdicts` marked `safe: false`
    is the vetting call having looked at a control and said why not. The second is the
    interesting half - it is a reason in the model's own words about a specific control -
    and collapsing both into one count would lose it.
    """
    by_reason: dict[str, int] = {}
    for blocked in data.get("blocked_actions") or []:
        by_reason[one_line(blocked.get("why", "unstated"))] = \
            by_reason.get(one_line(blocked.get("why", "unstated")), 0) + 1

    vetted, refused = 0, []
    for screen in data["screens"]:
        for action, verdict in (screen.get("mouse_verdicts") or {}).items():
            vetted += 1
            if not verdict.get("safe", True):
                refused.append({"screen": screen["id"], "action": action,
                                "why": one_line(verdict.get("why", ""))})
    return {
        "blocked_total": len(data.get("blocked_actions") or []),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0]))),
        "vetted": vetted,
        "refused_by_model": refused,
    }


def persistent_facts(data: dict) -> dict:
    """Elements that recur across screens, by label and by position.

    Both views are here because each one misses what the other catches. A label recurring on
    six screens is the same control drawn in the same place; a *band* of the window carrying
    elements on six screens is a persistent region whose contents differ - which is the
    actual finding about this target's navigation bar, whose icon x positions are not the
    same on any two screens.
    """
    labels: dict[str, list[str]] = {}
    bands: dict[str, dict[str, list[str]]] = {name: {} for name, _, _ in BANDS}
    for screen in data["screens"]:
        for element in screen.get("elements") or []:
            key = one_line(element.get("label", "")).lower()
            if key:
                labels.setdefault(key, [])
                if screen["id"] not in labels[key]:
                    labels[key].append(screen["id"])
            at = element.get("at")
            if not (at and len(at) == 2):
                continue
            for name, low, high in BANDS:
                if low <= at[1] <= high:
                    bands[name].setdefault(screen["id"], []).append(
                        one_line(element.get("label", "?")))
    return {
        "repeated": {k: v for k, v in sorted(labels.items()) if len(v) >= PERSISTENT_ON},
        "bands": bands,
        "threshold": PERSISTENT_ON,
        "band_bounds": {name: [low, high] for name, low, high in BANDS},
    }


def frame_facts(run_dir: Path, data: dict) -> dict:
    """Hash every saved before/after crop pair and report where the evidence disagrees.

    This is the one page that finds something nobody wrote down. A transition records how
    many cells changed *and* saves a cropped before/after pair as the evidence for it, and
    those two can contradict each other: a nonzero count whose crops are byte-identical, or a
    zero count whose crops differ.

    What such a pair does and does not prove is worth stating exactly, because overclaiming
    here would be easy. The count is measured over the whole frame at the recon grid while the
    crop covers only `crop_box`, so identical crops do **not** prove the frame held still -
    the change may simply have happened outside the crop. What they do prove is that the
    saved evidence for that transition does not show the change it reports, which for a
    transition read as a panel opening is the difference between a finding and an artefact.
    """
    def digest(rel: str) -> str | None:
        if not rel:
            return None
        path = run_dir / rel
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    checked, silent, unrecorded = 0, [], []
    for transition in data["transitions"]:
        crops = transition.get("crops") or {}
        before, after = digest(crops.get("before", "")), digest(crops.get("after", ""))
        if before is None or after is None:
            continue
        checked += 1
        row = {"id": transition.get("id", "?"), "from": transition.get("from", "?"),
               "to": transition.get("to", "?"), "effect": transition.get("effect", "?"),
               "action": (transition.get("action") or {}).get("id", "?"),
               "changed_cells": transition.get("changed_cells", 0),
               "crop_box": transition.get("crop_box"), "hash": before}
        if before == after and transition.get("changed_cells", 0) > 0:
            silent.append(row)
        elif before != after and transition.get("changed_cells", 0) == 0:
            unrecorded.append(row)
    return {"checked": checked, "identical_crops_nonzero_count": silent,
            "differing_crops_zero_count": unrecorded}


# --- pages ------------------------------------------------------------------------------

@dataclass
class Ctx:
    """Everything a page writer needs that is not the measurement itself."""
    run_rel: str                 # run dir, relative to the workspace root
    generated_by: str
    at: str
    sources: list[Source]

    def image(self, rel: str, depth: int = 2) -> str:
        """A markdown-safe path from a page `depth` levels under `wiki/` to a run image."""
        if not rel:
            return ""
        path = "/".join([".."] * depth + [self.run_rel, rel])
        return path.replace(" ", "%20")


def _cite(source_id: str) -> str:
    return f"[^{source_id}]"


def _footnotes(ctx: Ctx, used: list[str]) -> str:
    return "\n".join(f"[^{s.id}]: {s.title} - `{s.resource}`"
                     for s in ctx.sources if s.id in used)


def overview_page(data: dict, facts: Facts, ctx: Ctx, threshold_note: str) -> Page:
    session, target = data["session"], data["target"]
    minutes = session.get("seconds", 0) / 60
    body = [
        f"# {target.get('name', 'the target')} - what one recon pass measured",
        "",
        f"A single automated pass over the live client, {minutes:.1f} minutes long, "
        f"{session.get('actions', 0)} inputs sent. It found "
        f"{len(facts.screens)} distinct screens and {facts.graph['distinct_edges']} distinct "
        f"routes between them.{_cite('ontology')}",
        "",
        "## What this describes, and whose",
        "",
        f"The window was `{target.get('window_title', '?')}` at "
        f"{'x'.join(str(n) for n in target.get('client') or [])} pixels. That title carries an "
        f"account name, and everything below is a picture of **that account on that day** - "
        f"its level, its currency, the offers live in its lobby. A different account at a "
        f"different time is a different set of screens, so nothing here should be read as a "
        f"description of the game in general.{_cite('ontology')}",
        "",
        "## How screens were told apart",
        "",
        f"Identity is a pixel comparison on a {session.get('grid', ['?', '?'])[0]}x"
        f"{session.get('grid', ['?', '?'])[1]} grid, at a threshold of "
        f"**{session.get('screen_match_threshold', '?')}**, with a per-cell tolerance of "
        f"{session.get('cell_delta', '?')}. The median score among matches was "
        f"{session.get('median_match_score', '?')}.{_cite('ontology')}",
        "",
        threshold_note,
        "",
        f"The pass {'did' if session.get('vetted_by_model') else 'did NOT'} use a model to vet "
        f"and name what it saw, and inputs were "
        f"{'enabled' if session.get('clicks_enabled') else 'disabled'}. It stopped because: "
        f"**{session.get('stopped', 'unstated')}**"
        + (f", having resumed from an earlier pass (`{session['resumed_from']}`)"
           if session.get("resumed_from") else "")
        + f".{_cite('ontology')}",
        "",
        "## Where to start",
        "",
        "- [The observed navigation map](concepts/navigation-map.md) - the graph, and the "
        "shapes in it that cost a run something.",
        "- [What the pass refused to do](concepts/refused-and-unmodelled.md) - both safety "
        "layers, and how much of the interface neither reached.",
        "- [Where the saved frames disagree with the counts](concepts/frames-vs-counts.md) - "
        "transitions whose own evidence does not show the change they report.",
        "- [How screen identity was decided](concepts/screen-identity.md) - the grid, the "
        "threshold, and the four ways they produce identities a person would not draw.",
        "- [Elements that recur across screens](entities/persistent-elements.md).",
        "",
    ]
    if session.get("notes"):
        body += ["## Caveats the pass recorded about itself", "",
                 *(f"- {one_line(note)}" for note in session["notes"]), ""]
    body.append(_footnotes(ctx, ["ontology"]))
    return Page(
        rel="overview.md", kind="Product Overview",
        title=f"{target.get('name', 'target')} - one recon pass, {minutes:.0f} minutes",
        description=(f"What one {minutes:.0f}-minute automated pass over the live "
                     f"{target.get('name', 'client')} measured: {len(facts.screens)} screens, "
                     f"{facts.graph['distinct_edges']} routes, {facts.refusals['blocked_total']} "
                     f"inputs declined."),
        body="\n".join(body), tags=["recon", "overview"])


def summary_page(data: dict, facts: Facts, ctx: Ctx, report_text: str) -> Page:
    session = data["session"]
    body = [
        "# Recon report - faithful digest",
        "",
        "A digest of the pass's own report, which is the run's primary record. Nothing is "
        f"added here.{_cite('report')}",
        "",
        "## Key points",
        "",
        f"- {session.get('actions', 0)} inputs over {session.get('seconds', 0) / 60:.1f} "
        f"minutes; stopped because *{session.get('stopped', 'unstated')}*.",
        f"- {len(facts.screens)} screens, {len(facts.transitions)} recorded transitions "
        f"({facts.graph['edge_count']} of them screen changes, "
        f"{facts.graph['variant_edges']} the same screen looking different, "
        f"{facts.graph['inert_edges']} inputs that changed nothing visible).",
        f"- {facts.reach['named']} controls named across all screens, "
        f"{facts.reach['activated']} of them actually pressed.",
        f"- {facts.refusals['blocked_total']} inputs declined, "
        f"{len(facts.refusals['refused_by_model'])} of them refused by the vetting call with a "
        f"stated reason.",
        f"- {session.get('restarts', 0)} client restarts; "
        f"{session.get('screens_split_by_name', 0)} screens split apart because the model's "
        f"naming disagreed with the pixel match.",
        "",
        "## Risks & open questions the report raises",
        "",
    ]
    notes = session.get("notes") or []
    if notes:
        body += [f"- {one_line(note)}" for note in notes[:20]]
        if len(notes) > 20:
            body.append(f"- ...and {len(notes) - 20} more of the same kind.")
    else:
        body.append("- The pass recorded no caveats about its own measurements.")
    body += ["", "## The report as the pass wrote it", "",
             f"Full text: `{ctx.run_rel}/report.md` "
             f"({len(report_text.splitlines())} lines).{_cite('report')}", "",
             _footnotes(ctx, ["report", "ontology"])]
    return Page(
        rel=f"summaries/recon-{slug(data['target'].get('name', 'target'))}.md",
        kind="Source Summary", title="Recon report - faithful digest",
        description=(f"Digest of the pass's own report: {len(facts.screens)} screens, "
                     f"{len(facts.transitions)} transitions, {facts.reach['named']} named "
                     f"controls of which {facts.reach['activated']} were pressed."),
        body="\n".join(body), tags=["recon", "digest"])


# --- where a screen animates on its own --------------------------------------------

# How far apart (in cells, including diagonally) two flagged cells can be and still join
# the same region. 0 would draw one box per cell, which is unreadable on a 32x18 grid and
# not what a person means by "the area that animates" - a gap of 1 merges a ring of cells
# around a single moving icon into the one box it visually is.
CLUSTER_GAP = 1


def _cluster_cells(cells: set) -> list[tuple[int, int, int, int]]:
    """Group grid cells into rectangles by connected-component clustering.

    Cell-grid coordinates in, cell-grid boxes out (x0, y0, x1, y1), x1/y1 exclusive - the
    caller converts to fractions, this only knows about adjacency."""
    remaining = set(cells)
    boxes = []
    while remaining:
        stack = [next(iter(remaining))]
        cluster: set = set()
        while stack:
            cell = stack.pop()
            if cell in cluster:
                continue
            cluster.add(cell)
            remaining.discard(cell)
            cx, cy = cell
            for dx in range(-CLUSTER_GAP, CLUSTER_GAP + 1):
                for dy in range(-CLUSTER_GAP, CLUSTER_GAP + 1):
                    neighbour = (cx + dx, cy + dy)
                    if neighbour in remaining:
                        stack.append(neighbour)
        xs = [c[0] for c in cluster]
        ys = [c[1] for c in cluster]
        boxes.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return boxes


def animation_regions(screen: dict, grid: tuple[int, int]) -> dict:
    """Red and orange regions on this screen, as fractional boxes clustered from cell
    masks the pass already measured - no new measurement, just grouping.

    Both colours come from `recon.py`'s `map_animation`, which samples a screen's own
    movement in two tiers before anything is done to it (see its docstring for why one
    sampling window cannot tell a shimmer from a slow badge blink apart).

    **Red** is `animated_fast_map`: cells caught moving within the fast tier - a
    sub-second cycle, the strongest evidence there is that a region animates
    continuously.

    **Orange** is `animated_map` minus `animated_fast_map`: cells the slow tier caught
    that the fast tier did not - a cycle slower than a second, up to a few seconds. Not
    "less certain" the way the old volatile-based proxy was; it is a genuinely different
    finding; same measurement method, coarser sampling."""
    cols, rows = grid

    def cells(grid_lines):
        return {(x, y) for y, line in enumerate(grid_lines or [])
                for x, ch in enumerate(line) if ch == "#"}

    fast = cells(screen.get("animated_fast_map"))
    slow_only = cells(screen.get("animated_map")) - fast

    def to_fractions(boxes):
        return [(round(x0 / cols, 3), round(y0 / rows, 3),
                 round(x1 / cols, 3), round(y1 / rows, 3))
                for x0, y0, x1, y1 in boxes]

    return {"red": to_fractions(_cluster_cells(fast)),
            "orange": to_fractions(_cluster_cells(slow_only))}


def _draw_animation_map(image_path: Path, out_path: Path, regions: dict) -> bool:
    """Draw `regions` as outlined boxes on a copy of `image_path`. Returns False, having
    touched nothing, if Pillow is not installed or the image is not on disk - this kit
    ships with no image library by default (see requirements.txt), so the feature
    degrades rather than becoming a hard requirement of building a wiki at all."""
    if not image_path.exists():
        return False
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    colour = {"red": (230, 40, 40, 255), "orange": (255, 140, 0, 255)}
    base = Image.open(image_path).convert("RGBA")
    width, height = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for kind, boxes in regions.items():
        for x0, y0, x1, y1 in boxes:
            draw.rectangle([x0 * width, y0 * height, x1 * width, y1 * height],
                          outline=colour[kind], width=3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(base, overlay).convert("RGB").save(out_path)
    return True


def screen_page(screen: dict, data: dict, facts: Facts, ctx: Ctx, run_dir: Path) -> Page:
    sid = screen["id"]
    name = screen.get("name") or ""
    reach = facts.reach["per_screen"][sid]
    exits = facts.graph["out"].get(sid, [])
    entries = facts.graph["into"].get(sid, [])
    elements = screen.get("elements") or []
    title = f"{sid} - {name}" if name else f"{sid} - unnamed screen"

    body = [f"# {title}", "",
            f"- **Kind:** screen",
            f"- **Seen:** {screen.get('observations', 0)} times, first at action "
            f"{screen.get('first_seen_action', '?')}"]
    if name:
        body.append(f"- **What the vetting call called it:** \"{one_line(name)}\"")
    if screen.get("purpose"):
        body.append(f"- **Purpose, as described:** {one_line(screen['purpose'])}"
                    f"{_cite('ontology')}")
    body.append("")
    if screen.get("image"):
        body += [f"![{sid}]({ctx.image(screen['image'])})", ""]

    regions = animation_regions(screen, data["session"].get("grid") or [1, 1])
    if regions["red"] or regions["orange"]:
        body += ["## Where this screen animates on its own", ""]
        annotated_rel = ""
        if screen.get("image"):
            out_rel = f"images/{slug(sid)}-animation-map.png"
            if _draw_animation_map(run_dir / screen["image"], run_dir / out_rel, regions):
                annotated_rel = out_rel
        if annotated_rel:
            body += [f"![{sid} animation map]({ctx.image(annotated_rel)})", ""]
        else:
            body += ["*(No picture here - either Pillow is not installed "
                     "(`pip install Pillow`) or the screenshot this would draw on is "
                     "missing. The boxes below are the same data either way.)*", ""]
        body += [
            "**Red** - moves on a sub-second cycle (a pulse, a shine sweep, water or "
            "flags): caught within one second of sampling with no input in flight. "
            "**Orange** - moves too, but slower: not seen within that first second, only "
            "across a further three seconds of the same kind of sampling - a badge that "
            "blinks every couple of seconds, a slow fade. Anything slower than that "
            f"window may still be missed.{_cite('ontology')}", "",
            "| region | left | top | right | bottom |", "|---|---|---|---|---|",
        ]
        for kind in ("red", "orange"):
            for x0, y0, x1, y1 in regions[kind]:
                body.append(f"| {kind} | {x0:.3f} | {y0:.3f} | {x1:.3f} | {y1:.3f} |")
        body.append("")

    body += ["## How solidly this is one screen", "",
             f"{screen.get('stable_cells', 0)} cells held still across every sighting; "
             f"{screen.get('animated_cells', 0)} move with no input at all, so two frames "
             f"differing only there count as the same place. "
             f"{len(screen.get('variants') or [])} appearances were stored."
             f"{_cite('ontology')}", ""]
    if screen.get("identity_is_weak"):
        body += ["> **This screen's identity is flagged weak.** Too little of it holds still "
                 "for a pixel match to be trusted, so a frame filed here may belong "
                 "somewhere else - and any claim below that rests on which screen this is "
                 "inherits that doubt.", ""]

    body += ["## Elements", ""]
    if not elements:
        body.append("The pass named no elements on this screen, which means it was reached "
                    "but never described - so nothing here says what is on it.")
    else:
        measured = sum(1 for e in elements if e.get("box"))
        body += [
            f"{len(elements)} named, {measured} with a measured box and "
            f"{len(elements) - measured} placed from a description alone. The `located` column "
            f"is the run's own word for which is which, and it is reproduced rather than "
            f"softened: *described* next to a rectangle means nothing measured where that "
            f"rectangle ends.{_cite('ontology')}",
            "",
            "Pressed = a probe this pass sent landed inside the measured box, or within "
            f"{REACH_TOLERANCE} of the point where there is no box.",
            "",
            "| Element | What | Point | Box | Located | Pressed |",
            "|---|---|---|---|---|---|",
        ]
        tried = list((screen.get("explored") or {}).get("tried") or [])
        for element in elements:
            at = element.get("at") or []
            box = element.get("box") or []
            point = f"({at[0]:.3f}, {at[1]:.3f})" if len(at) == 2 else "unplaced"
            rect = (f"`[{box[0]:.3f}, {box[1]:.3f}, {box[2]:.3f}, {box[3]:.3f}]`"
                    if len(box) == 4 else "-")
            body.append(f"| {one_line(element.get('label', '?'))} | "
                        f"{one_line(element.get('what', ''))} | {point} | {rect} | "
                        f"{one_line(element.get('located', 'described'))} | "
                        f"{'yes' if _reached(element, tried) else 'no'} |")
        body += ["", f"{reach['activated']} of {reach['named']} were pressed by the "
                     f"{reach['probes']} probes this pass sent here. See "
                     f"[what the pass refused to do](../concepts/refused-and-unmodelled.md) "
                     f"for why the rest were not.", ""]

    body += ["## Routes", ""]
    if exits:
        body.append(f"**Out:** {', '.join(exits)}.")
    else:
        body.append("**Out:** nothing was seen to leave this screen - every input sent here "
                    "either changed nothing or only changed its appearance.")
    body.append("")
    if entries:
        body.append(f"**In:** {', '.join(entries)}.")
    else:
        body.append("**In:** nothing was seen to enter this screen, so how the pass got here "
                    "is not in the record.")
    body += ["", "See [the observed navigation map](../concepts/navigation-map.md) for the "
                 "graph this sits in.", "",
             _footnotes(ctx, ["ontology"])]

    summary_bits = [f"{len(elements)} named element{'' if len(elements) == 1 else 's'}",
                    f"{len(exits)} exit{'' if len(exits) == 1 else 's'}",
                    f"seen {screen.get('observations', 0)}x"]
    purpose = one_line(screen.get("purpose")) or "A screen the pass reached but never described"
    return Page(rel=f"entities/screen-{slug(sid)}.md", kind="Entity", entity_kind="screen",
                title=title,
                description=f"{purpose[:180]} ({', '.join(summary_bits)}).",
                body="\n".join(body), tags=["clash-royale", "screen", slug(sid)])


def persistent_page(facts: Facts, ctx: Ctx) -> Page:
    persistent = facts.persistent
    body = [
        "# Elements that recur across screens", "",
        "- **Kind:** ui-component", "",
        "Two views of the same question, because each catches what the other misses. A label "
        "recurring across screens is one control drawn in one place. A *band* of the window "
        "carrying elements on many screens is a persistent region whose contents differ - "
        "which is the more useful finding when a navigation bar's icons sit at different x "
        f"positions on every screen.{_cite('ontology')}", "",
        "## The same label, on several screens", "",
        f"A label has to appear on at least {persistent['threshold']} screens to be listed. "
        "Below that it is a coincidence between two independently written descriptions.", "",
    ]
    if persistent["repeated"]:
        body += ["| Label | Screens | Count |", "|---|---|---|"]
        for label, screens in sorted(persistent["repeated"].items(),
                                     key=lambda kv: (-len(kv[1]), kv[0])):
            body.append(f"| {label} | {', '.join(screens)} | {len(screens)} |")
    else:
        body.append(f"No label appeared on {persistent['threshold']} or more screens. Either "
                    f"the pass described too few screens for a pattern to show, or it named "
                    f"the same control differently each time - and the second is the likelier "
                    f"of the two, since each screen was described by its own call.")
    body.append("")

    for name, bounds in persistent["band_bounds"].items():
        rows = persistent["bands"][name]
        body += [f"## Elements in the {name} {bounds[0]:.0%}-{bounds[1]:.0%} of the window", ""]
        if not rows:
            body += ["Nothing was named in this band on any screen.", ""]
            continue
        body += [f"Present on {len(rows)} screen{'' if len(rows) == 1 else 's'}. This is "
                 f"geometry, not recognition: the run measured elements in this band, and "
                 f"whether they constitute one persistent bar is a reader's call.", "",
                 "| Screen | Elements named in this band |", "|---|---|"]
        for sid in sorted(rows):
            body.append(f"| {sid} | {'; '.join(rows[sid])} |")
        body.append("")

    body += ["## Related", "",
             "- [The observed navigation map](../concepts/navigation-map.md)",
             "- [What the pass refused to do](../concepts/refused-and-unmodelled.md)",
             "- [Everything named as clickable](../concepts/clickable-elements.md)", "",
             _footnotes(ctx, ["ontology"])]
    return Page(rel="entities/persistent-elements.md", kind="Entity",
                entity_kind="ui-component", title="Elements that recur across screens",
                description=(f"{len(persistent['repeated'])} labels named on "
                             f"{persistent['threshold']}+ screens, plus what the run measured "
                             f"in the window's top and bottom bands."),
                body="\n".join(body), tags=["clash-royale", "ui"])


def navigation_page(facts: Facts, ctx: Ctx) -> Page:
    graph = facts.graph
    body = [
        "# The observed navigation map", "",
        "## What it is", "",
        f"{graph['distinct_edges']} distinct routes between {len(graph['screens'])} screens, "
        f"from {graph['edge_count']} recorded screen changes. Only screen changes are routes "
        f"here: the pass also recorded {graph['variant_edges']} inputs that left it on the "
        f"same screen looking different and {graph['inert_edges']} that changed nothing "
        f"visible, and counting either as a route would grow the map exits that do not "
        f"exist.{_cite('ontology')}", "",
        "```",
        *([f"{a} -> {b}" for a, b in graph["edges"]] or ["(no screen changes recorded)"]),
        "```", "",
        "## Current state / findings", "",
        "| Screen | Out | In |", "|---|---|---|",
    ]
    for sid in graph["screens"]:
        body.append(f"| {sid} | {', '.join(graph['out'].get(sid, [])) or '-'} | "
                    f"{', '.join(graph['into'].get(sid, [])) or '-'} |")
    body += ["", f"The pass started on **{graph['start'] or '?'}**, which is the screen every "
                 f"reading below is relative to.", ""]

    for label, key, meaning in (
        ("Sinks", "sinks",
         "entered and never left. Every input sent here either did nothing or only changed "
         "the appearance, so a run that lands on one has no recorded way home."),
        ("Never entered", "never_entered",
         "the pass was on these screens but never recorded arriving at one. Either a route "
         "exists and was not taken, or arrival happened through something not recorded as an "
         "edge - and until that is resolved, coverage claims about them are unsupported."),
        ("Unreachable from the start screen", "unreachable_from_start",
         "no chain of recorded edges leads here from where the pass began, so nothing in this "
         "map explains how a fresh run would get to them."),
        ("Isolated", "isolated",
         "no recorded route in or out at all."),
    ):
        found = graph[key]
        body += [f"### {label}", "",
                 (", ".join(f"`{s}`" for s in found) + f" - {meaning}") if found
                 else f"None. {meaning[0].upper()}{meaning[1:]}", ""]

    body += ["## Implications", "",
             "- A pass that ends on a sink ends somewhere nobody chose, and the next run "
             "inherits that as its baseline unless a person puts the client back.",
             "- Screens nothing was seen to enter are the honest limit of this map: they are "
             "in it because the pass was on them, not because it knows a way there.",
             "", _footnotes(ctx, ["ontology"])]
    return Page(rel="concepts/navigation-map.md", kind="Quality Concept",
                title="The observed navigation map",
                description=(f"{graph['distinct_edges']} routes across "
                             f"{len(graph['screens'])} screens, with {len(graph['sinks'])} "
                             f"sinks and {len(graph['never_entered'])} screens nothing was seen "
                             f"to enter."),
                body="\n".join(body), tags=["clash-royale", "navigation"])


def refusals_page(facts: Facts, ctx: Ctx) -> Page:
    refusals, reach = facts.refusals, facts.reach
    body = [
        "# What the pass refused to do, and what it never reached", "",
        "## What it is", "",
        "Two different things end up looking like the same number, and this page keeps them "
        "apart. A **refusal** is the run declining to send an input. A control that was "
        "**never activated** was mostly not refused at all - the pass simply ran out of "
        f"budget before reaching it.{_cite('ontology')}", "",
        "## Refusals", "",
        f"{refusals['blocked_total']} inputs were declined, grouped by the reason the run "
        f"recorded:", "",
        "| Reason | Count |", "|---|---|",
    ]
    for reason, count in refusals["by_reason"].items():
        body.append(f"| {reason} | {count} |")
    if not refusals["by_reason"]:
        body.append("| (nothing was declined) | 0 |")

    body += ["", "### Refused by the vetting call, with a stated reason", "",
             f"{refusals['vetted']} controls were put to the vetting call and "
             f"{len(refusals['refused_by_model'])} came back unsafe. These are the interesting "
             f"half: a reason in the model's own words about one specific control, which a "
             f"coordinate rule cannot produce because a coordinate rule is screen-blind.", ""]
    if refusals["refused_by_model"]:
        body += ["| Screen | Action | Why it was refused |", "|---|---|---|"]
        for row in refusals["refused_by_model"]:
            body.append(f"| {row['screen']} | `{row['action']}` | {row['why']} |")
    else:
        body.append("Nothing was refused by the vetting call in this pass. That is not "
                    "reassurance on its own - it is also what a pass that never reached "
                    "anything risky looks like, and the two read identically here.")

    body += ["", "## What was named but never activated", "",
             f"{reach['named']} controls were named across all screens and "
             f"{reach['activated']} were pressed, leaving **{reach['never_activated']}** "
             f"identified but unmodelled. A control counts as pressed when a probe landed "
             f"inside its measured box, or within {reach['tolerance']} of its point where it "
             f"has no box - so this count is only as good as that rule, which is stated here "
             f"rather than buried so it can be argued with.", "",
             "| Screen | Named | Pressed | Probes sent | With a measured box |",
             "|---|---|---|---|---|"]
    for sid, row in reach["per_screen"].items():
        body.append(f"| {sid} | {row['named']} | {row['activated']} | {row['probes']} | "
                    f"{row['boxed']} |")

    body += ["", "## Implications", "",
             "- The gap between named and pressed is the honest coverage number, and it is "
             "mostly a budget story rather than a safety one.",
             "- A refusal is a **result**: it says a control exists and was judged too risky "
             "to touch, which is a fact about the target and not a gap in the run.",
             "", _footnotes(ctx, ["ontology"])]
    return Page(rel="concepts/refused-and-unmodelled.md", kind="Quality Concept",
                title="What the pass refused to do, and what it never reached",
                description=(f"{refusals['blocked_total']} inputs declined and "
                             f"{reach['never_activated']} of {reach['named']} named controls "
                             f"never pressed - two different numbers that are easy to "
                             f"conflate."),
                body="\n".join(body), tags=["clash-royale", "coverage", "safety"])


def frames_page(facts: Facts, ctx: Ctx) -> Page:
    frames = facts.frames
    silent, unrecorded = (frames["identical_crops_nonzero_count"],
                          frames["differing_crops_zero_count"])
    body = [
        "# Where the saved frames disagree with the counts", "",
        "## What it is", "",
        "Every transition records how many cells changed **and** saves a cropped before/after "
        "pair as the evidence for it. Hashing those pairs shows where the two disagree. "
        f"{frames['checked']} transitions had both crops on disk and were checked."
        f"{_cite('ontology')}", "",
        "**What a disagreement does and does not prove.** The cell count is measured over the "
        "whole frame at the recon grid, while the crop covers only that transition's "
        "`crop_box`. So identical crops do *not* prove the frame held still - the change may "
        "have happened outside the crop. What they prove is that **the saved evidence for "
        "that transition does not show the change it reports**, which for a transition read "
        "as a panel opening is the difference between a finding and an artefact.", "",
        "## Current state / findings", "",
        f"### {len(silent)} transitions report a change between byte-identical crops", "",
    ]
    if silent:
        body += ["| Transition | Route | Effect | Action | Cells reported changed |",
                 "|---|---|---|---|---|"]
        for row in silent:
            body.append(f"| {row['id']} | {row['from']} -> {row['to']} | {row['effect']} | "
                        f"`{row['action']}` | {row['changed_cells']} |")
    else:
        body.append("None - every transition that reports a change has crops that differ. "
                    "The saved evidence and the counts agree throughout this pass.")

    body += ["", f"### {len(unrecorded)} transitions report no change between crops that differ",
             ""]
    if unrecorded:
        body += ["| Transition | Route | Effect | Action |", "|---|---|---|---|"]
        for row in unrecorded:
            body.append(f"| {row['id']} | {row['from']} -> {row['to']} | {row['effect']} | "
                        f"`{row['action']}` |")
        body.append("")
        body.append("These are the cheaper error of the two: something moved inside the crop "
                    "and the whole-frame count was under its tolerance, which is what a "
                    "small local change looks like.")
    else:
        body.append("None.")

    body += ["", "## Implications", "",
             "- A transition in the first table should not be cited as evidence of anything "
             "without going back to the full frames, which this pass did not save for it.",
             "- The check is cheap and worth repeating on every pass, because it needs no "
             "model and no knowledge of the game - only the files the run already wrote.",
             "", _footnotes(ctx, ["ontology"])]
    return Page(rel="concepts/frames-vs-counts.md", kind="Quality Concept",
                title="Where the saved frames disagree with the counts",
                description=(f"Hashing {frames['checked']} before/after crop pairs found "
                             f"{len(silent)} transitions reporting a change between "
                             f"byte-identical frames."),
                body="\n".join(body), tags=["clash-royale", "evidence"])


def identity_page(data: dict, facts: Facts, ctx: Ctx, threshold_note: str) -> Page:
    session = data["session"]
    grid = session.get("grid") or ["?", "?"]
    weak = [s["id"] for s in facts.screens if s.get("identity_is_weak")]
    body = [
        "# How screen identity was decided", "",
        "## What it is", "",
        f"No screen in this wiki was named by hand. Every frame was reduced to a "
        f"{grid[0]}x{grid[1]} grid, compared against the appearances already stored, and "
        f"filed as the nearest one scoring at least "
        f"**{session.get('screen_match_threshold', '?')}** over its stable cells - or "
        f"registered as somewhere new. A cell counts as changed when it moves by more than "
        f"{session.get('cell_delta', '?')}.{_cite('ontology')}", "",
        threshold_note, "",
        "## Current state / findings", "",
        f"- Median match score among the frames that matched: "
        f"**{session.get('median_match_score', '?')}**.",
        f"- Screens split apart because the model's naming disagreed with the pixel match: "
        f"**{session.get('screens_split_by_name', 0)}**.",
        f"- Screens whose identity the run itself flags as weak: "
        f"**{len(weak)}**{' (' + ', '.join(weak) + ')' if weak else ''}.",
        f"- Stored appearances per screen ranges from "
        f"{min((len(s.get('variants') or []) for s in facts.screens), default=0)} to "
        f"{max((len(s.get('variants') or []) for s in facts.screens), default=0)}.",
        "",
        "### The four ways this produces identities a person would not draw", "",
        "1. **A modal over a screen is a different screen.** The comparison is over the whole "
        "frame, so a panel covering half of it scores below the threshold and gets its own id.",
        "2. **A screen that animates enough becomes several.** Cells that move on their own "
        "are masked out, but only once the run has seen them move; the first sighting is "
        "scored against everything.",
        "3. **Two screens sharing a large identical region can merge.** A persistent "
        "navigation bar is the same fraction of every screen that has one.",
        "4. **A stale stored appearance drifts.** Nothing is merged into a near match here, "
        "which is what stops that - but it means a genuinely changed screen appears as a new "
        "one rather than as a changed old one.",
        "",
        "## Implications", "",
        "- A screen id is a claim about pixels, not about what a player would call a place. "
        "Read the ids as the run's own filing system.",
        "- Any screen in the weak list above carries that doubt into every statement made "
        "about it elsewhere in this wiki.",
        "", _footnotes(ctx, ["ontology"])]
    return Page(rel="concepts/screen-identity.md", kind="Quality Concept",
                title="How screen identity was decided",
                description=(f"Screens were told apart on a {grid[0]}x{grid[1]} grid at "
                             f"threshold {session.get('screen_match_threshold', '?')}, with "
                             f"{len(weak)} identities the run itself flags as weak."),
                body="\n".join(body), tags=["clash-royale", "method"])


# --- assembly ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    workspace: Path
    pages: list[Path]
    facts: Facts
    log_entry: Path


def read_run(run_dir: Path) -> dict:
    path = run_dir / "ontology.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no ontology.json in {run_dir}. That file is the run, so there is nothing to "
            f"build a wiki from - which means the recon pass died before it wrote one.")
    return json.loads(path.read_text(encoding="utf-8"))


def derive(run_dir: Path, data: dict) -> Facts:
    return Facts(
        target=data.get("target") or {}, session=data.get("session") or {},
        screens=data.get("screens") or [], transitions=data.get("transitions") or [],
        graph=graph_facts(data), refusals=refusal_facts(data),
        persistent=persistent_facts(data), frames=frame_facts(run_dir, data),
        reach=reach_facts(data), clickable=clickable_facts(data))


def build(run_dir: Path, workspace: Path, *, generated_by: str, now: datetime | None = None,
          threshold_note: str = "") -> BuildResult:
    """Write the whole bundle. Overwrites pages, appends to the log.

    Pages are overwritten rather than merged because each one is wholly derived from one
    run - there is no hand-written content in any of them to preserve, and a merge would
    silently keep a statement about a screen this pass did not see. The log is the exception:
    it is the audit trail, so it only ever grows.
    """
    data = read_run(run_dir)
    facts = derive(run_dir, data)
    at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    day = at[:10]

    try:
        run_rel = run_dir.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        # A run directory outside the workspace still builds; its images just will not
        # resolve from the pages. Said plainly rather than silently producing broken links.
        run_rel = run_dir.resolve().as_posix()

    sources = [
        Source("ontology", f"{run_rel}/ontology.json",
               "The recon pass's own machine-readable map"),
        Source("report", f"{run_rel}/report.md", "The recon pass's own written report"),
    ]
    ctx = Ctx(run_rel=run_rel, generated_by=generated_by, at=at, sources=sources)
    report_text = (run_dir / "report.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "report.md").exists() else ""

    pages = [
        overview_page(data, facts, ctx, threshold_note),
        summary_page(data, facts, ctx, report_text),
        persistent_page(facts, ctx),
        navigation_page(facts, ctx),
        refusals_page(facts, ctx),
        frames_page(facts, ctx),
        identity_page(data, facts, ctx, threshold_note),
        clickable_page(facts, ctx),
    ] + [screen_page(screen, data, facts, ctx, run_dir) for screen in facts.screens]

    wiki = workspace / "wiki"
    for folder in ("summaries", "entities", "concepts", "log"):
        (wiki / folder).mkdir(parents=True, exist_ok=True)

    written = []
    for page in pages:
        target = wiki / page.rel
        text = frontmatter(page.kind, page.title, page.description,
                           generated_by=generated_by, at=at, sources=sources, tags=page.tags,
                           entity_kind=page.entity_kind)
        write(target, f"{text}\n\n{page.body.rstrip()}\n")
        written.append(target)

    log = wiki / "log" / f"{day}.md"
    if not log.exists():
        write(log,
              frontmatter("Log Entry", f"Log - {day}",
                          f"Operations run against this workspace on {day}.",
                          generated_by=generated_by, at=at, sources=[], tags=["log"])
              + f"\n\n# Log - {day}\n\n")
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"- **Build**: `{run_rel}` -> {len(written)} pages "
                     f"({len(facts.screens)} screens, {facts.graph['distinct_edges']} routes, "
                     f"{facts.refusals['blocked_total']} inputs declined) at {at}\n")

    config = workspace / "qpf.config.yml"
    if not config.exists():
        write(config, f'qpf:\n  customer: "{slug(facts.target.get("name", "target"))}"\n'
                      f"  language: en\n")

    return BuildResult(workspace=workspace, pages=written, facts=facts, log_entry=log)
