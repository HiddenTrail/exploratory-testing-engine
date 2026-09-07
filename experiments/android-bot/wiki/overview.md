---
type: Product Overview
title: "Clash Royale (Windows client) — product overview"
description: The Clash Royale meta-game as observed through one window on Windows — eleven screens, a scrolling bottom navigation bar, and a monetisation surface on nearly every one of them.
tags: [clash-royale, mobile-game, ui]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 15:39"
---

# Clash Royale (Windows client) — product overview

Everything on this page comes from **one recon report** covering **eleven screens** of a
running Clash Royale client.[^recon] Nothing here is from Supercell documentation, a
wiki, or general knowledge about the game. Where the report only records what a model
*said* about a screenshot rather than what was measured from pixels, the pages below say
so — see [Screen identity is a pixel measurement, not a name](concepts/clash-royale-screen-identity-by-pixels.md).

## What it is

Clash Royale is a card-based competitive mobile game. This wiki models only its
**meta-game**: the screens a player moves through between matches — home, deck, card
collection, social, shop offers, tower detail, battle result. No match was ever entered,
so nothing on this page describes gameplay.

## What was being looked at

- One window, client area **1121 × 1993** px — a tall portrait phone aspect ratio on a
  desktop.[^recon]
- The window is **not a native app**. The bottom of the home screen carries a browser
  tab label naming a website and Chrome, which is the report's own reading: "indicating
  this is a browser tab, not a native app".[^recon] The bottom ~2 % of the window is
  therefore browser furniture, not game surface — which matters for anything aimed near
  y ≈ 0.98.
- The account in view is a low-level test account: level 18 badge, 113 gold, 100 gems,
  clan "Testing / No Clan", 0 trophies.[^recon]

## The screens

| Screen | Name (model-given) | Sightings | Geometry measured? |
|---|---|---|---|
| [sc01](entities/clash-royale-sc01-main-screen.md) | Clash Royale main/home screen | 16 | yes — 20 elements with boxes |
| [sc02](entities/clash-royale-sc02-battle-deck.md) | Clash Royale - Battle Deck screen | 10 | yes — 15 elements with boxes |
| [sc03](entities/clash-royale-unnamed-screens.md) | *(unnamed — no model pass)* | 1 | no |
| [sc04](entities/clash-royale-sc04-social.md) | Social screen (Clash Royale-like game) | 1 | no — points only |
| [sc05](entities/clash-royale-unnamed-screens.md) | *(unnamed — no model pass)* | 1 | no |
| [sc06](entities/clash-royale-sc06-social.md) | Social screen (Clash Royale-style game) | 1 | no — points only |
| [sc07](entities/clash-royale-sc07-collection.md) | Clash Royale - Collection/Card Deck screen | 2 | no — points only |
| [sc08](entities/clash-royale-sc08-offers-shop.md) | Offers / Shop screen | 3 | no — points only |
| [sc09](entities/clash-royale-sc09-king-tower-info.md) | King Tower info panel | 9 | yes — 11 elements with boxes |
| [sc10](entities/clash-royale-unnamed-screens.md) | *(unnamed — no model pass)* | 1 | no |
| [sc11](entities/clash-royale-sc11-battle-result.md) | battle result screen | 28 | yes — 6 elements with boxes |

Two structures recur across screens and have their own pages: the
[bottom navigation bar](entities/clash-royale-bottom-navigation-bar.md) and the
[top status bar](entities/clash-royale-top-bar.md).

## The five things worth knowing before testing this

1. **A battle result panel can hold the client.** Sixteen distinct inputs were sent to
   sc11, including its own OK button, and every one of them left the screen unchanged.
   See [Panels that swallow input](concepts/clash-royale-panels-that-swallow-input.md).
2. **The bottom navigation bar scrolls, so its icons are not at fixed coordinates.**
   Three screens show left/right arrows inside the bar and the same icon sits at a
   different x on different screens. See
   [The bottom navigation bar](entities/clash-royale-bottom-navigation-bar.md).
3. **Money is reachable from nearly every screen** — a "+" beside each currency, banner
   offers on the home screen, and a real-money price bar on the shop screen. See
   [Monetisation surfaces](concepts/clash-royale-monetisation-surfaces.md).
4. **The observed navigation graph is not connected.** Three screens have no measured
   way out at all and no route was found back to any screen with untried controls. See
   [The observed navigation map](concepts/clash-royale-navigation-map.md).
5. **Small changed-cell counts in the source cannot be trusted.** Seven actions report a
   change between two screenshots that are byte-identical, including both of the transitions
   the model reads as a panel opening. Counts over 200 cells are all corroborated. See
   [the saved frames do not always match the changed-cell counts](concepts/clash-royale-frames-vs-counts.md).

## What this overview does not cover

Most of the interface. 120 candidate controls were identified and never activated —
some deliberately (money, battle, clan), most for want of a decision. See
[Surfaces that are named but unmodelled](concepts/clash-royale-unmodelled-surfaces.md)
for what is missing and why.

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
