---
type: Source Summary
title: "Spoor map of Juice Shop, 2026-09-30"
description: Spoor's second exploration of Juice Shop, from the plain product list, which reached all 12 products and the login page.
tags: [juice-shop, spoor, ui-map]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T10:40:00Z" }
sources:
  - id: spoor-map-2
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-30.json
    title: Spoor exploration of Juice Shop, 2026-09-30
  - id: screens
    resource: docs/product-sources/juice-shop-screens-2026-09-30/
    title: Spoor screenshots of Juice Shop, 2026-09-30 (S7, S9, S21)
---

# Spoor map of Juice Shop, 2026-09-30

The [first map](juice-shop-spoor-map-2026-09-29.md) got stuck on the product list
with the tutorial running. This run continued the same map from the plain list
(S2: welcome banner closed, no tutorial), up to 2 clicks further, at 10:21 UTC.
The map now has 22 screens, 35 transitions and 44 skipped actions. S0 to S6 are
the first run's screens, and S7 to S21 are new.[^spoor-map-2]

## New screens

| Id | What it is |
|---|---|
| S7 | Product list with the account menu open ("Go to login page") |
| S8 | Product list with the language menu open (41 language entries) |
| S9 to S20 | The product details dialog, one per product on the first page |
| S21 | The login page |

## Transitions from the plain list (S2)

- **Each of the 12 products** opens its own details dialog (S9 to S20).[^spoor-map-2]
- **"Show/hide account menu"** opens the account menu (S7), and its "Go to login
  page" leads to the login page (S21).[^spoor-map-2]
- **"Language selection menu"** opens the language list (S8).[^spoor-map-2]
- **"Open Sidenav" and "Back to homepage"** left the screen's controls
  unchanged, so Spoor recorded them as staying on S2.[^spoor-map-2] Whatever the
  side menu shows, Spoor couldn't reach it as controls.

## What the screenshots add

- **Prices** are shown in a currency marked "¤": Apple Juice (1000ml) 1.99,
  Apple Pomace 0.89, Banana Juice (1000ml) 1.99, Carrot Juice (1000ml) 2.99, and
  Best Juice Shop Salesman Artwork 5000.[^screens]
- **Stock:** the artwork carries an "Only 1 left" badge.[^screens]
- **The list's heading** is "All Products".[^screens]
- **The cookie notice** reads "This website uses fruit cookies to ensure you get
  the juiciest tracking experience", with "But me wait!" and "Me want it!".[^screens]
  Spoor names these two controls "learn more about cookies" and "dismiss cookie
  message", from their accessibility labels.

## Skipped actions

Of the 44 skips, 40 say "blocked by an unresolved layer": something drawn on top
stopped the click. They come from the open account menu (S7, 20), the open
language menu (S8, 13), the tutorial (S1, 6) and the search box on the plain list
(S2, 1). In 5 of them the layer named is the cookie notice's dialog.[^spoor-map-2]
So an open menu covers the rest of the page, as you'd expect.

The other 4 couldn't be found again after 3 replays: the OWASP link on the start
page, and on the plain list "Previous page", "Next page" and "Items per
page".[^spoor-map-2]

## Open questions

- Paging, "Items per page" and search are still unexplored.
- The side menu opens (the screenshots show a menu button at the top left) but
  gave Spoor no new controls. It might be drawn in a way the accessibility tree
  doesn't expose.
- Logging in, registering ("Not yet a customer?") and the password reset weren't
  tried. They need typed input, which Spoor's `apply-scaffold` would provide.

[^spoor-map-2]: Spoor exploration of Juice Shop, 2026-09-30 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-30.json`)
[^screens]: Spoor screenshots of Juice Shop, 2026-09-30 (`docs/product-sources/juice-shop-screens-2026-09-30/`)
