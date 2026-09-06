---
type: Source Summary
title: "Clash Royale recon report, 2026-09-03"
description: Faithful digest of the recon report covering 11 Clash Royale screens, 43 measured screen/action pairs and 120 controls that were named but never activated.
tags: [clash-royale, recon, source]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 15:39"
  - id: shots
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/images/"
    title: "242 screenshots, element close-ups and before/pressed/after triples"
---

# Clash Royale recon report, 2026-09-03

A digest of one source: `report.md` from the recon run in
`experiments/android-bot/out/Clash Royale-20260903-153913/`, plus the 242 images it
links.[^recon][^shots] Nothing has been added that the report does not say. Where the
report's own wording matters it is quoted.

> **The source is not in git.** `out/` is gitignored, so the report and its screenshots
> exist only on the machine that produced them. Image links from these wiki pages
> resolve locally and will be dead in a fresh clone.

## Key points

### The run

- Header line, verbatim: "16 actions in 4.4 minutes (4 per minute) at 1121x1993.
  11 screens, 43 distinct transitions, 0 restarts."[^recon]
- Screen identity: "32x18 grid, match threshold 0.94, median observed match 1.0.
  Committing actions were vetted by the model."[^recon] 32 × 18 = the 576 cells every
  per-screen paragraph counts against.
- **The screen inventory is cumulative, not from these 16 actions.** sc11 is recorded
  "Seen 28 times" and sc01 "Seen 16 times" — more sightings than the run had actions.
  The run's ontology file records that it resumed from an earlier run
  (`Clash Royale-20260903-150041`) and stopped because there was "nothing left to try".
  That file is the ontology layer and is not ingested here; it is named only because the
  sighting counts cannot be read correctly without it.
- The run ended stuck: "tapping home did not reach the frontier - sc01, sc02, sc03,
  sc04, sc05, sc06, sc07, sc08, sc09, sc10 still have untried actions but no observed
  route leads back to them".[^recon]

### The screens

Eleven, `sc01`–`sc11`. Eight got a model-written name and description; **sc03, sc05 and
sc10 are "(unnamed - no model pass)"** and carry nothing but one screenshot, a sighting
count, and an all-still cell map.[^recon]

Per screen the report records: a name and description, sightings and the action index of
the first, how many of 576 cells "held still", how many cells "move with no input at
all", a stored screenshot per distinct appearance, an element list, a 32 × 18 ASCII map
of which cells never held still, and a table of every action tried with its effect,
destination, changed-cell count, settle time and repeat count.

Element geometry comes in two grades, and the report distinguishes them consistently:

- **Measured** — sc01, sc02, sc09, sc11. Each element has a point *and* a box, with the
  trimming stated (`(trimmed except left and right)`, `(a point)`, `(described)`).
- **Model-placed only** — sc04, sc06, sc07, sc08. Each element has "around (x, y)" and
  no box. Five sc07 elements are "unplaced" entirely.

### Two names, possibly one place

The report keeps them separate and flags them:[^recon]

> Kept separate - geometry is a measurement and a name is a description - but worth a
> look: either two of these are one place the pixel test failed to merge, or the names
> need to be more specific before they reach a wiki.

- **sc02** "Clash Royale - Battle Deck screen" and **sc07** "Clash Royale -
  Collection/Card Deck screen"
- **sc04** "Social screen (Clash Royale-like game)" and **sc06** "Social screen
  (Clash Royale-style game)"

### The 43 screen/action pairs

Distributed sc01: 9, sc02: 6, sc04: 1, sc06: 1, sc07: 1, sc08: 1, sc09: 8, sc11: 16.
sc03, sc05 and sc10 have no action table at all. Every pair that changed screen:

| From | Action | To |
|---|---|---|
| sc01 | `click:0.200,0.970` | sc02 |
| sc01 | `drag:0.500,0.500>0.250,0.500` | sc03 |
| sc01 | `drag:0.500,0.500>0.750,0.500` | sc02 (seen twice) |
| sc02 | `click:0.030,0.850` | sc09 |
| sc02 | `drag:0.500,0.500>0.250,0.500` | sc01 |
| sc02 | `drag:0.500,0.500>0.500,0.250` | sc07 |
| sc04 | `drag:0.500,0.500>0.750,0.500` | sc05 |
| sc06 | `drag:0.500,0.500>0.750,0.500` | sc01 |
| sc07 | `drag:0.500,0.500>0.750,0.500` | sc08 |
| sc09 | `drag:0.500,0.500>0.750,0.500` | sc10 |

