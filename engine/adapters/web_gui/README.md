# web_gui adapter

A live **web application** as a system under test, driven by the engine's LLM-Driver
casting loop over **web-recon's perception**. The browser transposition of the
`clash_royale` adapter: where that drives a game by named taps and reads screens by pixel
comparison, this drives a web app by named `(state, control)` actions and reads states by
web-recon's *signature* (URL route + control skeleton + landmark headings).

This is the Stage 6 promotion of `.experiments/web-recon` into the engine. The two halves
divide cleanly:

- **The deterministic crawler** (`.experiments/web-recon`) does the read-only recon and
  writes an `ontology.json` — the map, discovered not declared, with a read-only safety
  gate deciding which controls are non-committing.
- **This adapter** takes that ontology as its **carried reference** (the analog of
  clash_royale's carried screen fingerprint set, `known_screens.json`): it *is* the action space. The Driver
  may only name a `(state, control)` pair the recon found and cleared as safe; there is no
  free-text selector and no coordinate, so the run looks and navigates only — nothing it
  can name mutates the app.

## Running it

```bash
# 1. Recon the app (read-only) to produce the carried reference.
cd .experiments/web-recon
python crawl.py http://localhost:5173 --out out/ontology.json

# 2. Point the adapter at that ontology and run the casting loop.
cd ../..
export WEB_GUI_ONTOLOGY="$PWD/.experiments/web-recon/out/ontology.json"
export WEB_GUI_URL="http://localhost:5173"   # optional; defaults to the ontology's target.url
export WEB_GUI_HEADED=1                        # optional; headless by default
export WEB_GUI_SESSION=.sessions/juice-shop/logged-in.json  # optional; every test starts from this saved session (#154)
export WEB_GUI_PRODUCT=juice-shop             # optional; use that product's seeded oracle, built from the wiki
export WEB_GUI_FEATURES="login,search,list-paging"  # optional, without a product: heuristic library tags to rank first
python -m engine.cli --adapter web_gui
```

**Or map the app with Spoor instead** (the default crawler, see CLAUDE.md). It gets past
overlays like cookie banners, which web-recon can't. The converter replays Spoor's paths
live and writes the same `ontology.json` shape, with no LLM call:

```bash
../ht-spoor/.venv/Scripts/spoor explore http://127.0.0.1:3000 --max-depth 2 --max-seconds 300
python -m engine.adapters.web_gui.from_spoor     --map .spoor-cache/maps/127.0.0.1_3000.json --url http://127.0.0.1:3000     --out .experiments/web-recon/out/juice-shop-from-spoor.json
export WEB_GUI_ONTOLOGY="$PWD/.experiments/web-recon/out/juice-shop-from-spoor.json"
```

**Behind a login (#154):** map and convert with the same saved session, then run with it.
Each test still starts in a fresh browser context, loaded from the session file. A run whose
session doesn't match the one the map was made with warns before it starts:

```bash
cd runs/spoor-juice-logged-in   # its own .spoor-cache, so the logged-out map isn't overwritten
../../../ht-spoor/.venv/Scripts/spoor explore http://127.0.0.1:3000 --session "$PWD/../../.sessions/juice-shop/logged-in.json" --max-depth 2
cd ../.. && python -m engine.adapters.web_gui.from_spoor --map runs/spoor-juice-logged-in/.spoor-cache/maps/127.0.0.1_3000.json     --url http://127.0.0.1:3000 --session .sessions/juice-shop/logged-in.json --out .experiments/web-recon/out/juice-shop-logged-in.json
export WEB_GUI_ONTOLOGY="$PWD/.experiments/web-recon/out/juice-shop-logged-in.json" WEB_GUI_SESSION=.sessions/juice-shop/logged-in.json
```

Session files hold live auth cookies: keep them in the gitignored `.sessions/`. Only a
session's name ever reaches the Driver or a report.

It keeps a control only if web-recon's safety gate would let the read-only crawl act on it
(judged on the live element), follows a Spoor step only if that control passes as a plain
click, and drops any page that doesn't replay to the same fingerprint twice. It prints how
many steps the gate refused, and names them.

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
| `session.py` | the only browser-touching module: a Playwright browser launched once, reusing web-recon's `capture`/`signature`/`appearance`/`visual_diff`. Reaches a state by replaying its path, actuates one control, classifies the transition. A click looks the control up on the live page by web-recon's role and name before falling back to the saved selector, which is positional and can shift. If another element covers the control (a cookie notice, say), it sends the click event to the control itself and reports `covered_by`, because a forced click would land on the cover. Every restart starts from a fresh browser session (no cookies or storage), and every read waits for a rested page: no DOM change for 0.4 s and no request in flight, at most 8 s, else the reading is flagged `settled: false`. Each result carries `signals`, the before/after diff: console errors, failed requests, storage and cookie keys changed (never their values), controls added or removed (#143). Only signals that pass every trust check are in `signals`: a request started after the action, on the product's own origin, nothing that also changes while the state sits idle (learned once per state per run), and a rested page. The rest go to `signals_weak`, as hints, and so does everything when the action wasn't sent. Screenshots are never a signal. The idle watch looks three times over about 6 s and learns controls too (a carousel). `signal_audit.py` checks all of this against a live site with no model calls: `python -m engine.adapters.web_gui.signal_audit --ontology <map> --url <url> --name <site>`. Where a known state is expected (the start page, the state a test targets), a capture that doesn't match is taken again, up to twice, since a page still loading reads as another state. |
| `signal_audit.py` | runs `act()` many times against one site (fresh sessions, every pair repeated) and reports weak spots in signal handling: trusted signals that don't reproduce, screen classes that flip, why signals went weak, unsettled reads, unstable idle noise. No model calls. |
| `from_spoor.py` | turns a Spoor exploration map into this `ontology.json`, by replaying Spoor's paths live and capturing each page the way web-recon does. Safety fails closed (see "Running it"). `map_errors` is the contract with Spoor's map format: the `spoor contract` CI job checks a real, pinned Spoor's output with it (`engine/requirements-spoor.txt`, #144). |
| `adapter.py` | the `SUTAdapter`: casting tool schema/prompt/validation (a pair outside the carried map is refused before actuation), `execute_test`, the typed `outcome_for` envelope, and report rendering. |
