---
type: Entity
entity_kind: ui-component
title: "The bottom navigation bar"
description: The persistent tab bar at the foot of six screens — five to seven icons whose x positions differ on every screen, with scroll arrows interleaved, so no fixed coordinate addresses a given tab.
tags: [clash-royale, navigation, ui-component]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — element lists for sc01, sc02, sc04, sc06, sc07, sc08"
---

# The bottom navigation bar

- **Kind:** ui-component — a persistent tab bar
- **Summary:** the strip of icons at y ≈ 0.93–0.96 that appears on six of the eleven
  screens. It is the product's primary navigation, and **it is the single least reliable
  thing to address by coordinate in this whole model.**

## Details

### The same icon, six different x positions

Collected from the element lists of the six screens that have one:[^recon]

| Screen | Chest / Shop | Cards | Battle | Clan / Social | Rank | Arrows in the bar |
|---|---|---|---|---|---|---|
| [sc01](clash-royale-sc01-main-screen.md) | 0.080 | 0.243 | 0.502 | 0.750 | 0.910 | – |
| [sc02](clash-royale-sc02-battle-deck.md) | 0.080 | 0.290 | 0.570 | 0.740 | 0.910 | ← 0.190, → 0.470 |
| [sc04](clash-royale-sc04-social.md) | 0.100 | 0.280 | 0.440 | 0.660 | 0.900 | – |
| [sc06](clash-royale-sc06-social.md) | 0.088 | 0.264 | 0.441 | 0.664 | 0.917 | ← 0.529, → 0.794 |
| [sc07](clash-royale-sc07-collection.md) | *unplaced* | *unplaced* | *unplaced* | *unplaced* | *unplaced* | – |
| [sc08](clash-royale-sc08-offers-shop.md) | 0.160 | 0.410 | 0.580 | 0.750 | 0.910 | → 0.310 |

All y values are 0.930 (sc02), 0.940 (sc04, sc06, sc08) or 0.942–0.957 (sc01). Only sc01
and sc02 have **measured boxes** for these icons; sc04, sc06 and sc08 are model estimates,
and sc07's five are outside the window entirely.

The Battle icon moves from 0.440 to 0.580 across screens — 157 px at this window width.
The Shop/chest icon moves from 0.080 to 0.160. **A tap written for one screen's nav bar can
land on a different tab on another screen**, and two refusals in the report show exactly
that happening: (0.710, 0.150) on sc02 refused as "the Pass Royale banner" is the
Collection tab, and (0.794, 0.940) on sc06 refused as "the Clan tab" is the right arrow.

### The arrows

Three screens carry arrows *inside* the bar, and the model reads them two different ways:

- sc02: "**Left arrow** — navigation arrow, possibly switch deck slot left" at 0.190, and a
  right arrow at 0.470 — interleaved between the icons, not at the ends.
- sc06: "**left arrow (bottom nav)** — scroll nav tabs left" at 0.529 and "right arrow —
  scroll nav tabs right" at 0.794.
- sc08: "bottom nav: right arrow — arrow to scroll bottom nav or go to next section" at
  0.310.

The sc06 and sc08 readings say the bar scrolls. The sc02 reading says the arrows page
through deck slots. **Neither was ever pressed** — every arrow is either "no verdict" or, at
(0.794, 0.940), refused by a denylist entry written for something else. If the bar does
scroll, the position table above is not describing five layouts but five *scroll offsets*,
and no coordinate addresses a tab durably.

That is the cheapest high-value experiment this model suggests: press one arrow, capture,
and see whether the icon x values shift.

### What the bar is refused for

Two of its icons carry standing refusals wherever they appear:[^recon]

- **Shop / chest icon** — "the Shop tab in the bottom navigation - the whole tab is offers,
  including real-money ones". Refused on sc01, sc02, sc04, sc06, sc08.
- **Clan / social icon** — "clan chat and card donations, which are messages and gifts to
  other people and cannot be taken back". Refused on sc01, sc02, sc04, sc06, sc08.

The Cards, Battle and Rank icons carry no policy refusal and are still unmodelled: every one
of them is "no verdict for this action". **Three quarters of this component's function is
untested for want of a decision, not for want of permission.**

Note that refusing the Shop tab did not keep the run out of the shop — sc08 was reached by a
rightward centre drag from sc07. See [sc08](clash-royale-sc08-offers-shop.md).

## Related

- [The top status bar](clash-royale-top-bar.md) — the other cross-screen component
- [The observed navigation map](../concepts/clash-royale-navigation-map.md) — what the drags did instead
- [Surfaces that are named but unmodelled](../concepts/clash-royale-unmodelled-surfaces.md)
- [Monetisation surfaces](../concepts/clash-royale-monetisation-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
