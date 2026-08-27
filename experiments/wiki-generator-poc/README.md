# Wiki Generator PoC

Proves the "wiki-ingest" mechanics described in the repo-root
[`AGENTS.md`](../../AGENTS.md) as real, testable code, instead of only an
interactive Claude Code slash command
([`.claude/commands/wiki-ingest.md`](../../.claude/commands/wiki-ingest.md)).
If this holds up, it graduates to `engine/wiki/` the way `token-purchase-poc`
became `engine/adapters/token_purchase` and `oracle-agent-poc` became
`engine/ontology` - proven here first, hardened there.

**This is a wiki about the product under test, not about this repo's own
testing machinery.** `raw/` holds only product-facing material a tester with
no prior knowledge would be handed: a spec, a ticket. Both files here are
transcribed verbatim from what's already known and validated elsewhere in
this project (`engine/adapters/token_purchase/adapter.py`'s
`API_SCHEMA_DOC`/`KNOWN_ACCOUNTS`, and `engine/bootstrap/jira_mock.py`'s
`PROJ-101`) - not rediscovered, not fabricated, and deliberately real files
on disk rather than string constants, so the generator has an actual
directory to point at.

## What it does

Two tool-forced LLM calls per run (same call→validate→retry shape every
experiment's `run_live.py` uses):

1. **Summarize** - one call per file under `--source`, producing a faithful
   `Source Summary` page.
2. **Synthesize** - one call across all the summaries just produced,
   producing a `Quality Concept` "product model" page - the point where
   combining sources tells you something neither told you alone.

Both calls return structured tool output; the actual markdown+frontmatter is
rendered deterministically in Python from that structure (same
"structured-call, deterministic-render" split as `engine/report.py`), not
generated as free-text markdown by the model.

## Running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
python generate.py
```

Defaults: `--source raw --dest results/wiki --product` (inferred from
`results`'s parent dir name, i.e. `wiki-generator-poc` unless overridden). To
point it at a different source/destination pair entirely:

```
python generate.py --source /path/to/raw/material --dest /path/to/wiki --product my-product
```

If `node` and this repo's `.wiki-source/scripts/rebuild-index.mjs` are
reachable, the run also regenerates `<dest>/index.md`; otherwise that step is
skipped with a warning, and the summary/concept pages are still written and
usable.

## Scope rule this inherits

Same as the repo-root `AGENTS.md`: in scope = specs, tickets, screenshots,
design docs, user-facing instructions - what a tester would actually be
handed. Out of scope = this repo's own engine/adapter code, oracle/heuristic
config, and past test-run results. This PoC doesn't classify files itself -
the caller is trusted to only point `--source` at a directory that's already
in-scope raw material (the interactive `/wiki-ingest` command does that
classification; this script assumes it already happened).

## What's not built here

- Recursive source directories (one flat level of files only).
- Entity pages (endpoints, known accounts, environments) - only
  Source Summary and one Quality Concept page per run.
- The in-scope/out-of-scope file classification `/wiki-ingest` does - see
  above.
- Non-text raw sources (screenshots/images) - `raw/` here is text-only; a real
  run against something like `live-sut-poc/out` may need vision input added.
