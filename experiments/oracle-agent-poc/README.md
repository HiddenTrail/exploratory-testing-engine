# Oracle Agent PoC

A first, deliberately narrow slice of the "Oracle layer" described in
[`docs/exploratory-testing-engine-concept.md`](../../docs/exploratory-testing-engine-concept.md)
§3.4 - distributing judgment across narrow, specialized heuristics instead
of one model just deciding "is this weird" alone. Never built until now.

**This agent does not test the system.** It never calls a live SUT - it
runs a heuristic pass over a written spec (`spec/spec.md`, the sole input)
and produces a single JSON "oracle library." Testing (the Driver) is a
separate, existing concern this artifact is meant to eventually feed into.

## The 5 heuristics

A handful, not the full taxonomy:
- Two SFDIPOT dimensions: **Data**, **Function** - the only two judged
  necessary for the three FEW HICCUPPS heuristics below.
- Three FEW HICCUPPS heuristics: **Claims** (spec-conformance),
  **Comparable Products**, **Self-Consistency** (the concept doc's own
  "Product/Image" oracle).

Each decides for itself whether it even applies to this SUT (`applies: bool`
+ reasoning, not assumed) before producing `vectors` - concrete,
context-specific facts/expectations. The other 5 SFDIPOT dimensions
(Structure, Interfacing, Platform, Operations, Time) are **not modeled** -
explicitly placeholdered in the output as `{"modeled": false, "reason":
"..."}`, not silently omitted, so a future phase can fill them in without
restructuring anything.

## The spec

`spec/spec.md` - one real, human-reviewable markdown file describing the
`token_purchase` API, its known accounts, and a real, captured happy-day
example. Transcribed from what's already known and validated about this
system elsewhere in the project (its adapter's own schema doc, plus the
domain description already written and live-verified during the
context-enriched-bootstrap work) - not rediscovered, not fabricated. Lives
in its own subfolder deliberately anticipating more files later, even
though today there's exactly one.

## Running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
python run_live.py
```

No SUT to start - this agent only reads `spec/spec.md`. Writes
`results/oracle_library.json`: one entry per applicable heuristic, each
with its own `vectors` list.

## What this doesn't do (yet)

- The Driver doesn't update this library as it tests (learn/refine oracle
  facts from real results) - explicitly deferred.
- This library isn't wired into the real `token_purchase` adapter's
  `onboarding_extra` as a shipped feature - explicitly deferred. It was,
  however, live-verified to be the right *shape* to be useful there: a
  one-off comparison of `engine.loop.get_casting_round()` with vs. without
  the library merged into a copy of the real adapter's `onboarding_extra`
  showed a real, observable difference - with the library, the Driver
  explicitly considered "invalid CVV" and "Luhn check" as candidate bug
  classes (absent from the baseline's reasoning entirely), and concretely
  chose to test `expired_card` as one of its 5 real tests, replacing a
  `credit_count=-1` test that appeared in the baseline run. Not proof this
  makes testing *better* - just evidence the artifact is the right shape
  to change real casting behavior, which is what this phase needed to show.
