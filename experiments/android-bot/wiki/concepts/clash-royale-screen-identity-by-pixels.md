---
type: Quality Concept
title: "Screen identity is a pixel measurement, not a name"
description: How the eleven screens were told apart — a 32x18 grid at threshold 0.94 — and the four ways that produces identities a person would not draw the same way.
tags: [clash-royale, method, screen-identity]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — header and 'Screens the model named the same thing'"
guidelines_refs: []
---

# Screen identity is a pixel measurement, not a name

## What it is

Every "screen" in this wiki is a **pixel fingerprint**, not a place someone named. Two
frames are the same screen when a 32 × 18 grid of cell hashes agrees at **0.94 or better**;
the median observed match was **1.0**.[^recon] Names and element descriptions came afterwards,
from a model looking at one screenshot, and only eight of the eleven got one at all.

The report states the principle it follows when the two disagree:[^recon]

> geometry is a measurement and a name is a description

Read every page in this wiki with that split in mind. The coordinates on
[sc01](../entities/clash-royale-sc01-main-screen.md),
[sc02](../entities/clash-royale-sc02-battle-deck.md),
[sc09](../entities/clash-royale-sc09-king-tower-info.md) and
[sc11](../entities/clash-royale-sc11-battle-result.md) are measurements. Every name, every
"likely opens…", and every coordinate on sc04, sc06, sc07 and sc08 is a description.

## Current state / findings

### What the fingerprint does well

- **576 cells is a fine enough grid to notice a tab highlight.** sc01 stored five
  appearances, three of which differ only in the Battle tab's active state in the nav bar,
  and the report says which element differed in each case.
- **It separates self-animating cells from responsive ones.** Each screen records how many
  cells "move with no input at all" — 20 on sc04, 17 on sc08, 11 on sc06, 9 on sc11, 5 on
  sc01, 2 on sc07, 1 on sc02, none on sc09 — and two frames differing *only* there count as
  the same appearance. Without that, a countdown timer on a shop banner would make every
  frame a new screen.
- **It gives a changed-cell count for every action**, which turns out to carry more
  information than the effect label: see
  [the navigation map](clash-royale-navigation-map.md) on 60-cell versus 555-cell "screen
  changes".

### Four ways it produces identities a person would draw differently

**1. Two identities, one name.** The report flags both cases itself rather than merging
them:[^recon]

- sc02 "Battle Deck screen" / sc07 "Collection/Card Deck screen"
- sc04 "Social screen (Clash Royale-like game)" / sc06 "Social screen (Clash Royale-style
  game)"

Its own framing: "either two of these are one place the pixel test failed to merge, or the
names need to be more specific before they reach a wiki." For sc02/sc07 there is evidence for
*two places*: sc02 → sc07 is an observed transition that changed 519 cells. For sc04/sc06
there is no such evidence — each was seen once, and their element lists overlap item for
item.

**2. A panel opening counts as a new screen.** sc04 → sc05 changed **60 of 576 cells** and
sc09 → sc10 changed **188**. Both crossed the 0.94 threshold, so both are new identities;
neither is a navigation. The threshold is doing what it was set to do, and the word "screen"
is doing something it was not.

Both of those counts are also the ones that fail a check against the saved images — and
`sc10-v1.png` is byte-identical to `sc09-v1.png`, which no threshold can turn into two
identities. So this particular illustration is on shaky evidence even though the general point
stands: see
[the saved frames do not always match the changed-cell counts](clash-royale-frames-vs-counts.md).

**3. A single sighting produces a meaningless still-map.** sc03, sc04, sc05, sc06, sc09 and
sc10 all report "576 of 576 cells held still". Five of those six were seen exactly once, so
that is not stability — there was no second frame to disagree with. Only sc09's 576/576 is
earned, over nine sightings; the counts that mean something are sc01 (542/576), sc02
(562/576), sc07 (575/576), sc08 (559/576), sc09 (576/576) and sc11 (548/576).

**4. "Different appearance" and "nothing changed" can both be true of one frame pair.** On
sc11 this happens three times: taps at (0.030, 0.500) and (0.030, 0.800) are recorded as
"same screen, different appearance" with **0** changed cells. The identity test matched a
different stored appearance while the change test saw nothing move. On a screen with nine
self-animating cells, that is what capturing at the wrong moment looks like — and it is the
one place where the two measurements audit each other.

### The three unnamed screens are a hole in the description layer, not the measurement layer

sc03, sc05 and sc10 have fingerprints, sightings and screenshots. What they lack is any pass
by a model to name them and list their elements.[^recon] They are as well *identified* as any
other screen and entirely un*described* — the cleanest illustration of the split this page is
about. See [the unnamed screens](../entities/clash-royale-unnamed-screens.md).

## Implications for Guidelines / Playbook

- **Never let a name carry a claim a measurement should.** When a test asserts something
  about a screen, it should assert it against a fingerprint, a coordinate or a cell count —
  never against "the Social screen", which is two screens.
- **Keep the changed-cell count in the log.** It is the only thing distinguishing a
  navigation from an overlay, and the effect label does not.
- **Do not read a still-map from a single sighting.** Require at least two visits before
  treating "held still" as a property of the screen.
- **Duplicate names are a signal to re-measure, not to merge.** Both flagged pairs need one
  more visit each: sc04/sc06 to see whether they are one place, sc02/sc07 to see why two
  places got names that close.
- **Un-named but well-identified screens are the cheapest coverage available.** Three of
  eleven screens need nothing but a second visit and one description pass.

## Related

- [The observed navigation map](clash-royale-navigation-map.md)
- [The saved frames do not always match the changed-cell counts](clash-royale-frames-vs-counts.md) — the same measurement checked against its own artefacts
- [Panels that swallow input](clash-royale-panels-that-swallow-input.md) — where the two measurements disagree
- [sc03, sc05, sc10 — the three unnamed screens](../entities/clash-royale-unnamed-screens.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
