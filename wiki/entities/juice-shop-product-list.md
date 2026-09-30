---
type: Entity
entity_kind: screen
title: "Juice Shop product list"
description: The shop's main page, a paged grid of products with prices, under a toolbar for the menu, search, account and language.
tags: [juice-shop, screen]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T10:40:00Z" }
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
  - id: spoor-map-2
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-30.json
    title: Spoor exploration of Juice Shop, 2026-09-30
  - id: screens
    resource: docs/product-sources/juice-shop-screens-2026-09-30/S7.png
    title: Spoor screenshot of the product list with the account menu open (S7)
---

# Juice Shop product list

- **Kind:** screen (S1 to S4, S7 and S8 in the Spoor maps of
  [2026-09-29](../summaries/juice-shop-spoor-map-2026-09-29.md) and
  [2026-09-30](../summaries/juice-shop-spoor-map-2026-09-30.md))
- **Summary:** the shop's main page once the welcome banner is gone

## Details

**Toolbar:** Open Sidenav, Back to homepage, Show/hide account menu, Language
selection menu, and a search textbox.[^spoor-map] On screen it's a menu button,
the "OWASP Juice Shop" logo, a search icon, "Account" and a language button
showing "EN".[^screens]

**Products:** a grid under the heading "All Products", each with a picture, a
name and a price in "¤".[^screens] Spoor saw 12 on the first page: Apple Juice
(1000ml), Apple Pomace, Banana Juice (1000ml), Best Juice Shop Salesman Artwork,
Carrot Juice (1000ml), DSOMM & Juice Shop User Day Ticket, Eggfruit Juice
(500ml), Fruit Press, Green Smoothie, Juice Shop "Permafrost" 2020 Edition, Lemon
Juice (500ml) and Melon Bike (Comeback-Product 2018 Edition).[^spoor-map] Prices
seen include Apple Juice 1.99, Apple Pomace 0.89, Carrot Juice 2.99 and the
artwork 5000, which also carries an "Only 1 left" badge.[^screens] Paging has
Previous page, Next page and an "Items per page" setting.[^spoor-map]

**Variants Spoor recorded:**

- **S2:** the plain list, reached by closing the welcome banner. Every product
  here opens its [details dialog](juice-shop-product-details-dialog.md).
  "Open Sidenav" and "Back to homepage" didn't change the controls
  Spoor could see.[^spoor-map-2]
- **S1:** the list with the tutorial started. It has one extra button, "×", which
  leads to S2. Here six toolbar and paging controls were blocked by a layer
  over the page.[^spoor-map]
- **S3 and S7:** the account menu open, with one item, "Go to login page", which
  leads to the [login page](juice-shop-login-page.md). S3 is from the tutorial
  list, S7 from the plain one.[^spoor-map] [^spoor-map-2]
- **S4 and S8:** the language menu open, with about 40 language entries (40 and
  41 in the two runs), from Azərbaycanca to 繁體中文.[^spoor-map] [^spoor-map-2]

## Not explored yet

Paging, "Items per page" and search. On the plain list Spoor couldn't find the
paging controls again after 3 replays, and the search box was blocked by a
layer.[^spoor-map-2]

## Related

- [Start page](juice-shop-start-page.md): how you get here
- [Product details dialog](juice-shop-product-details-dialog.md): what a product opens
- [Login page](juice-shop-login-page.md): where the account menu leads

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
[^spoor-map-2]: Spoor exploration of Juice Shop, 2026-09-30 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-30.json`)
[^screens]: Spoor screenshot of the product list with the account menu open (`docs/product-sources/juice-shop-screens-2026-09-30/S7.png`)
