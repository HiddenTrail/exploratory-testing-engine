---
type: Product Overview
resource: http://127.0.0.1:3000
title: "OWASP Juice Shop: product overview"
description: OWASP Juice Shop at a glance, a web shop for juice and merchandise run locally as a test target.
tags: [juice-shop]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T09:50:00Z" }
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
---

# OWASP Juice Shop: product overview

This wiki covers one product so far: **OWASP Juice Shop**, running locally from
`test-targets/` on port 3000.

## What it is

A web shop that sells juices and Juice Shop merchandise. The one mapped page
lists products such as Apple Juice (1000ml), Fruit Press and a "Permafrost" 2020
Edition, with paging and an "Items per page" setting.[^spoor-map]

It is also a training app. A first-time visitor gets a welcome banner with a
"Help getting started" button. Pressing it logs `Starting instructions for
challenge "Score Board"` to the console, so the app has challenges and a guided
tutorial.[^spoor-map]

## What a visitor can do on the mapped pages

- **Start page:** dismiss the cookie notice, close the welcome banner, or start
  the tutorial. See [Start page](entities/juice-shop-start-page.md).
- **Product list:** open the side menu, the account menu (which offers "Go to
  login page") and a language menu with 40 entries, page through products,
  and open a product. See [Product list](entities/juice-shop-product-list.md).
- **Product details:** a dialog per product with its reviews. See
  [Product details dialog](entities/juice-shop-product-details-dialog.md).

## The API behind it

While the pages loaded, the browser requested REST paths including
`/rest/products/search`, `/rest/languages`, `/rest/admin/application-configuration`,
`/rest/admin/application-version`, `/api/Challenges/` and `/api/Quantitys/`.
Opening a product also requested `/rest/products/<id>/reviews` and
`/rest/user/whoami`.[^spoor-map]

## Not mapped yet

Login, the basket, checkout, search results and the side menu's pages. The map
stops at the product list and its dialogs. The
[source summary](summaries/juice-shop-spoor-map-2026-09-29.md) says what was left
out and why.

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
