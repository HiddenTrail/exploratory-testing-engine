---
type: Entity
entity_kind: ui-component
title: "The top status bar"
description: The strip at y ≈ 0.03 carrying the level badge, gold and gem counters with their + buttons, and a dismissable ad icon — present on five screens, and refused on four of them.
tags: [clash-royale, ui-component, monetisation]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — element lists for sc01, sc02, sc04, sc06, sc07, sc08"
---

# The top status bar

- **Kind:** ui-component — a persistent status strip
- **Summary:** everything between y ≈ 0.027 and y ≈ 0.050 on the screens that have it: a
  level badge on the left, currency counters with "+" buttons on the right, and a small
  dismissable ad or notification icon near the centre.

## Details

### Positions, screen by screen

| Screen | Level badge | Gold / coins | Gems | Ad icon with X |
|---|---|---|---|---|
| [sc01](clash-royale-sc01-main-screen.md) | 0.050, 0.028 | 0.570, 0.027 | 0.850, 0.028 | 0.420, 0.031 |
| [sc02](clash-royale-sc02-battle-deck.md) | 0.048, 0.034 | 0.580, 0.028 | 0.850, 0.028 | 0.380, 0.036 |
| [sc04](clash-royale-sc04-social.md) | – | – | – | 0.380, 0.040 |
| [sc06](clash-royale-sc06-social.md) | – | – | – | 0.328, 0.043 |
| [sc07](clash-royale-sc07-collection.md) | 0.100, 0.030 | 0.620, 0.030 | 0.860, 0.030 | 0.380, 0.050 |
| [sc08](clash-royale-sc08-offers-shop.md) | 0.050, 0.030 | 0.650, 0.030 | 0.850, 0.030 | 0.380, 0.045 |

sc01 and sc02 are measured with boxes; sc04, sc06, sc07 and sc08 are model estimates.
[sc09](clash-royale-sc09-king-tower-info.md) and
[sc11](clash-royale-sc11-battle-result.md) have no status bar at all — they are panels drawn
over whatever was underneath.

The two social screens list *only* the ad icon and no currency counters, which is either a
real difference in the screen or the model not bothering; the report gives no basis to
choose.

### The values it shows

Consistent across every screen that shows them:[^recon]

- **Level 18** — sc01 "showing level 18 with progress bar", sc07 "Card level 18",
  sc08 "shows level or trophy count '18'"
- **113 gold / coins** — sc01, sc07, sc08 all agree; sc08 renders it "113+"
- **100 gems** — sc01, sc07, sc08 all agree; sc08 renders it "100+"
- **0 trophies** for the player row on both social screens

These four numbers are the only cross-screen consistency check the model contains, and they
hold. Anything that changes them is a state change a test could assert on.

### Every currency counter is a purchase entrance

The report refuses each of them, and states the reasoning once for gold and once for
gems:[^recon]

- gems — "the entrance to the gem shop, which is a real-money purchase flow"
- gold — "gold is bought with gems and gems with money, so this is the same purchase flow
  one step back"

Refused on sc01, sc02, sc07 and sc08. There are also **two extra refusals at coordinates no
element list mentions** — (0.500, 0.030) and (0.800, 0.030), refused as gold and gems on
sc01, sc02 and sc11 — which are the denylist's own grid points rather than measured
controls. On sc11, which has no status bar, both are refusals against nothing.

### The ad icon is a control nobody pressed

All five screens that show it describe it as a small icon carrying an **X**: "small X icon
near an ad/banner icon, likely closes a promo overlay" (sc01), "small icon banner with close
X" (sc02), "Possibly an ad or notification popup with close button" (sc04), "ad close
button (X)" (sc06), "circular logo with X and arrow" (sc07), "small colorful icon with an X"
(sc08).

It is refused only on sc02, where the word `offer` appeared in its description. On sc01,
sc04, sc06, sc07 and sc08 it is "no verdict for this action". So the one persistent control
the model describes as *closing* something was never activated on any screen — which is
worth knowing given two screens in this model could not be closed. See
[Panels that swallow input](../concepts/clash-royale-panels-that-swallow-input.md).

## Related

- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md) — the other cross-screen component
- [Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md)
- [Surfaces that are named but unmodelled](../concepts/clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
