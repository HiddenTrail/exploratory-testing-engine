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

## Status: Stage 6 (of 7) — resume/carry + promotion to an engine adapter

A run now **resumes the last one's map**: `crawl --resume prior.json` carries a previous
ontology forward, so a state is *known on first sight* (`carried`), and a drift report
flags carried states not reached this run (`carried_state_absent`) and states new since it
(`new_state`). And web-recon is **promoted into the engine**: the deterministic crawl is
the read-only recon that writes the map; the new
[`engine/adapters/web_gui`](../../engine/adapters/web_gui/) adapter takes that ontology as
its *carried reference* and drives the same app with the engine's LLM-Driver casting loop
(mirroring `clash_royale`), reusing this package's perception/identity/safety. One command:
`WEB_GUI_ONTOLOGY=...out/ontology.json python -m engine.cli --adapter web_gui`. The Driver
may only name a `(state, control)` pair the recon cleared as safe — so the casting run
looks and navigates only.

## Earlier: Stage 5 — safe interaction: gestures, model-proposed controls, vetted mutations

Beyond click/fill, every state is also probed with **non-committing gestures** at the
viewport centre: hover, wheel up/down, ctrl+wheel zoom in/out, and a drag-pan — the safe
half of the game kit's fuller input set (a wheel/hover/centre-drag commits nothing). Each
gesture's effect is judged by the same before/after screenshot diff, so a canvas that
pans or zooms registers as `changed`. Live on EcoEstate: wheel/ctrl+wheel zoom, drag-pan
and hover all move the Leaflet map and are captured, where click-only saw almost nothing.
A gesture is a *probe*, not navigation: it is always recorded as a **self-transition**
(never mints a state or a replayable discovery-path step, so replay stays deterministic),
it is tried **after** a state's real controls (so it can't crowd genuine coverage off a
tight budget), and a no-op gesture is never mis-reported as a "dead control".
(Vetting-gated *form* mutations remain a later step.)

### The model as a proposer (`crawl --llm`, off by default)

The optional half of a **driver/skeptic** loop, and it keeps the creed — *the model
proposes, the deterministic core disposes*. With `--llm`, each newly-discovered state's
DOM controls are supplemented by controls the **model nominates** (an icon-only button, a
div behaving as a button, a hover-revealed control the DOM scan missed). The model never
gets to assert an element exists or is safe: every nomination is (1) **resolved** against
the live page — a nomination matching no unique control is a hallucination and is dropped
before any action; (2) run through the **same deterministic safety gate** as every other
control, so a proposal can never widen what is touched; (3) **actuated and measured** like
any other control. A proposed-but-`dead`/`blocked` control is the skeptic's verdict,
recorded as measurement (and shown `model-proposed` in the wiki with its effect), not the
model's word. Off by default, one small tool-forced call per state via the engine's auth,
soft-failing to the deterministic path. Shown live on EcoEstate: the model nominated
controls, all were rejected at resolution (a Leaflet canvas exposes few nameable hidden
controls), and the deterministic map was untouched — the guardrail doing its job.

### Vetting-gated mutations (`crawl --mutate`, off by default)

Stage 5b lets the crawl cross the read-only line — but only through a **deterministic
vetting pass** (`safety.vet`), opt-in and fail-closed, with the model kept out of the
decision entirely (the creed: the model never authorizes a mutation). Two disjoint word
sets decide: a committing control is actuated only if it is **affirmatively reversible**
(a search / filter / sort / show query — an *idempotent, GET-style read* on the server)
**and** carries no verb from the **destructive denylist** (delete, buy, pay, send, save,
publish, sign out, …) — which is refused *even under* `--mutate`. So the one thing this
unlocks is the query submit the read-only pass deliberately avoided: a search box is now
filled *and* Enter-pressed, a "Search"/"Filter"/"Sort" button is clicked; a "Delete",
"Buy", or "Save" never is, mutations on or off. Each vetted action is a distinct
`__mutate__:` action alongside the read-only fill of the same field, tested and measured
like any other, and shown `vetted mutation` in the wiki with its effect. Live on EcoEstate:
the "Search postcodes" box gets its vetted fill+Enter submit (read-only only filled it),
measured `dead` — one honest extra transition, the map otherwise unchanged.

## Stage 4 (of 7) — intelligence: graph oracles + optional LLM synthesis

Stage 4 adds the "intelligence" layer in two halves that keep the creed:
- **Deterministic graph oracles** (`analyze.py`, always on, zero tokens): flags navigation
  anomalies over the finished ontology — dead controls, blocked controls, redundant
  controls (two controls to one destination), dead-end states — as *structural
  observations*, separate from functional findings and labelled observations, not defects.
- **Optional LLM synthesis** (`synthesize.py`, **off by default**, `wiki.py --llm`): one
  batched tool-forced call over the ontology digest → a summary and falsifiable claims,
  each **citing a measurement**, marked measured/inferred/speculative, and naming the rival
  it would lose to. Runs *after* the crawl, never gates it, soft-fails to a note if the
  model is unreachable, uses the engine's auth. Shown live on EcoEstate (Bedrock) — it even
  flagged the crawl's own read-only limits as rivals (search needs Enter; zoom may be canvas-only).

