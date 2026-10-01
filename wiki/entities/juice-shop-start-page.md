---
type: Entity
entity_kind: screen
title: "Juice Shop start page"
description: The first screen a new visitor sees, a welcome banner and a cookie notice over the shop.
tags: [juice-shop, screen]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-10-01T04:59:08Z" }
product: juice-shop
features: [dialog, notification, link]
facts:
  - id: F1
    kind: shown
    text: A first visit shows a welcome banner and a cookie notice over the shop.
    source: spoor-map
  - id: F2
    kind: shown
    text: "\"Close Welcome Banner\" leads to the product list."
    source: spoor-map
  - id: F3
    kind: shown
    text: "\"Help getting started\" leads to the product list with the tutorial started."
    source: spoor-map
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
---

# Juice Shop start page

- **Kind:** screen (S0 in the [Spoor map](../summaries/juice-shop-spoor-map-2026-09-29.md))
- **Summary:** what a first-time visitor lands on at `http://127.0.0.1:3000/`

## Details

A welcome banner and a cookie notice cover the shop. The only controls Spoor
could reach are these:[^spoor-map]

- the cookie notice: "learn more about cookies" and "dismiss cookie message"
- the banner: "Help getting started", "Close Welcome Banner", and links to
  `https://owasp-juice.shop` and the OWASP project

"Close Welcome Banner" leads to the [product list](juice-shop-product-list.md).
"Help getting started" leads to the same list with the tutorial
started.[^spoor-map]

## Related

- [Product list](juice-shop-product-list.md): where both banner buttons lead

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
