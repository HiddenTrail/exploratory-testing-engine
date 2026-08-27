---
description: Ingest a raw engagement source into the workspace wiki (summary + entities/concepts).
argument-hint: "<path to a file under raw/> (or leave blank to pick uningested sources)"
allowed-tools: Bash(node:*), Read, Write, Edit, Glob, Grep
---

Run the **Ingest** operation for the current QPF workspace (the cwd must be a
workspace — it has `qpf.config.yml` and `AGENTS.md`).

Target source: `$ARGUMENTS`

Steps:

1. If no path was given, list files under `raw/` that don't yet have a matching
   `wiki/summaries/` page, and ask which to ingest (or ingest all).
2. Read the raw source **faithfully**. Do not invent facts it doesn't contain.
3. Write a summary page to `wiki/summaries/<slug>.md` using the structure in
   `${CLAUDE_PLUGIN_ROOT}/templates/wiki/summary.md`. The wiki is an OKF v0.2 bundle, so
   the frontmatter must carry a non-empty `type` plus: a one-sentence `description`
   (this is what `wiki/index.md` shows), `status: draft`, `generated: { by: human:<id>,
   at: <ISO 8601 UTC> }` — a full timestamp with offset, not a bare date — and a
   `sources` **list of entries**, each with a REQUIRED `resource:` pointing at the raw
   path, plus an `id:` you cite from the body as a footnote (`[^<id>]`). Add `verified:`
   only when a human has actually confirmed the page; it is the trust signal, so never
   pre-fill it.
4. Create or update the relevant `wiki/entities/` (people, roles, teams, systems,
   tools, environments) and `wiki/concepts/` (DoD/DoR, quality gates, VSM findings,
   risks) pages — one entity/concept per file, cross-linked with relative links.
5. Regenerate the index: `node "${CLAUDE_PLUGIN_ROOT}/scripts/rebuild-index.mjs"`.
6. Append a one-line entry to `wiki/log/<today>.md` describing what was ingested and
   which pages were touched (create the file from the log-entry template if absent).

Honour the workspace language in `qpf.config.yml`. Do the writes on a short branch if
the pair's workflow calls for it. Report the pages you created/updated.
