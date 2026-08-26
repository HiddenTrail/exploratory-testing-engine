# TODO — Evaluate CocoIndex as a RAG layer

Tracking plan for [cocoindex.io](https://cocoindex.io) (open-source ETL framework for
building incrementally-indexed retrieval pipelines) as a possible RAG layer for this
project. Not started — spike first, no commitment to adopt.

## Why this might matter here

Several pieces of the engine involve "throw relevant context at an LLM call," which is
exactly RAG's problem shape:

- [[context-enriched-bootstrap-roadmap]] phases 1–2 currently thread a whole
  `--context-file` string straight into probing/generation. That's fine for one short
  file, but stops working once context sources grow (multiple docs, a large OpenAPI
  spec, ticket history) — retrieval over chunks becomes necessary instead of a raw
  string dump.
- Phase 3/4 of that same roadmap (mocked, then real, JIRA source) will pull in ticket
  descriptions *and comments* — a corpus that grows over time and benefits from
  incremental indexing rather than re-reading everything per run.
- The oracle layer's spec-conformance oracle (`docs/exploratory-testing-engine-concept.md`
  §3.4) needs to ground judgments in "documented behavior" — retrieval over indexed
  specs/docs is a more scalable version of hand-passing a schema string.
- State memory / anomaly history (§3.3, §3.5) is itself a growing corpus that future
  hypothesis generation could retrieve against ("has something like this anomaly been
  seen before?").

## Open question to resolve before committing (do this first)

Is a real retrieval pipeline justified yet, or is this premature? Today's context
inputs are small (one ticket, one context file) — simple truncation/concatenation may
outperform RAG's added complexity (embeddings, vector store, incremental-sync
machinery) until the corpus is actually large enough that relevance filtering matters.
Don't build phases 1+ below until this is answered with a real corpus size estimate.

## Phased plan (mirrors the existing bootstrap-roadmap style: validate small, then generalize)

1. **Spike.** Install `cocoindex`, index a small local doc set (this repo's `docs/`
   plus one sample OpenAPI spec), confirm incremental reindex works on a file edit,
   and do a manual relevance check against a handful of test queries. No wiring into
   the engine yet — throwaway script only.
2. **Wire into bootstrap probing.** If the spike looks worthwhile, replace the raw
   `--context-file` text dump in `engine/bootstrap/probe.py` with a retrieval call
   over an indexed version of that same context, so the prober gets ranked relevant
   chunks instead of everything.
3. **Extend into generation.** Same retrieval interface feeding
   `generate_adapter_source` (`engine/bootstrap/generate.py`), so generated adapters
   can pull from a larger indexed corpus (multiple docs, prior adapters) instead of
   just the one context string.
4. **Index the mocked JIRA ticket store** (roadmap phase 3) through the same
   retrieval interface, proving the abstraction holds for a ticket-shaped source
   before real JIRA (phase 4) is even attempted.
5. **Real JIRA, continuously indexed** (roadmap phase 4) — only after phase 4 of the
   existing roadmap is explicitly greenlit; index ticket + comment updates
   incrementally rather than re-fetching/re-embedding everything per run.

## Explicit non-goals for now

- No vector DB / embedding model selection yet — that's a phase-1 decision, not now.
- No changes to `probe.py` / `generate.py` signatures until the spike (step 1) proves
  retrieval actually beats plain text concatenation on this project's real corpus size.
