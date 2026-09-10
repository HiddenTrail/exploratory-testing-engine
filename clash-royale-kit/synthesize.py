"""Three analysis pages a model writes, from measurements only, with the citation checked.

What this is for, and what it is not
------------------------------------
The deterministic builder next door can say what the run measured. It cannot say what the
*shape* of those measurements means - that a graph with four routes and one sink implies a
particular thing about how this interface is organised, or that six refusals clustered on
three controls describes a monetisation surface. That is synthesis, and it is the one part of
the old hand-built wiki that genuinely needed a model.

So this is a fixed number of calls - three, one per page - and it is nothing like the agent it
replaces. No code is written. No file is edited except the three pages named below. The model
never sees the run's images, the client, or a shell. It is handed a JSON digest of numbers
somebody else measured and asked, through a forced tool schema, to argue about them.

The citation rule is the whole design
-------------------------------------
Every claim must name the measurement keys it rests on, and those keys are validated against
the digest that was actually sent. A claim citing `refusals.by_reason` passes; a claim citing
a field that does not exist is rejected and fed back for correction. This is a real constraint,
not a formality: the failure mode of asking a model to interpret a game's interface is that it
writes what it knows about Clash Royale in general, which reads perfectly and describes a
client nobody measured. A claim that cannot point at a number in the digest is exactly that
claim, and it does not survive validation.

Two more fields exist for the same reason. `confidence` is per claim rather than per page,
because a page whose overall tone is hedged still launders its individual overreaches.
And `unsupported` asks outright for the things the model wanted to say and could not - which is
the most useful paragraph on each of these pages, because it is a list of what a longer pass
would be for.

The budget is fixed and the failure is soft
-------------------------------------------
Three calls, capped tokens, no loop that decides to make a fourth. If credentials are absent or
a call fails, the deterministic wiki is already complete and correct - so this reports what it
could not do and returns, rather than taking the whole build down. That asymmetry is deliberate:
the pages this writes are commentary, and commentary is not worth failing a run over.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wikibuild  # noqa: E402

# Per call. Enough for three sections of real argument and not enough for an essay; the
# validator rejects a truncated answer with the *actionable* correction ("be shorter") rather
# than "be correct", which `engine/client.py` explains at the place it matters.
MAX_TOKENS = 3000

# Free-text length caps, enforced by the validator rather than requested in the prompt.
# A length asked for politely is a length the model averages over; a length validated is a
# length that comes back.
MAX_PARAGRAPH = 900
MAX_SUMMARY = 300

# `SystemExit` is in here, and it is not paranoia. `engine.client.build_client` raises
# `SystemExit` - not a subclass of `Exception` - when `ENGINE_USE_BEDROCK` is set with no region
# configured, which is the single likeliest thing to go wrong on a machine this kit is new to.
# An `except Exception` around it lets exactly that case take the whole build down after the
# deterministic wiki was already written, which is the opposite of what soft failure means.
# `KeyboardInterrupt` is deliberately not included: an operator pressing Ctrl-C means stop.
SOFT_FAILURES = (Exception, SystemExit)


def _tool(name: str, description: str) -> dict:
    """One page's schema. Identical shape for all three, because the differences are prompts.

    `evidence_keys` is `required` on every claim, which is what makes the citation rule
    enforceable rather than advisory. A model that has nothing to cite has to either drop the
    claim or move it to `unsupported`, and both of those are better pages than a confident
    sentence about a client nobody measured.
    """
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string",
                          "description": "A page title in plain words. No colons, no commas."},
                "summary": {"type": "string",
                            "description": ("One sentence, under 300 characters, saying what "
                                            "this page concludes. Not what it is about.")},
                "sections": {
                    "type": "array", "minItems": 2, "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "paragraphs": {"type": "array", "minItems": 1, "maxItems": 3,
                                           "items": {"type": "string"}},
                        },
                        "required": ["heading", "paragraphs"],
                    },
                },
                "claims": {
                    "type": "array", "minItems": 2, "maxItems": 6,
                    "description": ("Each specific enough to be wrong. A claim nothing in the "
                                    "digest could contradict belongs in `unsupported`."),
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string"},
                            "evidence_keys": {
                                "type": "array", "minItems": 1,
                                "items": {"type": "string"},
                                "description": ("Keys from the citable list, exactly as "
                                                "written there. A key not on the list is "
                                                "rejected."),
                            },
                            "confidence": {"type": "string",
                                           "enum": ["measured", "inferred", "speculative"],
                                           "description": ("measured: the digest states it. "
                                                           "inferred: it follows from what the "
                                                           "digest states. speculative: it is "
                                                           "a guess consistent with it.")},
                            "rival": {"type": "string",
                                      "description": ("The most plausible other explanation "
                                                      "for the same numbers.")},
                        },
                        "required": ["claim", "evidence_keys", "confidence", "rival"],
                    },
                },
                "unsupported": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "description": ("Things you wanted to say and the digest does not support. "
                                    "Name what measurement would settle each one."),
                    "items": {"type": "string"},
                },
            },
            "required": ["title", "summary", "sections", "claims", "unsupported"],
        },
    }


SYSTEM = """You are writing one page of a wiki about a live game client, from a JSON digest of
one automated exploration pass. You have not seen the client. You have not seen its images.

