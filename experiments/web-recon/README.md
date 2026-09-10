# web-recon

An intelligent browser-exploration bot that maps a web app *and* finds what's broken on
it, then (later stages) writes a wiki about it. It combines the two halves this repo
already has: the **Clash Royale kit's** discipline — the map is discovered not declared,
systematic coverage, safety that fails closed, a wiki built by arithmetic — running on
**Playwright's** semantic perception instead of a game's pixels.

**The creed:** the map is discovered, not declared; record evidence, don't assert;
safety fails closed; the wiki is measurement, the model only synthesizes; a run resumes
the last one's map. And, decided up front: **the deterministic core does everything by
itself; the LLM is off by default and, when on, only annotates the finished ontology —
it never gates the crawl.**

## Status: Stage 1 (of 7) — identity hardened across a multi-view app

Deterministic core, no model, nothing mutates the app.

Stage 1 result: the control-skeleton signature alone collapsed two genuinely different
views that share a control set (the PoC's "You said yes" and "You said no" pages, both
with only a Back button). Fixed by adding **visible landmark headings** to the
signature: the PoC now resolves to **three distinct states**, Back returns to the
question state, and — regression — EcoEstate (no headings) stays exactly one state, so
the extra term only adds resolution where the page provides it. Corpus: `fixtures/poc-*`.

| module | what it is |
|---|---|
| `schema.py` | the ontology: states (nodes), (state, action) → state transitions (edges), the elements on each state, and the evidence behind findings. Pure dataclasses + JSON. |
| `perceive.py` | the only browser-touching module: a live page → one normalised `Observation` (URL, a11y tree, interactive elements read off the DOM, console, network, visible text). |
| `identity.py` | "is this the same view?" — a state is its URL route + control skeleton; text/map-position is a *variant*, not a new state. No model. |
| `oracles.py` | deterministic functional oracles: HTTP 4xx/5xx, console errors, exceptions → `Evidence`. This is where a browser beats a game — it found the 500 below for free. |
| `capture_fixtures.py` | records a corpus of `Observation`s (in `fixtures/`) so all the above is tested offline. |

Run: `pip install -r requirements.txt && python -m playwright install chromium`, then
`python -m pytest tests` (offline, no app, no browser — uses the recorded fixtures).

## The Stage 0 spike verdict (the risk we set out to settle)

The make-or-break question was: **can we tell a web app's views apart without
over-splitting** (a game's fingerprint problem, transposed). Measured against EcoEstate:

- **The mechanism works, and is tested.** All five recorded EcoEstate frames — initial
  load, post-load error, two map zoom levels, a fresh revisit — collapse to **one
  state**; different control sets, different routes, are kept distinct; a query-string
  year is a variant, not a new view. So pan/zoom/loading/error never over-split — the
  browser analog of the scroll-surface fix, and it needs no model.
- **But not via the accessibility tree.** `page.accessibility.snapshot()` returns
  *nothing* on EcoEstate (a Leaflet canvas app). Identity built on it would collapse
  every thin-a11y app into one blob. The signal that works is the **interactive-element
  set read straight off the DOM** — which is what `identity.py` uses.
- **EcoEstate is a degenerate *mapping* target — and a great *functional* one.** It is
  effectively one route with ~5 controls (map zoom + attribution) that never change, so
  its navigation graph is a single node: there is almost nothing to *map*. What it does
  expose is a real bug, caught deterministically: `GET /api/property-prices?year=YYYY`
  returns **500** for every year (upstream StatFin request rejected with 400), so the
  price heatmap never loads. The oracles surface that with zero model calls.

**Recommendation carried into Stage 1:** keep EcoEstate as a *functional-findings*
target (its network/console evidence is gold), but bring in a **DOM/multi-view app** —
the sibling `playwright-gui-poc` (question → yes/no pages), or ideally the real product's
GUI — to exercise the *mapping* strength. The identity code is ready for both; only the
fixtures differ.

## Next (not built yet)

Stage 1 hardens identity across a multi-view app; Stage 2 adds read-only frontier
exploration + evidence capture → a real `ontology.json`; Stage 3 the wiki; Stage 4 the
optional, batched LLM review (hypotheses + Skeptic + Oracle heuristics); Stage 5
safety-gated mutations; Stage 6 resume/carry + promotion to an `engine/` adapter.
