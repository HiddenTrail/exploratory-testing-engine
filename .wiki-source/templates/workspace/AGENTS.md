# {{CUSTOMER}} — Quality workspace (AGENTS.md)

This repository is a **Quality Playbook workspace**: engagement inputs and the
knowledge synthesized from them, from which we build this customer's **Quality
Guidelines** and per-team **Quality Playbooks**.

It is **self-contained and tool-agnostic**. Any LLM chat tool or editor can work with
it — everything is plain CommonMark markdown in git. Obsidian is only an optional
viewer; `.obsidian/` is gitignored. Use standard relative links `[text](path.md)`,
never `[[wikilinks]]`.

> Scaffolded by the Quality Playbook Factory tool v{{VERSION}}. Language: **{{LANGUAGE}}**
> (set once, in `qpf.config.yml`). All Guidelines and Playbooks render in that language.

## Layout (Karpathy LLM-Wiki model)

| Directory | Layer | What lives here |
|---|---|---|
| `raw/` | **Raw sources** (immutable) | Verbatim engagement inputs — never edited after capture |
| `wiki/` | **Wiki** (LLM-maintained) | Knowledge synthesized from raw sources |
| `guidelines/` | Rendered view | This customer's tailored Quality Guidelines |
| `playbooks/<team>/` | Rendered view | One Quality Playbook per team |

```
raw/{workshops,interviews,assessments,product,assets}/
wiki/{index.md,overview.md,log/,summaries/,entities/,concepts/}
guidelines/{guidelines.yml,guidelines.md}
playbooks/<team>/playbook.md
```

`guidelines/guidelines.yml` is the **source of truth** for the Guidelines (structured
`section/id/type/description`); `guidelines.md` is a rendered table — do not hand-edit
it. `wiki/index.md` is derived — do not hand-edit it either.

## The wiki is an OKF v0.2 bundle

`wiki/` is an **Open Knowledge Format (OKF) v0.2** bundle: its root is `wiki/`, every
`.md` under it except `index.md` is an OKF *concept document*, and `wiki/index.md` is
the root index (derived — do not hand-edit).

Conformance is only three rules, so keep them: every concept document has a **parseable
YAML frontmatter block** with a **non-empty `type`**, and `index.md` carries **no
frontmatter except `okf_version`**. Everything else below is recommended, not required —
a page missing an optional field is still valid, so never drop a page for that reason,
and tolerate keys and `type` values you don't recognize.

```yaml
---
type: Source Summary            # REQUIRED, non-empty. Descriptive, not registered.
title: <human title>
description: <one sentence>      # what wiki/index.md shows for this page
tags: []
status: draft                   # draft | stable | deprecated (absent ⇒ stable)
resource: <URI>                 # only when the page describes a real asset
generated: { by: human:<id>, at: <ISO 8601 UTC> }   # who wrote it, when
verified: { by: human:<id>, at: <ISO 8601 UTC> }    # who confirmed it, when
sources:
  - id: <short-key>             # join key for body footnotes: [^<short-key>]
    resource: raw/<file>        # REQUIRED within each entry
    title: <label>
stale_after: <ISO 8601 UTC>     # optional; content is stale on/after this instant
guidelines_refs: []             # QPF extension: related Guidelines IDs
---
```

Four things are easy to get wrong:

- **Every timestamp is a full ISO 8601 datetime with an explicit UTC offset**
  (`2026-08-25T09:00:00Z`). A bare `YYYY-MM-DD` is not conformant.
- **Actors are prefixed**: `human:<id>` for a person, `process:<id>` for automation,
  `<producer>/<version>` for an agent. Trust keys off the `human:` prefix — no
  `verified` at all means *unverified*, verified by non-humans only means
  *machine-confirmed*, and a `human:` verifier means *human-reviewed*. So record
  `verified` when a page is actually reviewed; that is the whole trust signal.
- **`generated.by` is who wrote it; `verified` is who confirmed it.** Content can
  change without re-confirmation, and be re-confirmed without changing.
- **Attribute claims with footnotes keyed to a `sources[].id`**, not by position:
  `The pipeline has no gate.[^kickoff]`. Agents rewrite these pages constantly, and a
  positional reference misattributes silently the moment the list is reordered.

Page types: **Source Summary** (`wiki/summaries/`, a digest of one raw source),
**Entity** (`wiki/entities/`, a person/role/team/system/tool/environment — kind in the
`entity_kind` extension field), **Quality Concept** (`wiki/concepts/`, a DoD, quality
gate, VSM finding, risk…), **Product Overview** (`wiki/overview.md`), and **Log Entry**
(`wiki/log/<date>.md`).

Links between pages are plain relative markdown links. OKF also allows bundle-absolute
`/…` links, but relative keeps pages readable in Obsidian and any plain editor. A link
is an *untyped* edge, so state what the relationship is in the surrounding prose; a
broken link is acceptable — it just means knowledge not yet written.

History lives in `wiki/log/<date>.md`, not the reserved `log.md`, so parallel operations
never write-conflict on one file. Those date files are therefore ordinary concept
documents and each carries a `type`.

The deliverables outside the bundle — `guidelines/` and `playbooks/` — keep their own
frontmatter (`type: guidelines | playbook`, `status`, `updated`) and are **not** part of
the OKF bundle.

## Operations

Run these against this workspace (the tool provides `/qpf-*` commands that wrap them;
they also work as plain instructions to any LLM):

1. **Ingest** — read a file in `raw/` → write a `summaries/` page → update `entities/`
   & `concepts/` → rebuild `index.md` → append a line to today's `log/` file.
2. **Query** — search `index.md`, read the linked pages, answer **with citations** to
   `raw/`/`wiki/` paths. Optionally file the answer back as a `concepts/` page.
3. **Build Guidelines** — start from the tailored `guidelines/guidelines.yml`, adjust
   MUST/SHOULD/OPTIONAL to this customer's maturity and findings, then re-render
   `guidelines.md`.
4. **Generate Playbook (per team)** — select items for the team (all MUST + chosen
   SHOULD/OPTIONAL), assemble the contract (§4), synthesize the other sections from the
   wiki, render to `playbooks/<team>/` in the workspace language. Items the team isn't
   ready for become **roadmap placeholders**.
5. **Lint** — contradictions, stale claims, orphans, missing cross-refs; **plus domain
   checks**: every MUST present in each playbook, each contract item traces to a
   Guidelines ID, roadmap items flagged, RACI complete.

## Collaboration

Two consultants share this repo via git. Most content is read-only, so conflicts are
rare. Do **writes** (ingest, guidelines, playbook) on a short branch → diff/PR review →
merge. Generation sets `status: draft`; the other consultant lint-checks and reads,
then sets `status: approved`.
