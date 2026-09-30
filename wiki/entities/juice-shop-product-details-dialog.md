---
type: Entity
entity_kind: screen
title: "Juice Shop product details dialog"
description: The dialog a product opens, with its picture, description, price, a reviews section and a close button.
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
    resource: docs/product-sources/juice-shop-screens-2026-09-30/S9.png
    title: Spoor screenshot of the Apple Juice (1000ml) dialog (S9)
---

# Juice Shop product details dialog

- **Kind:** screen (S5 and S6 in the [first Spoor map](../summaries/juice-shop-spoor-map-2026-09-29.md),
  S9 to S20 in the [second](../summaries/juice-shop-spoor-map-2026-09-30.md))
- **Summary:** opened by pressing a product on the [product list](juice-shop-product-list.md)

## Details

The dialog shows the product's picture, name, a one-line description and the
price. For Apple Juice (1000ml): "The all-time classic.", 1.99¤. Below that is a
folded "Reviews (n)" section and a "Close" button, and the list stays dimmed
behind it.[^screens]

Spoor opened all 12 products on the first page.[^spoor-map-2] Every dialog has
"Close Dialog", an unnamed button and "Reviews (n)". The count differs per
product: 0 for Apple Pomace, Fruit Press, Lemon Juice and Melon Bike, 2 for the
Salesman Artwork, 3 for the DSOMM & Juice Shop User Day Ticket, and 1 for the
rest.[^spoor-map-2]

Some descriptions have links:[^spoor-map] [^spoor-map-2]

- **Apple Pomace:** "sent back to us"
- **DSOMM & Juice Shop User Day Ticket:** "Get a ticket*" and "here"
- **Juice Shop "Permafrost" 2020 Edition:** "OWASP Juice Shop that was archived on
  02/02/2020" and "Arctic Code Vault"

Opening a dialog requests `/rest/products/<id>/reviews` and `/rest/user/whoami`.
The ids seen are 1 (Apple Juice), 24 (Apple Pomace), 6, 42, 30, 46, 3, 25, 22, 41,
5 and 33, in the list's order.[^spoor-map-2] So product ids don't follow the list's
alphabetical order.

## Not explored yet

Opening the reviews, and the description links.

## Related

- [Product list](juice-shop-product-list.md): where the dialog opens from

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
[^spoor-map-2]: Spoor exploration of Juice Shop, 2026-09-30 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-30.json`)
[^screens]: Spoor screenshot of the Apple Juice (1000ml) dialog (`docs/product-sources/juice-shop-screens-2026-09-30/S9.png`)
