# TODO — Ontology layer (Phase 0)

Tracking plan for the 4-layer ontology stack under `engine/ontology/` — a
prioritization layer sitting between the domain-grounded oracle claims and
the Driver, plus a heuristic library and a context/results feed. See
`docs/exploratory-testing-engine-concept.md` for the original vision and
`/memories/repo/ontology-phase0-status.md` for the full session history that
led here.

## Status: Phase 0 proven on `token_purchase`, one real gap found

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

## Known gap — claim matching is exact-string only

Confirmed live: after a real Driver run (2 checkpoints, 3 tests/round), the
ranking did **not** shift, because `oracle_creator.score_grounded_claim` matches
a test result to an oracle claim by exact string equality — but the Driver's
`linked_hypothesis` is free text it writes itself, never verbatim equal to the
oracle's claim text, even when it's clearly testing the same thing. The loop
runs mechanically end to end but doesn't yet actually reprioritize anything.

Options to fix (not yet decided):
- Fuzzy/keyword-overlap matching instead of exact equality (cheap, imperfect)
- Give oracle claims stable IDs and have the casting tool reference an ID when
  a test is tied to one, instead of restating the claim in prose
- LLM-based matching ("does this result confirm/refute claim X") — most
  accurate, adds cost/latency per result

## Backlog (not yet started)

1. **Fix claim matching** (see gap above) — the loop needs this to have any
   real effect.
2. **Skeptic-guided case selection.** Right now the Driver just pulls from the
   top of the ranked list. The Skeptic should instead steer which prioritized
   cases get run next, based on what still needs proving/disproving for the
   current hypothesis — not a fixed top-N pull.
3. **Driver/Skeptic output verbosity.** Free-text reasoning/hypothesis/critique
   fields are very large per checkpoint. Needs a pass at trimming or
   restructuring before this scales to more checkpoints or more SUTs.
4. **Prioritization ablation** (still open from before Phase 0 started) — hasn't
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
