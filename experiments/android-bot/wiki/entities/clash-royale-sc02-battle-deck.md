---
type: Entity
entity_kind: screen
title: "sc02 — Clash Royale Battle Deck screen"
description: The deck view, with 15 measured elements, Decks/Collection tabs, arrows inside the bottom nav bar, and the only measured route into the King Tower panel.
tags: [clash-royale, screen, sc02]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc02"
---

# sc02 — Clash Royale Battle Deck screen

- **Kind:** screen
- **Summary:** the deck view. Model description: "Shows the player's current battle deck
  of cards with levels and upgrade progress, and allows navigation between
  Decks/Collection tabs and bottom navigation icons (chest, cards, battle, clan,
  tournament)."[^recon]

![sc02](../../out/Clash%20Royale-20260903-153913/images/sc02-v1.png)

## Details

Seen **10 times**, first at action 1. **562 of 576 cells held still**; **1 cell moves
with no input at all**. **4 appearances stored**; the only stated difference is `sc02-v3`,
where the Decks tab "appears highlighted/selected in blue".[^recon]

The still-map's moving cells sit in the top bar (row 0, x 10–19; row 1, x 12–13), row 7
around x 9 and 13, and row 11 at x 26 and 28–29 — the last being the top-right of the
card area, not the nav bar.[^recon]

The report flags this screen and [sc07](clash-royale-sc07-collection.md) as a possible
duplicate: "**sc02** 'Clash Royale - Battle Deck screen' and **sc07** 'Clash Royale -
Collection/Card Deck screen'" are either one place the pixel test failed to merge, or two
places whose names are not specific enough.[^recon] Note that sc02 → sc07 is itself an
observed transition, which argues they are two places.

### Elements — measured

| Element | Point | Box `[x, y, w, h]` | Note |
|---|---|---|---|
| Decks tab — currently selected | (0.290, 0.150) | `[0.245, 0.128, 0.090, 0.045]` | a point |
| Collection tab — unselected | (0.710, 0.157) | `[0.665, 0.128, 0.090, 0.060]` | |
| Battle Deck banner — header label | (0.580, 0.232) | `[0.535, 0.202, 0.090, 0.060]` | |
| Card slots — 8 cards with level and upgrade bars | (0.500, 0.550) | `[0.455, 0.527, 0.090, 0.045]` | a point |
| Currency: Gold — with plus/add button | (0.580, 0.028) | `[0.535, 0.011, 0.090, 0.034]` | refused: gold→gems→money |
| Currency: Gems — with plus/add button | (0.850, 0.028) | `[0.805, 0.011, 0.090, 0.034]` | refused: `gem` |
| Trophy/deck icon — deck count, top-left | (0.048, 0.034) | `[0.001, 0.005, 0.094, 0.058]` | |
| Ad/offer icon — small banner with close X | (0.380, 0.036) | `[0.335, 0.010, 0.090, 0.053]` | refused: `offer` |
| Chest icon — bottom nav | (0.080, 0.930) | `[0.035, 0.907, 0.090, 0.045]` | refused: `shop` |
| Collection nav icon — active | (0.290, 0.930) | `[0.245, 0.907, 0.090, 0.045]` | a point |
| Battle icon — crossed swords/axes | (0.570, 0.930) | `[0.525, 0.907, 0.090, 0.045]` | a point |
| Clan icon | (0.740, 0.930) | `[0.695, 0.907, 0.090, 0.045]` | refused: donations |
| Tournament/rank icon | (0.910, 0.930) | `[0.865, 0.907, 0.090, 0.045]` | a point |
| **Left arrow** — "possibly switch deck slot left" | (0.190, 0.930) | `[0.145, 0.907, 0.090, 0.045]` | a point |
| **Right arrow** — "possibly switch deck slot right" | (0.470, 0.930) | `[0.425, 0.907, 0.090, 0.045]` | a point |

The two arrows sit *between* the nav icons at the same y = 0.930, interleaved:
0.080 chest, **0.190 ←**, 0.290 collection, **0.470 →**, 0.570 battle, 0.740 clan,
0.910 rank. The model reads them as deck-slot arrows; sc06 and sc08 carry arrows at the
same y and read them as scrolling the nav bar instead. Neither reading was tested. See
[The bottom navigation bar](clash-royale-bottom-navigation-bar.md).

### Actions probed — 6

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `click:0.030,0.500` | nothing visible changed | – | 0 | 577 ms |
| `click:0.030,0.850` | went to another screen | [sc09](clash-royale-sc09-king-tower-info.md) | 568 | 1243 ms |
| `click:0.970,0.500` | same screen, different appearance | – | 1 | 884 ms |
| `drag:0.500,0.500>0.250,0.500` | went to another screen | [sc01](clash-royale-sc01-main-screen.md) | 528 | 973 ms |
| `drag:0.500,0.500>0.500,0.250` | went to another screen | [sc07](clash-royale-sc07-collection.md) | 519 | 1377 ms |
| `drag:0.500,0.500>0.750,0.500` | nothing visible changed | – | 0 | 1563 ms |

Three of six exits — the most connected screen in the model. Note the asymmetry with
sc01: a *left* centre drag returns to sc01 from here, and a *right* centre drag from sc01
arrives here.

`click:0.030,0.850` is the one measured route into the King Tower panel, and it is not on
any element in the list above — (0.030, 0.850) is a bare-margin probe near the left edge.
Whatever it hits is unnamed.

### Not tried

Twenty entries. Ten carry a stated reason (gold counter ×2, gem counter ×2, Pass Royale ×2
— one of them attached to the *Collection tab* at (0.710, 0.150), Clan tab ×2, Shop tab,
Battle-button downward drag); the other ten are "no verdict for this action", including
the Decks tab, the card slots, the deck banner, the two arrows, and the ad/offer
X.[^recon]

The Pass Royale reason landing on the Collection tab is a coordinate-based refusal
misfiring: the denylist is keyed to a point, and (0.710, 0.150) on this screen is a tab,
not a banner. Treat the Collection tab as unmodelled rather than unsafe.

## Related

- [sc07 — Collection/Card Deck screen](clash-royale-sc07-collection.md) — the possible duplicate
- [sc09 — King Tower info panel](clash-royale-sc09-king-tower-info.md) — reachable from here
- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md)
- [The top status bar](clash-royale-top-bar.md)
- [The observed navigation map](../concepts/clash-royale-navigation-map.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc02 - Clash Royale - Battle Deck screen" and "Screens the model named the same thing"
