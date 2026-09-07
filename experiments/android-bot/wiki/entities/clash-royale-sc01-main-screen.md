---
type: Entity
entity_kind: screen
title: "sc01 — Clash Royale main/home screen"
description: The game's hub screen and the most-visited screen in the model, with 20 measured elements, three exits and five currency or offer targets refused on policy.
tags: [clash-royale, screen, sc01]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc01"
---

# sc01 — Clash Royale main/home screen

- **Kind:** screen
- **Summary:** the hub. Model description: "Main hub screen of the mobile game Clash
  Royale, showing the player's clan status, currency counts, current arena/battle deck,
  chest slots, and a central Battle button to start a match."[^recon]

![sc01](../../out/Clash%20Royale-20260903-153913/images/sc01-v1.png)

## Details

Seen **16 times**, first at action 0. **542 of 576 cells held still**; **5 cells move
with no input at all**, so two frames differing only there count as the same appearance.
**5 appearances stored** (`sc01-v1` … `sc01-v5`); three of them differ only in the
Battle tab's active/highlighted state in the bottom nav.[^recon]

The cells that never held still cluster in three bands of the still-map: the top row
(around x 10–19), rows 10–12 in the same x range, and row 16 spanning x 10–21 — the top
bar, the clan/arena area, and the bottom navigation bar.[^recon]

### Elements — measured

Twenty elements, each with a point *and* a box, so these coordinates are measurements
rather than model guesses. Refused targets are marked; see
[Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md).

| Element | Point | Box `[x, y, w, h]` | Note |
|---|---|---|---|
| Trophy/level badge — level 18 with progress bar | (0.050, 0.028) | `[0.005, 0.005, 0.090, 0.045]` | |
| Coin count — 113 coins with a + button to buy more | (0.570, 0.027) | `[0.525, 0.010, 0.090, 0.034]` | refused: `buy` |
| Gem count — 100 gems with a + button to buy more | (0.850, 0.028) | `[0.805, 0.010, 0.090, 0.035]` | refused: `buy` |
| Close button (X) — near an ad/banner icon | (0.420, 0.031) | `[0.375, 0.010, 0.090, 0.042]` | |
| Friends/social icon | (0.650, 0.107) | `[0.605, 0.075, 0.090, 0.063]` | |
| Card collection icon | (0.780, 0.107) | `[0.735, 0.075, 0.090, 0.063]` | |
| Menu (hamburger) icon | (0.916, 0.107) | `[0.865, 0.075, 0.102, 0.063]` | |
| Pass Royale banner — locked promotion | (0.780, 0.220) | `[0.735, 0.198, 0.090, 0.045]` | refused: `purchas` |
| Clan name "Testing / No Clan" | (0.100, 0.200) | `[0.055, 0.177, 0.090, 0.045]` | |
| Arena/battle scene — 3D rendering | (0.500, 0.450) | `[0.455, 0.427, 0.090, 0.045]` | |
| Chest slots — four chest icons | (0.500, 0.650) | `[0.455, 0.627, 0.090, 0.045]` | |
| Deck icon | (0.200, 0.830) | `[0.155, 0.807, 0.090, 0.045]` | |
| **Battle button** — large orange button | (0.500, 0.830) | `[0.455, 0.807, 0.090, 0.045]` | refused: starts a live match |
| Trophy road icon | (0.790, 0.830) | `[0.745, 0.807, 0.090, 0.045]` | |
| Bottom nav: chest icon | (0.080, 0.957) | `[0.035, 0.927, 0.090, 0.060]` | refused: `shop` |
| Bottom nav: cards icon | (0.243, 0.957) | `[0.168, 0.927, 0.149, 0.060]` | |
| Bottom nav: battle icon (crossed swords) — selected | (0.502, 0.950) | `[0.427, 0.927, 0.149, 0.045]` | |
| Bottom nav: clan icon | (0.750, 0.957) | `[0.705, 0.927, 0.090, 0.058]` | refused: donations |
| Bottom nav: tournament/rank icon | (0.910, 0.942) | `[0.865, 0.912, 0.090, 0.060]` | |
| Browser tab label | (0.504, 0.981) | `[0.445, 0.968, 0.118, 0.027]` | not game surface |

The last one is the report's own evidence that this is not a native app: text at the very
bottom naming a website and Chrome, "indicating this is a browser tab, not a native
app".[^recon] Anything aimed below y ≈ 0.968 is aimed at the browser.

Note that seven of the twenty boxes are exactly `0.090 × 0.045` and centred on the point,
and the report marks each of those seven "(a point)". A `0.090 × 0.045` centred box on
this screen is an absence of measurement, not a measured extent — so the Battle button,
the chest slots, the arena and the trophy road have a location but no known size.

### Actions probed — 9

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `click:0.030,0.500` | nothing visible changed | – | 0 | 797 ms |
| `click:0.030,0.850` | same screen, different appearance | – | 1 | 1222 ms |
| `click:0.200,0.970` | went to another screen | [sc02](clash-royale-sc02-battle-deck.md) | 530 | 1481 ms |
| `click:0.970,0.500` | same screen, different appearance | – | 4 | 344 ms |
| `drag:0.500,0.500>0.250,0.500` | went to another screen | [sc03](clash-royale-unnamed-screens.md) | 555 | 1634 ms |
| `drag:0.500,0.500>0.500,0.250` | same screen, different appearance | – | 1 | 463 ms |
| `drag:0.500,0.500>0.750,0.500` | went to another screen | [sc02](clash-royale-sc02-battle-deck.md) | 528 | 1566 ms (×2) |
| `scroll:down3:0.500,0.500` | same screen, different appearance | – | 1 | 1090 ms |
| `scroll:up3:0.500,0.500` | nothing visible changed | – | 0 | 1106 ms |

Two different actions — a tap at (0.200, 0.970) and a rightward centre drag — both land
on sc02, changing ~530 of 576 cells. A leftward centre drag from the same origin lands on
sc03 instead. Nothing on this screen was ever observed to reach sc04, sc06, sc07, sc08,
sc09, sc10 or sc11.

### Not tried

Twenty-six entries for sc01 in the report's "What was not tried, and why". Thirteen carry
a stated reason — Battle button ×2 (once as a tap, once as a downward drag), gold counter
×3, gem counter ×2, Pass Royale ×2, Clan tab ×2, Shop tab, coin counter. The other
thirteen are "no verdict for this action", including the hamburger menu at
(0.910, 0.100), the friends icon at (0.650, 0.100), the card collection icon at
(0.780, 0.100), the chest slots, the deck icon, the trophy road icon, and the cards and
battle nav tabs.[^recon]

## Related

- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md) — five icons here,
  at x 0.080 / 0.243 / 0.502 / 0.750 / 0.910
- [The top status bar](clash-royale-top-bar.md) — level badge, coins, gems, ad/banner X
- [The observed navigation map](../concepts/clash-royale-navigation-map.md)
- [Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, section "sc01 - Clash Royale main/home screen"
