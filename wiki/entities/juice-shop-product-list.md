---
type: Entity
entity_kind: screen
title: "Juice Shop product list"
description: The shop's main page, a paged grid of products with a toolbar for the menu, account and language.
tags: [juice-shop, screen]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T09:50:00Z" }
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
---

# Juice Shop product list

- **Kind:** screen (S1 to S4 in the [Spoor map](../summaries/juice-shop-spoor-map-2026-09-29.md))
- **Summary:** the shop's main page once the welcome banner is gone

## Details

**Toolbar:** Open Sidenav, Back to homepage, Show/hide account menu, Language
selection menu, and a search textbox.[^spoor-map]

**Products:** one button per product. Spoor saw 12 on the first page: Apple
Juice (1000ml), Apple Pomace, Banana Juice (1000ml), Best Juice Shop Salesman
Artwork, Carrot Juice (1000ml), DSOMM & Juice Shop User Day Ticket, Eggfruit
Juice (500ml), Fruit Press, Green Smoothie, Juice Shop "Permafrost" 2020 Edition,
Lemon Juice (500ml) and Melon Bike (Comeback-Product 2018 Edition). Paging has
Previous page, Next page and an "Items per page" setting.[^spoor-map]

**Variants Spoor recorded:**[^spoor-map]

- **S2:** the plain list, reached by closing the welcome banner.
- **S1:** the list with the tutorial started. It has one extra button, "×", which
  leads to S2. Here six toolbar and paging controls were blocked by a layer
  over the page.
- **S3:** S1 with the account menu open. It adds one item, "Go to login page".
- **S4:** S1 with the language menu open: 40 language entries, from
  Azərbaycanca to 繁體中文 (which is listed twice).

Pressing a product opens the [product details dialog](juice-shop-product-details-dialog.md).

## Related

- [Start page](juice-shop-start-page.md): how you get here
- [Product details dialog](juice-shop-product-details-dialog.md): what a product opens

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
