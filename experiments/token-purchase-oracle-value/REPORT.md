# Does the oracle library help on the real, wired-in token_purchase adapter?

## Setup

Unlike `pattern-detection-oracle-poc`, this runs the actual production pipeline -
`engine.runner.run()` against the real `token_purchase` adapter, not a hand-rolled
reimplementation - because the full Driver+Skeptic checkpoint loop already exists for it.

- **6 paired trials** (12 runs total). Same adapter, same budget in both arms - the only
  difference is whether `onboarding_extra` carries `oracle_library` (the real `ADAPTER`) or not
  (a `dataclasses.replace()` copy with just `known_accounts`).
- **8 tests per checkpoint** in both rounds (up from the adapter's defaults of 5/4), 2
  checkpoints max (adapter default) - so up to 16 tests per run.
- The mock SUT holds in-memory state (balances, transaction counter) that persists across calls
  within one process. Restarted fresh before every individual trial so all 12 runs start from
  the same clean slate, not compounding state from earlier trials.
- **No ground truth here** - `token_purchase`'s own docstring says a real bug's existence is
  "genuinely unknown going in." Same limitation as before: this can only measure proxy signals
  (Skeptic satisfaction, coverage, bug yield), not recall against a known answer.

## Result 1: the Skeptic was satisfied 3x more often with the oracle library present

| | strong_enough | weak |
|---|---|---|
| **Without oracle** | 1/6 | 5/6 |
| **With oracle** | 3/6 | 3/6 |

Same fixed 16-test budget both arms, every trial. This is the actual outcome measure this
project's own architecture uses to decide "was the investigation good enough" - and the
oracle-informed arm reached it 3x more often.

**Caveat against over-reading this as clean**: in trial 1, the without-oracle run's "weak"
verdict was partly driven by the Driver's hypothesis containing a real arithmetic inconsistency
(claiming two approvals that couldn't both be true given the numbers stated) - a Driver-writing
mistake unrelated to the oracle library, not a coverage gap. Some of this 3x gap is real
run-to-run LLM variance, not 100% attributable to the library. N=6 is too small to put a
confidence interval on "3x," but the direction held in every pair where the arms diverged
(never once did without-oracle reach strong_enough while with-oracle stayed weak).

Bug-report `status` (`corroborated` vs `inconclusive`) is **not an independent second metric** -
the tool schema defines it as literally derived from the same final Skeptic verdict
("'corroborated' if Skeptic was satisfied"). Reporting it separately would double-count Result 1,
so it's omitted here as its own line item.

## Result 2: coverage broadened specifically where the plain schema doc gives no hint

Keyword-tallied across each run's theory-driven test hypotheses (a blunt instrument - presence
of a keyword, not a judged correctness call):

| Theme | Without oracle | With oracle |
|---|---|---|
| Monetary precision / rounding | 1/6 | **4/6** |
| CVV format (non-numeric rejection) | 3/6 | **6/6** |
| Transaction ID uniqueness | 0/6 | 1/6 |
| Luhn checksum | 4/6 | 5/6 |
| Cross-account authorization | 5/6 | 6/6 |
| credit_count validation | 5/6 | 6/6 |
| Expiry validation | 6/6 | 6/6 |
| Card-number format | 5/6 | 6/6 |
| Pricing tiers | 6/6 | 6/6 |
| Capacity / insufficient_funds | 6/6 | 5/6 |
| Balance accumulation | 5/6 | 6/6 |
| PAN/CVV non-echo | 2/6 | 2/6 |

Most themes are near-ceiling in **both** arms - these are directly hinted at by the plain
`API_SCHEMA_DOC`'s documented decline-reason enum, so both arms find them regardless of the
oracle library. The real, attributable movement is in the two themes the schema doc says nothing
about: **monetary precision** (1/6 → 4/6) and **CVV format** (3/6 → 6/6), which map directly to
specific `data` heuristic vectors in the oracle library ("must not exhibit floating-point
artifacts," "CVV... should reject non-numeric strings") that the without-oracle arm never sees.

PAN/CVV non-echo (a distinct oracle vector - "must not be reflected in any response field") shows
no difference here (2/6 both arms) as a *dedicated test hypothesis* - though it did appear as a
passive *observation* in the wired-in run shown earlier in this conversation ("No PAN or CVV
reflection observed"). Passive observations aren't captured by this keyword tally, which only
scans `linked_hypothesis` test entries - a real gap in this measurement, not evidence the oracle
had no effect there.

## Result 3: bug yield was more consistent, not necessarily "more correct"

Without oracle: 1, 2, 1, 1, 2, 2 anomalies flagged (9 total, varies run to run). With oracle: 2,
2, 2, 2, 2, 2 (12 total, exactly 2 every single time). More consistent yield isn't automatically
better - without ground truth, more flagged anomalies could mean more real findings or just more
false positives. Noted as an observation, not scored as a win.

## Efficiency: no difference

All 12 runs used the full budget - 2 checkpoints, 16 tests, no early `give_up` in either arm.
The oracle library changed what got tested and how satisfied the Skeptic ended up, not how much
testing got done.

## Honest limitations

- N=6 per arm, same as before - no statistical test is justified at this size.
- Theme coverage was scored by simple keyword matching, not a judged correctness call - a blunt
  instrument that undercounts passive observations (see PAN/CVV note above).
- No ground truth exists for this SUT. Every finding here is a proxy signal (Skeptic
  satisfaction, coverage breadth, yield consistency) - not evidence that either arm found a real
  bug, since whether one exists at all remains unknown.
- I scored this myself, not blinded to which arm produced which run.

## Bottom line

Unlike `pattern-detection-oracle-poc` (a ceiling effect - the test case was too easy for either
arm to fail), this comparison on the real, wired-in production adapter shows a **real, consistent
effect on the actual outcome measure this project already uses**: the oracle-informed arm
satisfied the Skeptic 3x more often on an identical budget, and its extra coverage traces
concretely to oracle-library content absent from the plain schema doc (monetary precision, CVV
format) rather than to restating what the schema already implies. It still can't say these are
*real* bugs - `token_purchase` has no known ground truth - but on the metric this project's own
architecture uses to judge "was this investigation good enough," the oracle-informed arm won more
often, every time the two diverged.
