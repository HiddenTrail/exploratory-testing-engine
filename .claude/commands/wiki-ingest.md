---
description: Generate/update a product wiki in <dest> from raw material in <source>.
argument-hint: "<source-dir> [--dest <dir>]"
allowed-tools: Bash(node:*), Read, Write, Edit, Glob, Grep
---

Run the **Ingest** operation (per [AGENTS.md](../../AGENTS.md)) against an
arbitrary source/destination pair, not just the repo-root `wiki/`.

Arguments given: `$ARGUMENTS`

1. Parse `<source-dir>` (required, repo-relative, the folder holding raw
   material) and `--dest <dir>` (optional; default to a `wiki/` sibling of
   `<source-dir>`'s parent, e.g. `experiments/live-sut-poc/out` →
   `experiments/live-sut-poc/wiki`). If `<source-dir>` doesn't exist, say so
   and stop — don't guess a different path.
2. Ensure the destination workspace exists:
   - `<dest>/summaries/`, `<dest>/entities/`, `<dest>/concepts/`, `<dest>/log/`
   - a `qpf.config.yml` in `<dest>`'s **parent** directory (the `--dir` that
     `rebuild-index.mjs` needs) — if one isn't already there, create a minimal
     one: `qpf: { customer: "<dest-parent-slug>", language: en }`. Skip this
     if `<dest>` is the repo-root `wiki/`, which already has one.
   - `<dest>/index.md` — if missing, seed it from
     `.wiki-source/templates/wiki/index.md`.
3. List every file under `<source-dir>` (recursively). For each, apply the
   scope rule from [AGENTS.md](../../AGENTS.md) **"What counts as a raw
   source"**: in scope = product-facing material (specs, tickets, screenshots,
   design docs, instructions); out of scope = this repo's own testing
   machinery and past test-run results (adapter/engine code, `casting_log`,
   `bugs.json`, `output.json`, oracle/heuristic config). If a file's category
   is genuinely ambiguous, ask the user rather than guessing — don't silently
   include or exclude it.
4. For each in-scope file, read it **faithfully** (no invented facts) and
   write a page into `<dest>/summaries/` using
   `.wiki-source/templates/wiki/summary.md`'s structure — frontmatter with a
   non-empty `type`, a one-sentence `description`, `status: draft`,
   `generated: { by: human:<git user>, at: <ISO 8601 UTC> }`, and a `sources`
   entry whose `resource:` is the real repo-relative path (or the specific
   constant/section, if the source is embedded in a larger file). Prefix the
   page filename with the product/SUT slug if `<dest>` will ever hold more
   than one product's pages.
5. Create/update `<dest>/entities/` and `<dest>/concepts/` pages that
   synthesize across what was just ingested — this is where the actual
   product model gets built, not just a pile of digests. Cross-link with
   relative markdown links.
6. Regenerate the index:
   `node .wiki-source/scripts/rebuild-index.mjs --dir <dest's parent>`.
7. Append a line to `<dest>/log/<today>.md` (create from
   `.wiki-source/templates/wiki/log-entry.md` if absent) describing what was
   ingested from where.

Report the pages created/updated and any files you skipped as out-of-scope or
flagged as ambiguous.
