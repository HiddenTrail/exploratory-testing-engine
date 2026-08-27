# TODO — Ontology layer (Phase 0)

Tracking plan for the 4-layer ontology stack under `engine/ontology/` — a
prioritization layer sitting between the domain-grounded oracle claims and
the Driver, plus a heuristic library and a context/results feed. See
`docs/exploratory-testing-engine-concept.md` for the original vision and
`/memories/repo/ontology-phase0-status.md` for the full session history that
led here.

## Status: Phase 0 proven on `token_purchase`; claim-matching gap fixed

The 4 layers exist as flat JSON files, wired together by
`engine/ontology/oracle_creator.py`, rendered by `engine/ontology/website.py`,
and the Driver has been live-run once against them end to end:

1. `heuristics.json` — generic, domain-agnostic heuristic vocabulary (Goldilocks,
   boundary edges, monetary precision, sensitive-data exposure, etc.)
2. `domain_<sut>.json` — per-SUT business/domain facts (schema, known accounts,
   business rules), extracted out of the adapter
3. `context_<sut>.json` — test results / jira entries / risk assessments
4. `oracle_creator.py` — scores and ranks domain claims + heuristic probes using
   what layer 3 says about each claim (untested / confirmed / refuted / jira-matched),
   generic probes always fill in behind grounded claims

`token_purchase`'s adapter now surfaces the top-15 ranked ideas (`ORACLE_RANKED`)
in its onboarding evidence, and `engine/ontology/feedback.py` writes a completed
Driver run's results back into `context_<sut>.json`.

## Resolved gap — claim matching was exact-string only

Confirmed live: after a real Driver run (2 checkpoints, 3 tests/round), the
ranking did **not** shift, because `oracle_creator.score_grounded_claim` matched
a test result to an oracle claim by exact string equality — but the Driver's
`linked_hypothesis` is free text it writes itself, never verbatim equal to the
oracle's claim text, even when it's clearly testing the same thing.

Fixed by giving every domain claim a stable, deterministic id
(`load_domain_claims` in `engine/ontology/oracle_creator.py`, e.g.
`claim:data:03`; generic heuristics reuse their existing `heuristics.json`
id as `heuristic:<id>`) and threading a new `oracle_claim_id` field through
the casting tool schema: the Driver still writes `linked_hypothesis` as its
own free-text theory (unchanged, still used by the report/Skeptic), but when
a test is meant to test one of the ranked ideas shown in its evidence, it now
also cites that idea's id verbatim. `engine/loop.py` persists
`oracle_claim_id` into `casting_log`; `engine/ontology/feedback.py` only
carries forward results that have one (a pure edge-case probe or an
off-list hypothesis has nothing to reprioritize); `oracle_creator.py` matches
on that id instead of on claim text. Covered by
`engine/tests/test_ontology_claim_matching.py`, including an end-to-end case
proving a merged result actually changes a claim's score.
`context_token_purchase.json`'s prior demo `test_results` were cleared since
they were keyed by claim text under the old, non-functional scheme.

## Backlog (not yet started)

1. **Skeptic-guided case selection.** Right now the Driver just pulls from the
   top of the ranked list. The Skeptic should instead steer which prioritized
   cases get run next, based on what still needs proving/disproving for the
   current hypothesis — not a fixed top-N pull.
2. **Driver/Skeptic output verbosity.** Free-text reasoning/hypothesis/critique
   fields are very large per checkpoint. Needs a pass at trimming or
   restructuring before this scales to more checkpoints or more SUTs.
3. **Prioritization ablation** (still open from before Phase 0 started) — hasn't
   been run: unranked vs. ranked claim order at a fixed test budget, to
   measure whether ranking actually improves what gets found. Cheap to run,
   reuses the existing paired-trial methodology from
   `experiments/token-purchase-oracle-value/` and
   `experiments/ecoestate-notes-oracle-value/`.

## Not yet in scope

- CocoIndex / retrieval wiring for layer 3 — separate spike, see
  `docs/rag-cocoindex-todo.md`, gated on its own corpus-size question.
- Real product / real JIRA as a context source — still proving the loop on
  the `token_purchase` mock first.
- Service split (Oracle vs. Driver as independent services) — gated on the
  Oracle having a stable, versioned output contract, which this Phase 0 work
  is what's establishing.
- **Possible future "signal layer"** (not started, not designed) — static
  code analysis, unit test coverage, churn metrics, etc. Would likely sit
  alongside or feed into layer 3 (fast-changing, per-SUT), but whether it's
  a genuinely distinct layer or just another context source hasn't been
  thought through. Flagged 2026-08-27 during the layer-3 documentation pass
  (see `docs/ontology-layer-reference.md`) as an idea worth returning to,
  explicitly deferred.