The digest is the only thing you know about this target. Anything you know about this game from
elsewhere is inadmissible here: the pass ran against one account on one day, and a statement
that is true of the game in general but not of these measurements makes the wiki confidently
wrong in a way nobody downstream can detect.

Every claim must cite `evidence_keys` drawn from the citable-keys list in the message. Keys are
checked against the digest that was actually sent; an invented key is rejected. If you want to
say something you cannot cite, put it in `unsupported` and name the measurement that would
settle it - that field is read, and it is the most useful part of the page.

Mark each claim's confidence honestly. `measured` means the digest states it outright.
`inferred` means it follows from what the digest states. `speculative` means it is a guess
consistent with the digest. Prefer fewer, sharper claims over more, hedged ones, and give each
one the most plausible rival explanation for the same numbers.

Write in plain declarative prose. No marketing tone, no bullet-point summaries of what you just
said, no restating the question. Assume the reader can see the numbers."""


@dataclass(frozen=True)
class PageSpec:
    """One synthesis page: where it goes, what it is asked, and what it is called."""
    rel: str
    tool: str
    tags: list[str]
    ask: str


PAGES = (
    PageSpec(
        rel="concepts/what-this-interface-is-for.md", tool="interface_shape",
        tags=["clash-royale", "analysis", "navigation"],
        ask=("What is this interface organised to do, judging only from the screens the pass "
             "found, what it says they are for, and the shape of the routes between them? "
             "Attend to the graph: which screen everything returns through, which screens are "
             "one tap from it, what a sink implies about how the interface expects to be left. "
             "Do not describe the game's rules - you have no evidence about those. Describe the "
             "structure the measurements show.")),
    PageSpec(
        rel="concepts/where-this-target-asks-for-money.md", tool="monetisation_surface",
        tags=["clash-royale", "analysis", "safety"],
        ask=("Where does this interface ask the account holder to spend something? Use the "
             "refusal reasons, the element labels and what the vetting call said about specific "
             "controls. Two things are worth separating: currency the account already has, and "
             "money that leaves a bank. Then say what the refusals imply about how close an "
             "automated pass gets to a purchase by accident - and be careful, because a low "
             "count of refusals is also what a pass that never reached anything risky looks "
             "like.")),
    PageSpec(
        rel="concepts/where-this-map-is-weakest.md", tool="map_weakness",
        tags=["clash-royale", "analysis", "coverage"],
        ask=("Where should the next pass be spent, and why? Use the coverage numbers, the "
             "screens whose identity the run flags as weak, the screens nothing was seen to "
             "enter, and any transition whose saved frames disagree with its own cell count. "
             "Rank by what would change a conclusion in this wiki if it turned out otherwise, "
             "not by what is merely unmeasured.")),
)


def digest(facts: wikibuild.Facts, threshold_note: str = "") -> dict:
    """The numbers a synthesis call is allowed to reason from.

    Deliberately not the whole `ontology.json`. Two reasons, and the second is the important
    one. It would not fit; and a model handed raw fingerprint bytes and image paths starts
    reasoning about files it cannot open, then cites them. Everything here is a number or a
    string the run itself wrote, and every key is citable - which is what makes the citation
    check mean something rather than being a list of names to pick from.
    """
    return {
        "target": {"name": facts.target.get("name", ""),
                   "client": facts.target.get("client", [])},
        "session": {key: facts.session.get(key) for key in
                    ("seconds", "actions", "stopped", "restarts", "vetted_by_model",
                     "clicks_enabled", "screen_match_threshold", "cell_delta",
                     "median_match_score", "screens_split_by_name", "notes")},
        "screens": [{"id": screen["id"], "name": screen.get("name", ""),
                     "purpose": screen.get("purpose", ""),
                     "observations": screen.get("observations", 0),
                     "identity_is_weak": bool(screen.get("identity_is_weak")),
                     "stable_cells": screen.get("stable_cells", 0),
                     "animated_cells": screen.get("animated_cells", 0),
                     "elements": [{"label": element.get("label", ""),
                                   "what": element.get("what", ""),
                                   "located": element.get("located", "described")}
                                  for element in (screen.get("elements") or [])]}
                    for screen in facts.screens],
        "graph": {key: facts.graph[key] for key in
                  ("edges", "distinct_edges", "start", "sinks", "never_entered", "isolated",
                   "unreachable_from_start", "variant_edges", "inert_edges")},
        "refusals": facts.refusals,
        "coverage": {"named": facts.reach["named"], "activated": facts.reach["activated"],
                     "never_activated": facts.reach["never_activated"],
                     "per_screen": facts.reach["per_screen"]},
        "persistent": {"repeated": facts.persistent["repeated"]},
        "frames": {"checked": facts.frames["checked"],
                   "identical_crops_nonzero_count":
                       facts.frames["identical_crops_nonzero_count"],
                   "differing_crops_zero_count": facts.frames["differing_crops_zero_count"]},
        "threshold_note": threshold_note,
    }


def citable(payload: dict) -> set[str]:
    """Every dotted path in the digest, to one level of nesting, as the citation vocabulary.

    One level rather than every leaf: `screens[3].elements[7].label` is a path nobody types
    correctly and rejecting a claim over an off-by-one index would punish the wrong thing. A
    claim citing `screens` is pointing at the screen list, which is enough for a reader to check
    it. Leaf-level precision would be better if it were achievable; it is not, and a rule that
    rejects good claims for clerical reasons trains the model to cite the one key it knows works.
    """
    keys = set()
    for top, value in payload.items():
        keys.add(top)
        if isinstance(value, dict):
            keys.update(f"{top}.{inner}" for inner in value)
    return keys


def validator(allowed: set[str]):
    """Reject an answer the wiki cannot honestly render, and say which part.

    Every message here is fed back to the model verbatim on retry, so each one is written as an
    instruction rather than as a complaint - a validator that says "invalid claims" buys three
    identical failures, while one that says "claim 2 cites 'monetisation' which is not a key;
    the keys are ..." gets a corrected answer on the second attempt.
    """
    def validate(payload: dict) -> list[str]:
        errors = []
        for field in ("title", "summary", "sections", "claims", "unsupported"):
            if not payload.get(field):
                errors.append(f"'{field}' is missing or empty")
        if errors:
            return errors

        if len(payload["summary"]) > MAX_SUMMARY:
            errors.append(f"'summary' is {len(payload['summary'])} characters, over the "
                          f"{MAX_SUMMARY} limit - cut it to one sentence")
        if "\n" in payload["title"] or '"' in payload["title"]:
            errors.append("'title' must be one line with no double quotes")

        for index, section in enumerate(payload["sections"], 1):
            if not section.get("heading") or not section.get("paragraphs"):
                errors.append(f"section {index} is missing a heading or its paragraphs")
                continue
            for paragraph in section["paragraphs"]:
                if len(paragraph) > MAX_PARAGRAPH:
                    errors.append(f"a paragraph in section {index} is {len(paragraph)} "
                                  f"characters, over the {MAX_PARAGRAPH} limit - split or cut it")

        for index, claim in enumerate(payload["claims"], 1):
            if not claim.get("claim") or not claim.get("rival"):
                errors.append(f"claim {index} is missing its text or its rival explanation")
            if claim.get("confidence") not in ("measured", "inferred", "speculative"):
                errors.append(f"claim {index} has confidence {claim.get('confidence')!r}, which "
                              f"must be measured, inferred or speculative")
            unknown = [key for key in (claim.get("evidence_keys") or []) if key not in allowed]
            if not claim.get("evidence_keys"):
                errors.append(f"claim {index} cites no evidence_keys. Every claim must cite at "
                              f"least one key from the citable list, or move to 'unsupported'")
            elif unknown:
                errors.append(
                    f"claim {index} cites {unknown}, which are not keys in the digest. "
                    f"The citable keys are: {', '.join(sorted(allowed))}")
        return errors
    return validate


def render(payload: dict, spec: PageSpec, run_rel: str) -> wikibuild.Page:
    """The model's structured answer as a page, with the citations left visible.

    The claims table is rendered rather than woven into the prose on purpose. A claim inside a
    paragraph carries its confidence as tone, which is exactly how a `speculative` reading gets
    read as a finding three months later; a claim in a row next to the word `speculative` and
    the key it rests on does not.
    """
    body = [f"# {wikibuild.one_line(payload['title'])}", "",
            wikibuild.one_line(payload["summary"]), ""]
    for section in payload["sections"]:
        body += [f"## {wikibuild.one_line(section['heading'])}", ""]
        body += [f"{wikibuild.one_line(paragraph)}\n" for paragraph in section["paragraphs"]]

    body += ["## Claims, and what each rests on", "",
             "Each row cites the part of the run's own digest it was drawn from, and names the "
             "most plausible other reading of the same numbers. `measured` means the run states "
             "it; `inferred` means it follows; `speculative` means it is a guess consistent "
             "with the measurements and nothing more.", "",
             "| Claim | Confidence | Rests on | Most plausible rival |", "|---|---|---|---|"]
    for claim in payload["claims"]:
        keys = ", ".join(f"`{key}`" for key in claim["evidence_keys"])
        body.append(f"| {wikibuild.one_line(claim['claim'])} | {claim['confidence']} | {keys} "
                    f"| {wikibuild.one_line(claim.get('rival', '-'))} |")

    body += ["", "## What the measurements could not settle", "",
             "Asked for outright, because it is the list of what a longer pass would be for.",
             ""]
    body += [f"- {wikibuild.one_line(item)}" for item in payload["unsupported"]]
    body += ["", "---", "",
             f"Written from `{run_rel}/ontology.json` by one schema-forced model call over a "
             f"digest of that run's measurements. No image, no client and no other source was "
             f"available to it, and every claim above cites a key from that digest.", ""]

    return wikibuild.Page(rel=spec.rel, kind="Quality Concept",
                          title=wikibuild.one_line(payload["title"]),
                          description=wikibuild.one_line(payload["summary"])[:280],
                          body="\n".join(body), tags=spec.tags)


@dataclass
class SynthesisResult:
    pages: list[Path]
    skipped: list[str]
    model: str = ""


def run(facts: wikibuild.Facts, workspace: Path, run_rel: str, *, generated_by: str,
        threshold_note: str = "", now: datetime | None = None,
        client=None, model: str = "") -> SynthesisResult:
    """Write the three analysis pages. Never raises; reports what it could not do.

    Soft failure is the point. By the time this runs the deterministic wiki is complete and
    correct, and these three pages are commentary on it - so a missing credential, an expired
    SSO session or a model that will not produce a valid answer costs three pages, not a
    five-minute pass over somebody's live account.
    """
    at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = digest(facts, threshold_note)
    allowed = citable(payload)
    sources = [wikibuild.Source("ontology", f"{run_rel}/ontology.json",
                               "The recon pass's own machine-readable map")]
    written, skipped = [], []

    if client is None:
        try:
            from engine.client import build_client, default_model
            client, model = build_client(), model or default_model()
        except SOFT_FAILURES as error:                                    # noqa: BLE001
            return SynthesisResult(pages=[], skipped=[
                f"all three analysis pages: no model client could be built ({error}). The "
                f"deterministic wiki is complete without them - set ENGINE_USE_BEDROCK=1 and "
                f"AWS_REGION, or ANTHROPIC_API_KEY, and re-run with --synthesize to add them."])

    from engine.client import call_tool_with_retry
    evidence = json.dumps(payload, indent=1, default=str)

    for spec in PAGES:
        tool = _tool(spec.tool, spec.ask)
        message = (f"{spec.ask}\n\n"
                   f"Citable keys, exactly as written - anything else is rejected:\n"
                   f"{chr(10).join('  ' + key for key in sorted(allowed))}\n\n"
                   f"The digest:\n```json\n{evidence}\n```")
        try:
            answer = call_tool_with_retry(
                client, model=model, system=SYSTEM, tools=[tool], tool_name=spec.tool,
                user_message=message, validate_fn=validator(allowed), max_tokens=MAX_TOKENS)
        except SOFT_FAILURES as error:                                    # noqa: BLE001
            skipped.append(f"{spec.rel}: {type(error).__name__}: {error}")
            continue

        page = render(answer, spec, run_rel)
        target = workspace / "wiki" / page.rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # Through `wikibuild.write` for the line endings: these land in the same bundle and are
        # read by the same renderer, which a stray \r crashes. See that function.
        wikibuild.write(
            target,
            wikibuild.frontmatter(page.kind, page.title, page.description,
                                  generated_by=generated_by, at=at, sources=sources,
                                  tags=page.tags)
            + f"\n\n{page.body.rstrip()}\n")
        written.append(target)

    return SynthesisResult(pages=written, skipped=skipped, model=model)
