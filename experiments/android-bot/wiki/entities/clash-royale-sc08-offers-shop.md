---
type: Entity
entity_kind: screen
title: "sc08 — Offers / Shop screen"
description: The real-money storefront, reached by a single drag from the collection screen, carrying a €1.19 price bar and eleven refused targets — the highest-risk screen in the model.
tags: [clash-royale, screen, sc08, monetisation]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc08"
---

# sc08 — Offers / Shop screen

- **Kind:** screen
- **Summary:** the storefront. Model description: "Displays in-game store offers (e.g.,
  'Royal Starter Pack', 'Upgrade Special') where players can purchase bundles of currency
  or cards using real money; bottom navigation bar allows switching between game sections
  like Shop, Cards, Battle, Clan, etc."[^recon]

![sc08](../../out/Clash%20Royale-20260903-153913/images/sc08-v1.png)

> **This screen was reached, and it is the screen the money policy exists to avoid.** It
> was not reached by tapping the Shop tab — every Shop tab in the model is refused — but by
> a rightward centre drag from [sc07](clash-royale-sc07-collection.md). A denylist keyed to
> coordinates does not close a route that a gesture opens.

## Details

Seen **3 times**, first at action 15 — the last screen the run discovered. **559 of 576
cells held still**; **17 cells move with no input at all**, the second-highest in the
model. **3 appearances stored**, with no stated difference between them.[^recon]

The still-map is the busiest of any screen: cells that never held still are scattered
across rows 1–4 (x 1, 6, 10, 12, 14, 22, 27–28), rows 8–9 at x 30, and row 11 at x 1 —
consistent with countdown timers on the offer banners, which the model's own descriptions
mention twice ("with a countdown timer").[^recon]

### Elements — model-placed only

No boxes were measured. Eleven of the eighteen were refused on the money policy.[^recon]

| Element | Around | Model's reading | Refused? |
|---|---|---|---|
| Offers banner | (0.500, 0.190) | header title, non-interactive decorative banner | yes: `offer` |
| info icon (i) near Offers | (0.850, 0.190) | likely opens a tooltip/explanation dialog | yes: `offer` |
| Royal Starter Pack banner | (0.500, 0.310) | title of a purchasable bundle with a countdown timer | yes: `purchas` |
| Bundle contents panel | (0.500, 0.530) | shows 10000 coins, 500 gems, and x20 of a card | yes: `bundle` |
| **€1.19 price bar** | (0.500, 0.660) | "purchase button showing real-money price … tapping it would spend real money" | yes: `€` |
| info icon (i) near price | (0.900, 0.660) | likely a tooltip | yes: `price` |
| Upgrade Special banner | (0.500, 0.720) | another purchasable offer with countdown timer | yes: `purchas` |
| green partial panel | (0.500, 0.780) | top of another offer panel, cut off by screen edge | yes: `offer` |
| top bar: cards/trophy icon | (0.050, 0.030) | shows level or trophy count "18" | no |
| top bar: coin count "113+" | (0.650, 0.030) | likely opens purchase screen for coins | yes: `purchas` |
| top bar: gem count "100+" | (0.850, 0.030) | likely opens purchase screen for gems | yes: `purchas` |
| small popup icon top center | (0.380, 0.045) | possibly a dismissable notification or ad | no |
| bottom nav: Shop | (0.160, 0.940) | currently active tab, a chest labelled "Shop" | yes: `shop` |
| bottom nav: right arrow | (0.310, 0.940) | "arrow to scroll bottom nav or go to next section" | no |
| bottom nav: Cards icon | (0.410, 0.940) | card collection | no |
| bottom nav: Battle icon | (0.580, 0.940) | battle mode | no |
| bottom nav: Clan icon | (0.750, 0.940) | clan section | no |
| bottom nav: Trophy/rank icon | (0.910, 0.940) | rankings or trophy road | no |

Two things about this list are worth carrying elsewhere:

- **The price bar names a currency and an amount** — €1.19 — which is the only hard
  monetisation fact in the whole model, as opposed to the many "likely opens a purchase
  screen" guesses. See [Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md).
- **The Shop tab sits at x = 0.160 here**, against 0.080 on sc01 and sc02, 0.100 on sc04
  and 0.088 on sc06 — and there is a right arrow at 0.310 immediately after it. The bar is
  not in the same place on this screen. See
  [The bottom navigation bar](clash-royale-bottom-navigation-bar.md).

### Actions probed — 1

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `drag:0.500,0.500>0.750,0.500` | same screen, different appearance | – | 13 | 3008 ms |

The same rightward drag that arrived here does not leave. Thirteen cells changed, which is
in the range of the screen's own animated cells (17), so it may have changed nothing at all
that the drag caused. The saved before and after frames for it are in fact byte-identical,
which supports the "changed nothing" reading while also making the 13 unreproducible — see
[the saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md).

**No exit from this screen was ever observed.** Everything that could plausibly be one is
refused (the Shop tab) or unmodelled (the other four nav icons and the right arrow).

### Not tried

Nineteen entries. Eight carry a stated reason: the Shop tab, the gold counter, the gem
counter, two banner targets refused as the Battle button at (0.500, 0.720) and
(0.500, 0.780), the Clan tab, a Pass Royale refusal landing on the info icon at
(0.850, 0.190), and a downward centre drag as the Battle button.[^recon] Eleven are "no
verdict for this action" — including **the €1.19 price bar itself at (0.500, 0.660)**,
which the "What went wrong" list separately records as refused on `€`. The two lists
disagree about that one control; the refusal is the safe reading and the one that held —
the price bar was never pressed.

## Related

- [sc07 — Collection/Card Deck screen](clash-royale-sc07-collection.md) — the only observed way in
- [Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md)
- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md)
- [The top status bar](clash-royale-top-bar.md)
- [The observed navigation map](../concepts/clash-royale-navigation-map.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc08 - Offers / Shop screen", "What went wrong" and "What was not tried, and why"