Ten of forty-three. The remaining thirty-three either changed nothing visible or landed
on the same screen with a different stored appearance. **All sixteen sc11 pairs are in
that remainder.**

### What the report says went wrong

Thirty-three "What went wrong" bullets, of four kinds:[^recon]

1. **No hover map.** "sc11: no hover map - a touch UI has no hover states, so clicks are
   aimed at vetted elements instead."
2. **Failed vetting calls.** Two crashes — `('name')` covering four candidate actions,
   and `('str' object has no attribute 'get')` covering one — left 7 then 2 candidates
   "unplanned again rather than retired unsent".
3. **Money refusals — 20 bullets**, on sc01, sc02, sc07 and sc08, each naming the element
   and the word in its description that stopped it: `buy`, `purchas`, `shop`, `gem`,
   `offer`, `bundle`, `€`, `price`. Same list as the policy group below.
4. **Out-of-window placements.** Five sc07 bottom-nav elements were dropped because "the
   vetting call put it at [0.09, 1.33], which is not a point inside the window, so there
   is nothing to tap". y = 1.33 is below the bottom edge.

Plus the three closing bullets — a tap away from any panel at (0.03, 0.5), a home tap at
(0.5, 0.95), and the failure of the second, quoted above.

## Decisions & commitments

The report's "What was not tried, and why" section holds **120 entries**.[^recon] They
fall into two groups:

- **Refused on a stated policy.** Recurring reasons, quoted once each:
  - the Battle button — "it starts a real-time match against a live opponent, which is
    outside the scope this bot was given (the meta-game only) and cannot be backed out of
    once joined"
  - the gem counter and its + button — "the entrance to the gem shop, which is a
    real-money purchase flow"
  - the gold counter and its + button — "gold is bought with gems and gems with money, so
    this is the same purchase flow one step back"
  - the Pass Royale banner — "a paid subscription offer"
  - the Shop tab — "the whole tab is offers, including real-money ones"
  - the Clan tab — "clan chat and card donations, which are messages and gifts to other
    people and cannot be taken back"
- **"no verdict for this action"** — the majority. No decision was reached, so the
  control is simply unmodelled.

Three entries are individually reasoned rather than pattern-matched, all on sc11, and all
about whether a close control is safe: `click:0.030,0.850`, `click:0.083,0.900` (the X)
and `click:0.200,0.970`. The last is refused because the point "lands on empty background
grass/tree decoration near the bottom, not on the visible X close button".[^recon]

## Risks & open questions

- **sc11 has no measured exit.** Sixteen inputs, including the OK button at
  (0.520, 0.953) and a tap at (0.030, 0.800) in the same corner as the X, and not one
  changed the screen. The X itself at (0.083, 0.900) was never pressed. Carried into
  [Panels that swallow input](../concepts/clash-royale-panels-that-swallow-input.md).
- **Fourteen of sixteen sc11 settle times fall in 3001–3067 ms**, against 296–1634 ms
  everywhere else except sc07 (3050 ms) and sc08 (3008 ms). A cluster that tight reads as
  a fixed ceiling being hit rather than fourteen independent measurements — but the report
  does not state a settle cap, so this is an inference, not a source fact.
- **sc03, sc05, sc10 are unexplained.** Each was reached once, has all 576 cells still,
  and had no action sent. Two were reached by a right-drag from a social screen and from
  the King Tower panel respectively; sc03 by a left-drag from home.
- **No screen was ever observed to lead into sc04, sc06 or sc11.** They were reached,
  since they were seen, but not by any action in the table.
- **The element names are model descriptions, not labels read off the screen.** sc06
  lists "left arrow (bottom nav) - scroll nav tabs left" as a guess ("likely",
  "possibly" recur throughout). Treat every name as a hypothesis about the control and
  every coordinate on sc01/sc02/sc09/sc11 as a measurement.
- **The report contains personal identifiers** — the browser tab label names a real
  person's site, and sc11 names two players. Those are not reproduced on the other pages
  of this wiki.

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
[^shots]: Screenshots and close-ups, `experiments/android-bot/out/Clash Royale-20260903-153913/images/`
