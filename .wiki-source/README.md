# .wiki-source

Everything in here was copied from Hidden Trail's **Quality Playbook Factory (QPF)**
repo (`quality-playbook-factory`, sibling folder to this one) — specifically the parts
that implement its "Karpathy LLM Wiki" pattern: an LLM keeps a `wiki/` of markdown pages
synthesized from raw sources, instead of a human writing it by hand.

This folder is **reference material to replicate that pattern in this repo**
(`qes-exploration`), not a working workspace itself — nothing here runs against
`qes-exploration`'s own data yet.

## What's here and why

```
commands/
  qpf-init.md        the operation that scaffolds a wiki skeleton (dirs + starter files)
  qpf-ingest.md       the operation that turns one raw source into wiki pages
scripts/
  scaffold.mjs         creates the directory skeleton + seeds wiki/index.md, wiki/overview.md
  rebuild-index.mjs     regenerates wiki/index.md from the frontmatter of every wiki page
  lib/yaml.mjs          dependency-free YAML parser rebuild-index.mjs needs
templates/
  wiki/
    index.md           the derived root index template (OKF v0.2 bundle root)
    overview.md         product/service-at-a-glance page template
    summary.md           template for a "digest of one raw source" page
    entity.md             template for a person/role/team/system/tool/environment page
    concept.md             template for a quality-concept/finding page
    log-entry.md            template for one day's append-only operations log
  workspace/
    AGENTS.md           the schema doc: page types, frontmatter rules, operations
    CLAUDE.md             thin pointer so Claude Code also picks up AGENTS.md
```

These are QPF's actual, working files — not rewritten or simplified. `scaffold.mjs` and
`rebuild-index.mjs` are runnable as-is (`node`, no dependencies) once you adjust the
paths below.

## The pattern in one paragraph

A wiki here is an **[Open Knowledge Format (OKF) v0.2](templates/workspace/AGENTS.md)**
bundle: a `wiki/` directory where every `.md` file (except the derived `index.md`) is a
"concept document" with a YAML frontmatter block carrying at minimum a non-empty `type`.
Raw, immutable source material lives in `raw/` and is never edited. An LLM (or you)
reads a raw source and writes a wiki page that **cites it** via a `sources:` list in the
frontmatter, so every claim in the wiki traces back to something real. `wiki/index.md`
is regenerated from all the pages' frontmatter — never hand-edited.

Four page types cover it:

| Type | Where | Purpose |
|---|---|---|
| Source Summary | `wiki/summaries/` | A faithful digest of one raw source |
| Entity | `wiki/entities/` | One person/role/team/system/tool/environment |
| Quality Concept | `wiki/concepts/` | A finding, definition, gate, risk — anything conceptual |
| Product Overview | `wiki/overview.md` | The product/service at a glance |

Plus `wiki/log/<date>.md` — an append-only per-day record of what got ingested, split
by date so parallel writers never conflict on one file.

Full rules (frontmatter shape, timestamp format, trust/verification signals, linking
convention) are in [templates/workspace/AGENTS.md](templates/workspace/AGENTS.md) — read
that before writing your first page by hand.

## How to adapt this to qes-exploration

QPF's version is wired for a **quality-consulting engagement** (raw sources =
workshops/interviews/assessments; wiki feeds a Guidelines+Playbook generator). None of
that domain-specific framing is required — the wiki mechanics (raw → summary/entity/
concept pages → derived index) are generic. To stand up a wiki for **this** repo:

1. **Pick where raw sources live.** QPF uses `raw/{workshops,interviews,assessments,product,assets}`.
   For `qes-exploration` that's probably something like `raw/{experiments,runs,notes}` —
   whatever matches what's actually in `experiments/` and `runs/` today. Images and JSON
   files work fine as raw sources; an LLM with vision can summarize a screenshot the same
   way it summarizes a transcript, and JSON is just structured text to read faithfully.

2. **Adjust `scaffold.mjs`** (or just run it once and re-arrange): change the `dirs` array
   and the `raw/...` subfolders to match step 1, then run:
   ```
   node scripts/scaffold.mjs --customer "qes-exploration" --dir /c/Users/pmarj/qes-exploration --force
   ```
   `--force` is needed because the target isn't empty — check what it writes before
   committing; it won't touch existing files outside the specific paths it creates.
   Note it also writes `guidelines/` and a customer-flavored `AGENTS.md`/`CLAUDE.md`/
   `README.md`/`qpf.config.yml` — drop or rewrite whatever doesn't fit (the wiki/log/
   summaries/entities/concepts skeleton and `rebuild-index.mjs` are the reusable core;
   the Guidelines-tailoring machinery is QPF-specific and can be deleted).

3. **Strip the QPF-specific framing** from `templates/workspace/AGENTS.md` before adopting
   it here: drop the Guidelines/Playbook operations (§ "Build Guidelines", "Generate
   Playbook") and the customer/consultant-pair language, keep the OKF frontmatter rules,
   page-type table, and the Ingest/Query operations — those are the generic wiki contract.

4. **Ingest sources** by following the same steps as [commands/qpf-ingest.md](commands/qpf-ingest.md):
   read one raw file faithfully, write a page from the matching template into
   `wiki/summaries/` (or `entities/`/`concepts/` as appropriate), cite the raw file in
   `sources:`, then run `node scripts/rebuild-index.mjs --dir <workspace>` to regenerate
   `wiki/index.md`. `rebuild-index.mjs` also tries to render `guidelines/guidelines.yml` —
   harmless no-op if that file doesn't exist, it just prints a warning and skips it.

5. **Log it.** Append one line to `wiki/log/<today>.md` per ingest run so there's an audit
   trail of what got added and from what source.

## What's deliberately not copied

`standards/`, `templates/playbook/`, `templates/ingest/`, and the `/qpf-guidelines` /
`/qpf-playbook` / `/qpf-lint` commands were left out — they're the Guidelines-and-Playbook
generation layer built *on top of* the wiki, specific to Hidden Trail's consulting
product. Nothing here needs them; they're only worth pulling in later if
`qes-exploration` ends up wanting that same "tailored conventions doc per audience"
output, not just a synthesized knowledge base.
