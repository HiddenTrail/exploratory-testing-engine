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

## The catalog: a growing reference behind the active 5

`heuristics/catalog.json` is the broader reference the active 5 heuristics
above are drawn from - not loaded by `run_live.py`, just a standing,
growing list of what *could* be modeled. Seeded from James Bach's
Heuristic Test Strategy Model (HTSM v6.3): all 7 SFDIPOT Product Factors,
all 10 Quality Criteria Categories, all 9 General Test Techniques, and the
5 FEW HICCUPPS-derived oracles this project has named so far. Each entry
follows one template (`keyword`, `type` - `"model"` vs `"technique"`,
`category`, `name`, `description`, `context`, `status` - `"implemented"`
vs `"cataloged"`, `source`). HTSM's "Project Environment" category
(testing-project logistics, not SUT behavior) is deliberately excluded -
a different kind of thing than everything else here. Standing practice:
append newly invented heuristics here, following the same template.

## Wired into the real Driver

This run's output (`results/oracle_library.json`, copied verbatim, not
regenerated) is now committed at
[`engine/adapters/token_purchase/oracle_library.json`](../../engine/adapters/token_purchase/oracle_library.json)
and merged into the real `token_purchase` adapter's `onboarding_extra` -
see [`adapter.py`](../../engine/adapters/token_purchase/adapter.py). The
Driver sees it as ordinary evidence alongside the schema and known
accounts, and it renders as its own "Oracle library" exhibit in the HTML
report. A real live run confirmed the effect isn't just cosmetic: given
the library, the Driver's first-round reasoning explicitly cited the
`expired_card` vs. `expiry_mismatch` distinction the library's `function`
and `comparable_products` vectors both flag, tested for it directly, and
it surfaced as a real (inconclusive, honestly caveated) anomaly in the
bug report - not fabricated, an actual run against the live mock SUT.

It's still a one-time snapshot, not live - regenerating it means re-running
`run_live.py` and re-copying the output by hand. This library only grows
by intent, matching the pattern for [the catalog](#the-catalog-a-growing-reference-behind-the-active-5)
above.

## What this doesn't do (yet)

- The Driver doesn't update this library as it tests (learn/refine oracle
  facts from real results) - explicitly deferred.
