# web_gui adapter

A live **web application** as a system under test, driven by the engine's LLM-Driver
casting loop over **web-recon's perception**. The browser transposition of the
`clash_royale` adapter: where that drives a game by named taps and reads screens by pixel
comparison, this drives a web app by tests of a start and a few steps on the live page, and reads states by
web-recon's *signature* (URL route + control skeleton + landmark headings).

This is the Stage 6 promotion of `.experiments/web-recon` into the engine. The two halves
divide cleanly:

- **The deterministic crawler** (`.experiments/web-recon`) does the read-only recon and
  writes an `ontology.json` — the map, discovered not declared, with a read-only safety
  gate deciding which controls are non-committing.
- **This adapter** takes that ontology as its **carried reference**: a guide to the
  product's screens, their routes and what's on them, never a limit (#310). A test starts
  from a route on the site or a screen the map knows, and runs up to 6 steps (click, fill,
  select, goto, back) on whatever is on the page. It tests fully by default: clicks,
  types, submits, buys (#299). Safety lives in the engine: the browser never leaves the
  site, logging out is refused, and on parts of a target tagged careful
  (`test-targets/careful/<product>.json`, `WEB_GUI_CAREFUL`) the read-only gate decides
  each step.

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
export WEB_GUI_CAREFUL="/#/payment,Delete account"  # optional; parts where the Driver only looks, "*" for all (#299)
export WEB_GUI_VIDEO=off                       # optional; by default the cited tests' videos are kept in <out-dir>/videos (#286)
export WEB_GUI_SESSION=.sessions/juice-shop/logged-in.json  # optional; every test starts from this saved session (#154)
export WEB_GUI_SESSION_CHECK=/profile         # optional; a path that answers below 400 only while the server accepts the session (#227)
export WEB_GUI_PRODUCT=juice-shop             # optional; use that product's seeded oracle, built from the wiki
export WEB_GUI_KNOWN_PROBLEMS=test-targets/known-problems/juice-shop.json  # optional; the default is the list named after WEB_GUI_PRODUCT, if there is one: the run scores itself against it (#285)
export WEB_GUI_FEATURES="login,search,list-paging"  # optional: library tags to rank first; with a product, the run's focus (e.g. security), up to a third of the ideas
python -m engine.cli --adapter web_gui
```

**Or map the app with Spoor instead** (the default crawler, see CLAUDE.md). It gets past
overlays like cookie banners, which web-recon can't. On a local throwaway target, pass
`--sandbox` so Spoor also buys, deletes and submits, and the map reaches what's behind
those (#310). The converter replays Spoor's paths live and writes the same `ontology.json`
shape, with no LLM call. It keeps everything stable it reaches; only logging out, and on
a part tagged careful anything the read-only gate wouldn't click, isn't followed:

```bash
../ht-spoor/.venv/Scripts/spoor explore http://127.0.0.1:3000 --sandbox --max-depth 2 --max-seconds 300
python -m engine.adapters.web_gui.from_spoor     --map .spoor-cache/maps/127.0.0.1_3000.json --url http://127.0.0.1:3000     --out .experiments/web-recon/out/juice-shop-from-spoor.json
export WEB_GUI_ONTOLOGY="$PWD/.experiments/web-recon/out/juice-shop-from-spoor.json"
```

**Behind a login (#154, #155):** save a session, map and convert with it, then run with it.
To save one, open a browser, log in by hand and press Enter (no password is stored), or let a
condition decide when (`--until storage:<key>`, `cookie:<name>`, `url:<text>` or `selector:<css>`):

```bash
python -m engine.adapters.web_gui.save_session --url http://127.0.0.1:3000/#/login --product juice-shop --name logged-in
```

It writes `.sessions/<product>/<name>.json` and refuses any path git doesn't ignore. A run can also
save the session it reached with `Session.save(path)`.
Each test still starts in a fresh browser context, loaded from the session file. A run whose
session doesn't match the one the map was made with warns before it starts:

```bash
cd runs/spoor-juice-logged-in   # its own .spoor-cache, so the logged-out map isn't overwritten
../../../ht-spoor/.venv/Scripts/spoor explore http://127.0.0.1:3000 --session "$PWD/../../.sessions/juice-shop/logged-in.json" --max-depth 2
cd ../.. && python -m engine.adapters.web_gui.from_spoor --map runs/spoor-juice-logged-in/.spoor-cache/maps/127.0.0.1_3000.json     --url http://127.0.0.1:3000 --session .sessions/juice-shop/logged-in.json --out .experiments/web-recon/out/juice-shop-logged-in.json
export WEB_GUI_ONTOLOGY="$PWD/.experiments/web-recon/out/juice-shop-logged-in.json" WEB_GUI_SESSION=.sessions/juice-shop/logged-in.json
```

A saved session goes stale on the server long before the page shows it: Juice Shop's token
cookie expires after a few hours, and the page still looks logged in from the copy in
localStorage. Before a run, web_gui refuses a session whose credential cookies or JWTs have
expired (names that look like a credential, or any JWT with an `exp`), and warns when one
expires within 30 minutes. A session with no dates to judge passes that check, so set
`WEB_GUI_SESSION_CHECK` to a path that only works logged in, and the run stops if the server
answers 400 or above. Pick one that really fails logged out: single-page apps often answer
200 for any path. The value must be a path starting with `/`. Git Bash rewrites `/profile`
into `C:/Program Files/Git/profile`, which is refused, so set `MSYS_NO_PATHCONV=1` there (#243).

**A test can start as a new tab** (#249): with `"start_as": "new_tab"`, it gets the saved
session's cookies and localStorage but empty sessionStorage, the way a second tab of the same
logged-in browser would. That's where Juice Shop loses the basket. Run the same test both
ways and compare.

**Before a bug is reported** (#177), each test it cites runs again from a fresh browser
context. It counts as reproduced only if the replay lands on the same screen with the same
trusted signals. A replay that doesn't reach its state, doesn't send the action, or reads a
page that hasn't rested can't tell either way, so the bug is lowered. The session checks
above run again first, because a replay from an expired session reproduces the server's
refusal every time.

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
| `reference.py` | loads a web-recon `ontology.json` as the carried reference: the reachable states, the navigation path to each (so a test can start there), the safe `(state, control)` pairs the sweep runs, and the Driver's guide to the screens with their routes. Pure: unit-tested against a fixture ontology with no browser. |
| `session.py` | the only browser-touching module: a Playwright browser launched once, reusing web-recon's `capture`/`signature`/`appearance`/`visual_diff`. Reaches a state by replaying its path, actuates one control, classifies the transition. A click looks the control up on the live page by web-recon's role and name before falling back to the saved selector, which is positional and can shift. If another element covers the control (a cookie notice, say), it sends the click event to the control itself and reports `covered_by`, because a forced click would land on the cover. The browser never leaves the product's site: Chrome's own interception stops any main-frame navigation to another origin, including through a redirect, and the result says where it would have gone in `blocked_off_site` (#308). Every restart starts from a fresh browser session (no cookies or storage), and every read waits for a rested page: no DOM change for 0.4 s and no request in flight, at most 8 s, else the reading is flagged `settled: false`. Each result carries `signals`, the before/after diff: console errors, failed requests, storage and cookie keys changed (never their values), controls added or removed (#143). Only signals that pass every trust check are in `signals`: a request started after the action, on the product's own origin, nothing that also changes while the state sits idle (learned once per state per run), and a rested page. The rest go to `signals_weak`, as hints, and so does everything when the action wasn't sent. Screenshots are never a signal. Every browser context is recorded as video unless `WEB_GUI_VIDEO=off`, and at the end `save_videos` keeps only the videos of the tests the run cites, in `<out-dir>/videos` (#286). Never Playwright traces: they hold cookies and tokens. The idle watch looks three times over about 6 s and learns controls too (a carousel). `signal_audit.py` checks all of this against a live site with no model calls: `python -m engine.adapters.web_gui.signal_audit --ontology <map> --url <url> --name <site>`. Where a known state is expected (the start page, the state a test targets), a capture that doesn't match is taken again, up to twice, since a page still loading reads as another state. |
| `score.py` | scores a run against a target's known problems (`test-targets/known-problems/<target>.json`): found X of Y, by evidence. An observation finds a problem when a test it cites recorded the problem's signal and its claim names it; problems a test saw but nobody reported are listed apart from those missed (#277). `python -m engine.adapters.web_gui.score --known <list> --run <output.json>`. The CI workflow scores every run. |
| `sweep.py` | runs every (state, control) pair in the map once, as the same tab and as a new tab, with no model, and lists every problem the harness observed (console errors, failed requests), deduplicated: what a run could have found at all (#276). A candidate list for a person to review into a target's known problems. `python -m engine.adapters.web_gui.sweep --ontology <map> --url <url> --session <file> --out runs/sweep/<target>.json`; `--follow-discoveries` also runs the actions on screens found on the way. |
| `login_recipe.py` | logs in with no person, from a recipe file (credentials generated per run or read from the environment, then steps: requests, goto, click, fill), and saves the session the way `save_session.py` does. A recipe that sends requests only runs against this machine. Used by the CI pipeline (#255): `python -m engine.adapters.web_gui.login_recipe --recipe test-targets/login-recipes/juice-shop.json --url http://127.0.0.1:3000 --product juice-shop`. |
| `save_session.py` | saves a browser session (cookies, localStorage, and sessionStorage, which Playwright leaves out and web_gui puts back with an init script) for `WEB_GUI_SESSION` and Spoor's `--session`: a person logs in, or a condition (`--until`) decides when. Writes only where git ignores, prints only names. |
| *(discoveries)* | when an action reaches a screen the carried map doesn't have, its result records it (`discovered`): an id from its signature, the path that reached it, and its controls through the safety gate, in a map state's shape. It also joins the run's map (#158): from the next round, the Driver may act on its cleared controls by naming the screen's id as the state, and the harness reaches it by replaying the steps that found it. The Driver sees the controls once, then just the id; a screen more than 6 steps from the start doesn't join. `python -m engine.ontology.feedback --sut web_gui --product <slug> --run <output.json>`, or `--learn <slug>` on the run command, writes them into `context_<slug>.json` (#157). With `WEB_GUI_PRODUCT` set, the next run's preflight replays each one once, the most reached first, up to 20, and the ones that land where they did join the map the Driver starts with, labelled "found by an earlier run" (#159). |
| `signal_audit.py` | runs `act()` many times against one site (fresh sessions, every pair repeated) and reports weak spots in signal handling: trusted signals that don't reproduce, screen classes that flip, why signals went weak, unsettled reads, unstable idle noise. No model calls. |
| `from_spoor.py` | turns a Spoor exploration map into this `ontology.json`, by replaying Spoor's paths live and captures each page the way web-recon does. It keeps everything stable Spoor reached, marking each control's gate verdict (`committing`) and whether Spoor reached it (`spoor_reached`); see "Running it". `map_errors` is the contract with Spoor's map format: the `spoor contract` CI job checks a real, pinned Spoor's output with it (`engine/requirements-spoor.txt`, #144), logged out and from a saved session, and converts the session map end to end (#156). |
| `adapter.py` | the `SUTAdapter`: casting tool schema/prompt/validation (a pair outside the carried map is refused before actuation), `execute_test`, the typed `outcome_for` envelope, and report rendering. |
