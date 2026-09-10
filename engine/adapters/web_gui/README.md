# web_gui adapter

A live **web application** as a system under test, driven by the engine's LLM-Driver
casting loop over **web-recon's perception**. The browser transposition of the
`clash_royale` adapter: where that drives a game by named taps and reads screens by pixel
comparison, this drives a web app by named `(state, control)` actions and reads states by
web-recon's *signature* (URL route + control skeleton + landmark headings).

This is the Stage 6 promotion of `experiments/web-recon` into the engine. The two halves
divide cleanly:

- **The deterministic crawler** (`experiments/web-recon`) does the read-only recon and
  writes an `ontology.json` — the map, discovered not declared, with a read-only safety
  gate deciding which controls are non-committing.
- **This adapter** takes that ontology as its **carried reference** (the analog of
  clash_royale's carried 11-screen fingerprint set): it *is* the action space. The Driver
  may only name a `(state, control)` pair the recon found and cleared as safe; there is no
  free-text selector and no coordinate, so the run looks and navigates only — nothing it
  can name mutates the app.

## Running it

```bash
# 1. Recon the app (read-only) to produce the carried reference.
cd experiments/web-recon
python crawl.py http://localhost:5173 --out out/ontology.json

# 2. Point the adapter at that ontology and run the casting loop.
cd ../..
export WEB_GUI_ONTOLOGY="$PWD/experiments/web-recon/out/ontology.json"
export WEB_GUI_URL="http://localhost:5173"   # optional; defaults to the ontology's target.url
export WEB_GUI_HEADED=1                        # optional; headless by default
python -m engine.cli --adapter web_gui
```

`check_sut_ready` loads the reference, launches the browser once, and confirms the SUT is
up and on the mapped entry state before any API call is spent — warning loudly (not
failing) if the app has drifted from the carried map since the recon.

## What a test is, and what an anomaly is

A test is one control on one state plus a **structural prediction** — `same_screen`,
`known_screen`, or `new_screen` — the strongest claim checkable on a first visit. `execute_test`
navigates to the state by replaying the recon's path, actuates the control, classifies where
it landed against the carried map, and reboots to recover. An anomaly is a control that does
not behave the way its interface implies: a dead control (same signature *and* no pixel
change — the visual-diff check, shared with the crawler via `perceive.visual_diff`, keeps a
canvas pan/zoom from being mistaken for dead), a control you cannot get back from
(`recovered_ok` false), two controls to one state, or a carried state you can no longer reach
(drift in the app since it was mapped).

## Modules

| module | what it is |
|---|---|
| `reference.py` | loads a web-recon `ontology.json` as the carried reference: the reachable states, the safe `(state, control)` action space, the navigation path to each state, and the Driver briefing. Pure — unit-tested against a fixture ontology with no browser. |
| `session.py` | the only browser-touching module: a Playwright browser launched once, reusing web-recon's `capture`/`signature`/`appearance`/`visual_diff`. Reaches a state by replaying its path, actuates one control, classifies the transition, reboots to recover. |
| `adapter.py` | the `SUTAdapter`: casting tool schema/prompt/validation (a pair outside the carried map is refused before actuation), `execute_test`, the typed `outcome_for` envelope, and report rendering. |
