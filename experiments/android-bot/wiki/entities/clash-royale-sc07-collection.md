---
type: Entity
entity_kind: screen
title: "sc07 — Clash Royale Collection/Card Deck screen"
description: The card collection view, reachable only by an upward drag from the deck screen, whose entire bottom navigation bar was placed outside the window and therefore never modelled.
tags: [clash-royale, screen, sc07]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc07"
---

# sc07 — Clash Royale Collection/Card Deck screen

- **Kind:** screen
- **Summary:** the card collection. Model description: "Shows the player's card
  collection, current deck with king/princess towers, currency counts (gold, gems,
  elixir), and level/upgrade progress for each card. Bottom navigation bar allows
  switching between game sections."[^recon]

![sc07](../../out/Clash%20Royale-20260903-153913/images/sc07-v1.png)

## Details

Seen **twice**, first at action 14 — the latest first-sighting of any named screen.
**575 of 576 cells held still**; **2 cells move with no input at all**. **2 appearances
stored**, with no stated difference between them. The one cell that never held still is
row 6, x 26.[^recon]

Flagged with [sc02](clash-royale-sc02-battle-deck.md) as a possible duplicate: "'Clash
Royale - Battle Deck screen' and 'Clash Royale - Collection/Card Deck screen'".[^recon]
Against that: sc02 → sc07 is an observed transition (an upward centre drag), so at the
moment the drag was sent the two frames differed by 519 of 576 cells. They are two
appearances at minimum, whatever they are called.

### Elements — model-placed only, and five of them unplaceable

No boxes were measured. Worse, **five of the thirteen elements have no coordinates at
all**.[^recon]

| Element | Around | Model's reading |
|---|---|---|
| Gold count 113 with + button | (0.620, 0.030) | currency display and purchase/add button — refused: `purchas` |
| Gems count 100 with + button | (0.860, 0.030) | currency display and purchase/add button — refused: `purchas` |
| Card level 18 with card icon | (0.100, 0.030) | player level / collection indicator |
| Card thumbnails (various characters, Level 1-3) | (0.500, 0.250) | collection cards with upgrade progress bars |
| Elixir drop icon with 3.6 | (0.130, 0.440) | resource counter |
| King/Princess tower deck preview with pencil edit icon | (0.400, 0.850) | current deck display and edit-deck button |
| Small card level panel (Level 1, 1/2) | (0.870, 0.850) | single card slot preview |
| Small overlay icon top center (circular logo with X and arrow) | (0.380, 0.050) | possibly an ad or notification popup overlay |
| Bottom nav: chest icon | **unplaced** | chests/rewards |
| Bottom nav: Collection (cards icon, highlighted) | **unplaced** | current screen indicator |
| Bottom nav: crossed axes icon | **unplaced** | battle/shop |
| Bottom nav: clan/social icon with notification dot | **unplaced** | clan |
| Bottom nav: shield/sword icon | **unplaced** | tournament/events |

All five were dropped for the same reason, recorded once per element: "the vetting call put
it at [0.09, 1.33], which is not a point inside the window, so there is nothing to
tap".[^recon] The five x values were 0.09, 0.35, 0.58, 0.75 and 0.9 — plausible nav
spacing — but every y was **1.33**, a third of a window height below the bottom edge.

The consequence is concrete: **sc07 has no modelled navigation bar.** Every route out of
this screen through the nav bar is unreachable in the current model, and the one action
that was tried does not use it.

The elixir counter reading "3.6" is the only place in the whole model where an elixir value
appears. The report calls it a "resource counter" and says nothing more; what it counts is
not established here.

### Actions probed — 1

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `drag:0.500,0.500>0.750,0.500` | went to another screen | [sc08](clash-royale-sc08-offers-shop.md) | 542 | 3050 ms |

One probe, and it lands on the **shop**. 3050 ms to settle, against 344–1634 ms for every
transition on sc01, sc02, sc04 and sc06 — see the settle-time caveat in
[the source summary](../summaries/clash-royale-recon-report-2026-09-03.md).

### Not tried

Nine entries. Three carry a stated reason — gold counter at (0.620, 0.030), gem counter at
(0.860, 0.030), and a downward centre drag refused as the Battle button. Six are "no
verdict for this action": the level badge, the card thumbnails, the elixir counter, the
deck preview with its edit pencil, the card level panel, and the top-centre overlay
X.[^recon] The five unplaced nav icons do not appear in this list at all — there was no
point to refuse.

## Related

- [sc02 — Battle Deck screen](clash-royale-sc02-battle-deck.md) — the possible duplicate, and the only way in
- [sc08 — Offers / Shop screen](clash-royale-sc08-offers-shop.md) — where the one probe led
- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md) — absent from this screen's model
- [The top status bar](clash-royale-top-bar.md)
- [Surfaces that are named but unmodelled](../concepts/clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc07 - Clash Royale - Collection/Card Deck screen" and "What went wrong"
