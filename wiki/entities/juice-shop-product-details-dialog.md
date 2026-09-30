---
type: Entity
entity_kind: screen
title: "Juice Shop product details dialog"
description: The dialog a product opens, with a reviews section and a close button.
tags: [juice-shop, screen]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T09:50:00Z" }
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
---

# Juice Shop product details dialog

- **Kind:** screen (S5 and S6 in the [Spoor map](../summaries/juice-shop-spoor-map-2026-09-29.md))
- **Summary:** opened by pressing a product on the [product list](juice-shop-product-list.md)

## Details

Spoor opened two products:[^spoor-map]

- **Apple Juice (1000ml) (S5):** "Close Dialog", an unnamed button, and
  "Reviews (1)".
- **Apple Pomace (S6):** the same, but with "Reviews (0)" and a link named "sent
  back to us".

The review count is part of the button's name, so it differs per product.
Opening a dialog requested `/rest/products/<id>/reviews` (ids 1 and 24) and
`/rest/user/whoami`.[^spoor-map]

## Related

- [Product list](juice-shop-product-list.md): where the dialog opens from

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
