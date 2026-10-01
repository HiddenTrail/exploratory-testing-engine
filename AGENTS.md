# qes-exploration — Wiki (AGENTS.md)

This wiki's purpose is a **model of the product(s) under test** — not of this
repo's own testing engine. It's built the way a new tester would actually be
onboarded: from specs, instructions, JIRA tickets, and screenshots of the
product, synthesized into pages an LLM (or a person) can read to understand
what the product is and does before testing it. Pattern origin and full
mechanics: [.wiki-source/README.md](.wiki-source/README.md).

Everything is plain CommonMark markdown in git, tool-agnostic. Use standard
relative links `[text](path.md)`, never `[[wikilinks]]`.

## What counts as a raw source (and what doesn't)

**In scope** — anything a tester with no prior knowledge of the product would
be handed to learn what it is: a published API/spec doc, a JIRA ticket
describing intent or a bug, a screenshot or recording of the UI, a design doc,
user-facing instructions. It doesn't matter where that material physically
sits in this repo — a genuine product doc embedded as a string constant in an
adapter file (e.g. `API_SCHEMA_DOC` in `engine/adapters/<sut>/adapter.py`) is
in scope for exactly what it documents; cite the specific constant, not the
file's surrounding code.

**Out of scope** — this repo's own testing machinery: engine/adapter
implementation code, oracle/heuristic config, prioritization logic, and past
test-run results (`casting_log`, `bugs.json`, `output.json`, `runs/…`). Those
describe *how we test*, not *what the product is* — a test result belongs in
`context_<sut>.json` (the ontology layer), never in this wiki. If a page here
needs to reference one for context, say so in prose and link out; don't ingest
it as a `sources[]` entry.

When several products/SUTs are modeled here, prefix each page's filename with
the product's slug (`token-purchase-api-spec.md`, not `api-spec.md`) so pages
for different products coexist in the same `summaries/`/`concepts/` pool
without colliding.

## Layout

```
wiki/{index.md,overview.md,summaries/,entities/,concepts/,log/}
```

`wiki/index.md` is **derived** — regenerate with
`node .wiki-source/scripts/rebuild-index.mjs --dir .`, do not hand-edit it.

## The wiki is an OKF v0.2 bundle

`wiki/` is an **Open Knowledge Format (OKF) v0.2** bundle: its root is `wiki/`,
every `.md` under it except `index.md` is an OKF *concept document*, and
`wiki/index.md` is the root index (derived).

Conformance is only three rules: every concept document has a **parseable YAML
frontmatter block** with a **non-empty `type`**, and `index.md` carries **no
frontmatter except `okf_version`**. Everything else is recommended, not
required — a page missing an optional field is still valid.

```yaml
---
type: Source Summary            # REQUIRED, non-empty. Descriptive, not registered.
title: <human title>
description: <one sentence>      # what wiki/index.md shows for this page
tags: []
status: draft                   # draft | stable | deprecated (absent ⇒ stable)
generated: { by: human:<id>, at: <ISO 8601 UTC> }   # who wrote it, when
verified: { by: human:<id>, at: <ISO 8601 UTC> }    # who confirmed it, when
sources:
  - id: <short-key>             # join key for body footnotes: [^<short-key>]
    resource: <repo-relative path to the real source>   # REQUIRED per entry
    title: <label>
stale_after: <ISO 8601 UTC>     # optional; content is stale on/after this instant
---
```

Four things are easy to get wrong:

- **Every timestamp is a full ISO 8601 datetime with an explicit UTC offset**
  (`2026-08-25T09:00:00Z`). A bare `YYYY-MM-DD` is not conformant.
- **Actors are prefixed**: `human:<id>` for a person, `process:<id>` for
  automation, `<producer>/<version>` for an agent. No `verified` at all means
  *unverified*; a `human:` verifier means *human-reviewed*.
- **`generated.by` is who wrote it; `verified` is who confirmed it.** Content
  can change without re-confirmation, and be re-confirmed without changing.
- **Attribute claims with footnotes keyed to a `sources[].id`**, not by
  position: `The layer has no gate.[^todo]`. A positional reference
  misattributes silently the moment the list is reordered.

Page types in use here:

- **Product Overview** (`wiki/overview.md`, singular) — the product at a
  glance: what it is, who/what it serves, its main capabilities. One per
  product; if this wiki ever covers more than one product, split into
  `wiki/overview-<product-slug>.md` instead and list all of them from
  `wiki/overview.md`.
- **Source Summary** (`wiki/summaries/`) — a faithful digest of *one* raw
  source (one spec, one ticket, one screenshot).
- **Entity** (`wiki/entities/`) — one concrete thing the product is made of or
  interacts with, worth its own page because other pages will reference it
  repeatedly: an endpoint, a known test account, a role, an environment. Kind
  goes in the `entity_kind` frontmatter extension.
- **Quality Concept** (`wiki/concepts/`) — a finding, mechanism, behavior, or
  open question synthesized across *multiple* sources — this is where the
  actual "product model" gets assembled from the raw digests.
- **Log Entry** (`wiki/log/<date>.md`) — append-only audit trail of what got
  ingested and when.

`raw/` material for this wiki is **not copied into a `raw/` folder** — the
genuine product-facing sources already live where they are (see scope rules
above); `sources[].resource` points straight at the real repo-relative path
(or the specific constant/section within a file).

The exception is a source that can't be committed as it is. Spoor's map lives
in the gitignored `.spoor-cache/`, which holds raw captures with secrets. For
that, commit a trimmed export in `docs/product-sources/` (screens, controls,
transitions, no captures) and cite the export. Screenshots of a local test
target can be copied there too, a few at a time, when a page needs what they
show.

## The product layer: what the oracle reads

The engine builds each product's oracle from this wiki (issue #138, see
`engine/ontology/product.py` and `seeder.py`), so a product's pages carry three
extra frontmatter fields:

- **`product`** (the Product Overview and every Entity page about it): the
  product's slug, e.g. `juice-shop`. The overview also gets **`surfaces`**,
  e.g. `[gui]`.
- **`features`** (Entity pages): what the thing has, as tags from
  `engine/ontology/heuristics/vocabulary.json`, e.g. `[login, form]`. These
  decide which heuristics the oracle applies to it.
- **`facts`** (Entity pages): short checkable statements, each with an `id`
  unique on the page (`F1`), a `kind` from the vocabulary's `fact_kinds`
  (`claimed`, `shown`, `rule`, `standard`), its `text`, and the `source`: one
  of the page's `sources[].id`. A fact's global id is
  `<product>.<page>.<id>`, e.g. `juice-shop.product-list.F2`. A `claimed`
  fact is anything the product claims, wherever it says it: a spec or help text,
  its own pages and messages, marketing, emails to customers, promises.

```yaml
product: juice-shop
features: [list-paging, money]
facts:
  - id: F2
    kind: shown
    text: Apple Juice (1000ml) costs 1.99¤ in the list.
    source: screens
```

A fact is held to the same rule as the rest of the page: it says only what its
source says. `engine/tests/test_seeded_oracle.py` checks the fields.

## Operations

1. **Ingest** — read one in-scope raw source **faithfully** (no invented
   facts, nothing from out-of-scope engine/test-result material) → write a
   `summaries/` page → update/create `entities/` and `concepts/` pages that
   synthesize it with what's already known → regenerate `index.md` → append a
   line to today's `log/` file.
2. **Query** — search `index.md`, read the linked pages, answer **with
   citations** to the real source paths. Optionally file the answer back as a
   `concepts/` page.
