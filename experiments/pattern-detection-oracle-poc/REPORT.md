# Does the oracle library help? A paired comparison on a scenario with real ground truth

## Setup

Unlike `token_purchase` (no known bug — recall can't be measured), `pattern-detection-poc`'s
`sequence.json` has a real, known `ground_truth`, withheld from every model call. That makes
this scenario a genuine test of whether the oracle library changes outcomes, not just prose.

- **Oracle library**: freshly generated (`run_oracle_pass.py`), judging all 22 "model"-type
  entries in the heuristics catalog independently against a new `spec.md` describing only the
  `/analyze` endpoint's schema and one ordinary example — no hint of the real cause. 20/22
  applied; `charisma` and `installability` were correctly judged not applicable to a backend API.
  None of the 20 applicable heuristics' vectors mention regex, backtracking, or repeated
  characters — the library was not leaked.
- **Comparison** (`run_comparison.py`): 6 paired trials. Same Driver tool schema and system
  prompt in both arms — the *only* difference is whether `oracle_library` is present in the
  evidence. Each hypothesis then gets a cold Skeptic review that never sees the oracle library,
  mirroring how `engine.loop`'s Skeptic never sees `onboarding_extra` either.
- **Scoring**: done by hand against the real `ground_truth` (this project's standing convention),
  by me, not blinded to which arm produced which output — a real limitation, noted here rather
  than glossed over.

## Result 1: no measurable difference on the primary metric

**6/6 without the oracle, and 6/6 with it, correctly identified catastrophic regex backtracking
(ReDoS) as call 9's cause**, with `anomalous_call_index: 9` and `severity_if_true: high` in
every single trial, both arms. Several responses even used the term "ReDoS" unprompted.

This is a **ceiling effect**, not a null result about the oracle library specifically: call 9's
text (63 repeated `'a'` characters followed by `'b!'`) is such a textbook, highly-recognizable
regex-catastrophic-backtracking trigger that the baseline model gets it right unaided, every
time. There was no headroom left for the oracle library to demonstrate improvement on
"did it find the right answer" — the test scenario itself is too easy for the model this project
uses. This scenario cannot answer the value question on this axis; a harder, less
training-data-cliché ground truth would be needed to.

## Result 2: a real, secondary difference in how broadly each arm explored alternatives

Every trial also produces a `competing_explanation` - the most plausible *alternative* theory a
careful engineer would consider. This is where a real, consistent difference showed up:

| Arm | Trial 1 | Trial 2 | Trial 3 | Trial 4 | Trial 5 | Trial 6 | Distinct themes |
|---|---|---|---|---|---|---|---|
| **Without oracle** | cache miss / cold path | cache miss (memoization) | cache/memoization bypass | cache bypass (memoization) | cache miss + cold path | cache miss + cold downstream call | **1** |
| **With oracle** | rate-limiter / throttle | O(n²) algorithmic complexity | O(n²) algorithmic complexity | resource contention / GC pause | resource contention / cold-path buffer | rate-limit / anti-abuse throttle | **3** |

Without the oracle library, all 6 independent trials converged on essentially the same
alternative theory (a caching/memoization effect). With it, the 6 trials spread across three
distinct failure-mode families, with no theme repeated more than twice.

This traces concretely to the fresh oracle library's content, not to imagination: the
`reliability` heuristic's vector explicitly states *"latency_ms must not degrade super-linearly
as text length increases"* (→ the O(n²)-complexity theories), and `platform`/`scalability`
vectors discuss resource contention, concurrent load, and connection handling (→ the GC-pause
and rate-limiting theories) — dimensions the without-oracle arm never sees at all. Both arms then
designed a confirm/disconfirm test reasonably well-matched to whichever alternative they'd
picked, so this isn't a difference in test-design rigor - it's a difference in the breadth of
alternative-hypothesis space each arm drew from.

Whether broader alternative-consideration is worth having is a separate judgment call (it didn't
change the final verdict here, and the Skeptic rated every single one of the 12 hypotheses
"weak", in both arms, for structural reasons - a single-observation hypothesis with no live
re-test can't earn "strong_enough" regardless of the oracle library). But it is a real, repeatable
effect, not noise: 1 unique theme in 6 tries vs. 3 unique themes in 6 tries.

## Result 3: a real cost, not just a benefit

The much larger oracle-library evidence blob reliably (2/2 initial attempts, 100%) caused the
Driver's tool call to malform a nested `confirm_test`/`disconfirm_test` object shape - not
truncation (`stop_reason` was `tool_use`, not `max_tokens`), but the model flattening the nested
object into a string and losing later fields under the added context load. Flattening the schema
to plain string fields fixed it completely (12/12 clean afterward). This is a concrete,
generalizable finding for wiring the oracle library into a real Driver: large supplementary
context can degrade structured-output reliability on nested schemas, independent of whether it
improves reasoning content - something to test for explicitly, not assume away.

## Honest limitations

- N=6 per arm. No statistical test is justified at this size; the diversity difference in
  Result 2 is stark (1 vs. 3 unique themes, no overlap) but this is a raw-count observation, not
  a significance claim.
- Scoring was done by me, not blinded to which arm produced which hypothesis - a real source of
  possible bias that a more rigorous version of this experiment should remove (e.g. a separate
  judge call that never sees which arm produced which response).
- One Skeptic response (trial 4, with-oracle) was missing `unconsidered_alternatives` - my
  `validate_fn` for the Skeptic only checked the `verdict` field, not the full schema, so an
  incomplete response slipped through. Doesn't affect the Driver-side findings above.
- This scenario's ceiling effect means Result 1 tells you nothing about whether the oracle
  library helps find *harder* bugs - only that it doesn't hurt on an easy one, and that it
  broadens exploration even when it doesn't change the final answer.

## Bottom line

On the one metric with real ground truth, the oracle library showed **no measurable benefit** -
but only because the test case was too easy for either arm to fail. On a genuine secondary
metric, it showed a **real, mechanistically-explained broadening** of the alternative
explanations considered, traceable to specific heuristics (reliability, platform, scalability)
absent from the baseline. And it surfaced a **real cost**: larger context degraded structured
output reliability until the tool schema was hardened. None of this proves the oracle library
makes testing better - it's the first result in this project with real ground truth attached, and
what it actually shows is that the *interesting* comparisons (does it help find something a
capable baseline would miss?) still need a harder scenario than this one to answer.