## Stage 3 — the wiki, by arithmetic

Deterministic core, no model, nothing mutates the app.

Stage 3 turns an `ontology.json` into a browsable **HTML wiki** with `wiki.py`
(`build_wiki` is a pure function of the ontology): a summary, the headline **Functional
findings** page a game wiki never had (every HTTP error / failed request / console
error / exception with the state it fired in), an SVG **navigation map** (states as
nodes, transitions as edges; a state with findings is red), and a per-state detail card
with **a screenshot of the state** (the browser analog of the game wiki's per-screen
picture), its signature, URL, exits, findings, and interactive elements. Proven on both
crawls — the
EcoEstate wiki names the `property-prices` 500 with its evidence; the PoC wiki draws the
whole question ↔ Yes/No graph.

Stage 2 crawls an app by frontier-BFS: enumerate each state's safe actions, go to the
nearest state with an untried one (replaying its discovery path), act, and record where
it led plus any evidence. The read-only gate (`safety.py`) refuses form inputs,
mutating-verb names, submit/reset, off-site and non-http links, and any unrecognised
role (fail-closed).

Stage 1 (identity) result, still holding: the control-skeleton signature collapsed the
PoC's "You said yes" / "You said no" pages (both only a Back button); fixed by adding
**visible landmark headings** to the signature. Three distinct states; Back returns to
the question; EcoEstate (no headings) stays one state.

| module | what it is |
|---|---|
| `schema.py` | the ontology: states (nodes), (state, action) → state transitions (edges), the elements on each state, and the evidence behind findings. Pure dataclasses + JSON. |
| `perceive.py` | the only browser-touching module: a live page → one normalised `Observation` (URL, visible headings, interactive elements read off the DOM, console, network responses **and failures**, visible text). |
| `identity.py` | "is this the same view?" — a state is its URL route + control skeleton + landmark headings; body text / map position is a *variant*, not a new state. No model. |
| `oracles.py` | deterministic functional oracles: HTTP 4xx/5xx, **failed requests (a dead endpoint)**, console errors, exceptions → `Evidence`. This is where a browser beats a game — it found the 500 below for free. |
| `safety.py` | the read-only gate: `plan(element)` → **click** (links/buttons + view-toggle selection controls: radio/checkbox/tab/switch), **fill** (a search/filter box with a benign query), or **skip** (submit/reset, mutating-verb names, sensitive or generic text fields, off-site/non-http links — off-site fails closed — unrecognised roles). Pure. `vet()` is the Stage 5b extension: with mutations enabled it admits *only* an affirmatively-reversible query submit (search/filter/sort) and refuses a destructive-verb control even then. |
| `crawl.py` | the frontier-BFS read-only crawler → `Ontology` (+ a screenshot per state, and **per action** — every touch). Actuates each control's plan; clicks via a **ladder** (unique role locator → CSS → scroll+retry → `dispatch_event` → force) so a found control is reached if it possibly can be, else recorded as a `blocked` edge (not a finding). Waits for network-idle before capture/act; **reboots** to the start before every action, and if one navigates off-origin. When the DOM says an action changed nothing, a **before/after screenshot diff** confirms it before calling the control `dead` — so a canvas/map change the DOM can't see reads as `changed`, not a false dead. Also probes each state with **gesture actions** (hover, wheel, ctrl+wheel zoom, drag-pan) at the viewport centre. `choose_frontier` is a pure planner. `python crawl.py <url> [--headed] [--max N] [--out PATH] [--llm] [--mutate] [--resume prior.json]` (`--llm`/`--mutate` off by default; `--resume` carries a prior run's map forward — states it mapped are known on first sight, and a drift report flags carried states not reached this run and states new since it). |
| `analyze.py` | deterministic graph oracles over the finished ontology → structural observations (dead/blocked/redundant controls, dead ends). Pure, no model. |
| `wiki.py` | `ontology.json` → a self-contained HTML wiki (state + per-action screenshots, functional findings, structural observations, nav map), by arithmetic; `build_wiki` is pure. `--llm` adds an optional model-synthesis section. `python wiki.py <ontology.json> [--out wiki.html] [--llm]`. |
| `synthesize.py` | **optional**, off by default: one batched LLM call over the ontology digest → cited, calibrated claims (measured/inferred/speculative + rival). Uses the engine's auth; soft-fails. Pure digest/validate/render, tested with a fake client. |
| `propose.py` | **optional**, off by default (`crawl --llm`): the model nominates interactable controls the DOM scan missed; the crawler then resolves each on the live page, runs it through the deterministic safety gate, and tests it — the model proposes, the gate and the app dispose. Pure digest/validate/parse, tested with a fake client. |
| `capture_fixtures.py` / `capture_poc.py` | record `Observation` corpora (in `fixtures/`) so identity/oracles are tested offline. |

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
  set read straight off the DOM** — which is what `identity.py` uses. (So the a11y
  snapshot is no longer captured at all — it was only ever written, never read.)
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
safe interaction (gestures, model-proposed controls, vetting-gated mutations); Stage 6
resume/carry + promotion to an `engine/` adapter.
