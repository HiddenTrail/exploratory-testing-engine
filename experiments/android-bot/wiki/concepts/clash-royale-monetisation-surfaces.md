---
type: Quality Concept
title: "Monetisation surfaces"
description: Where real money is reachable in this client — one €1.19 price bar, a currency + button on every screen with a status bar, three banner offers, and a whole tab — and why refusing them by coordinate did not keep the run out of the shop.
tags: [clash-royale, monetisation, risk, safety]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — element lists and 'What was not tried, and why'"
guidelines_refs: []
---

# Monetisation surfaces

## What it is

The set of controls in this client that lead toward spending, mapped from the recon
report.[^recon] It matters for two reasons: it is the largest single block of the interface
that is deliberately unmodelled, and it is the one place where the model's caution is a
product finding in its own right — **money is reachable from nearly every screen the game
has**.

## Current state / findings

### The one hard fact

**A €1.19 price bar sits at (0.500, 0.660) on [sc08](../entities/clash-royale-sc08-offers-shop.md).**
The model's own description: "purchase button showing real-money price for the Royal Starter
Pack; tapping it would spend real money."[^recon] The bundle above it lists its contents —
10 000 coins, 500 gems, and ×20 of a card — and a countdown timer runs on the banner.

Everything else on this page is a "likely" or a "possibly". This is the only place where a
currency symbol, an amount and a purchase target all appear together.

### Where money is reachable

| Surface | Where | Screens |
|---|---|---|
| **Real-money price bar** | (0.500, 0.660) | sc08 |
| **Gem counter with + button** | (0.850, 0.028) / (0.860, 0.030) / (0.850, 0.030) | sc01, sc02, sc07, sc08 |
| **Gold / coin counter with + button** | (0.570, 0.027) / (0.580, 0.028) / (0.620, 0.030) / (0.650, 0.030) | sc01, sc02, sc07, sc08 |
| **Pass Royale banner** (paid subscription) | (0.780, 0.220) | sc01 |
| **Offer banners** (Royal Starter Pack, Upgrade Special, a third cut off) | (0.500, 0.310) / (0.500, 0.720) / (0.500, 0.780) | sc08 |
| **Bundle contents panel** | (0.500, 0.530) | sc08 |
| **Info icons beside offers** | (0.850, 0.190), (0.900, 0.660) | sc08 |
| **Shop / chest tab in the bottom nav** | 0.080–0.160 at y ≈ 0.94 | sc01, sc02, sc04, sc06, sc08 |
| **Ad / offer icon in the top bar** | ≈ (0.380, 0.036–0.050) | sc01, sc02, sc04, sc06, sc07, sc08 |

Four of the six screens that have a status bar carry a currency "+" button, and five of the
six with a navigation bar carry the Shop tab. **There is no meta-game screen in this model
from which money is more than one tap away**, except the two modal panels that have neither
bar.

The report's own two-line reasoning for treating both currencies alike is worth keeping,
because it is a genuine product-structure claim rather than a policy:[^recon]

> the gem counter and its + button - the entrance to the gem shop, which is a real-money
> purchase flow

> the gold counter and its + button - gold is bought with gems and gems with money, so this
> is the same purchase flow one step back

That makes gold a second-order money surface: a hard-currency conversion sits between the
gold "+" and a card, but nothing else does.

### 28 money refusals, and one that mattered

The "What was not tried, and why" list carries **28 entries refused on a money reason** —
gold counter, gem counter, Pass Royale, Shop tab, coin counter — spread across sc01 (9),
sc02 (7), sc07 (2), sc08 (4), sc11 (3), sc04 (1), sc06 (1) and sc09 (1). Twenty of the same
refusals are echoed in the "What went wrong" list, which additionally names the word in each
element's description that triggered it: `buy`, `purchas`, `shop`, `gem`, `offer`, `bundle`,
`€`, `price`.[^recon] Every purchase surface in the table above was refused at least once.
**No purchase was made and no purchase dialog was opened.**

But the refusals are keyed to **coordinates, screen by screen**, and that has two consequences
the report's own data shows:

1. **A coordinate denylist does not close a route a gesture opens.** sc08 — the shop — was
   reached anyway, by `drag:0.500,0.500>0.750,0.500` from
   [sc07](../entities/clash-royale-sc07-collection.md), which changed 542 of 576 cells. Every
   Shop tab in the model is refused, and the run still ended up on the storefront with the
   €1.19 bar on screen. It did not press it; nothing structural stopped it from being there.
2. **A point refused on one screen is refused on every screen.** The clearest case is
   [sc09](../entities/clash-royale-sc09-king-tower-info.md), where (0.914, 0.049) is a
   measured red X and was refused as "the entrance to the gem shop". The same pattern refuses
   sc02's Collection tab as "the Pass Royale banner", sc06's right arrow as "the Clan tab",
   and two coordinates on sc11 — a screen with no status bar at all — as gold and gem
   counters.

### What the money policy costs

The refusals removed, from the model: the whole shop tab on five screens, both currency
counters on four screens, the Pass Royale banner, four offer banners, two info icons, and
(by misfire) one close button, one tab and one nav arrow. That is the single largest block of
unmodelled interface — see
[Surfaces that are named but unmodelled](clash-royale-unmodelled-surfaces.md), which counts
the rest.

## Implications for Guidelines / Playbook

- **Key the refusal to the element, not to the point.** The point is only stable within one
  screen, and this model contains four cases of a point meaning something different one screen
  over — one of which removed the only exit from a panel.
- **Refuse destinations as well as controls.** A screen classified as a purchase surface
  should end a run when it is *reached*, however it was reached. Refusing every labelled route
  to sc08 did not prevent arriving there sideways.
- **The €1.19 bar is the tripwire worth naming explicitly.** It is a measured coordinate on a
  known screen with a known effect. Anything that gets within one input of it should stop.
- **Gold is not a safe currency.** Treat the gold "+" as a money surface, on the report's own
  reasoning, not as an in-game resource control.
- **The ad/offer X is the exception worth testing.** It is described on six screens as a
  *close* control and refused on only one, yet never pressed on any. It is the one
  monetisation-adjacent control whose likely effect is dismissal rather than purchase — and
  two panels in this model could not be dismissed.

## Related

- [sc08 — Offers / Shop screen](../entities/clash-royale-sc08-offers-shop.md)
- [The top status bar](../entities/clash-royale-top-bar.md)
- [The bottom navigation bar](../entities/clash-royale-bottom-navigation-bar.md)
- [Surfaces that are named but unmodelled](clash-royale-unmodelled-surfaces.md)
- [Panels that swallow input](clash-royale-panels-that-swallow-input.md) — where a money refusal removed an exit
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
