---
type: Product Overview
resource: http://127.0.0.1:3000
title: "OWASP Juice Shop: product overview"
description: OWASP Juice Shop at a glance, a web shop for juice and merchandise run locally as a test target.
tags: [juice-shop]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-10-01T04:59:08Z" }
product: juice-shop
surfaces: [gui]
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
  - id: spoor-map-2
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-30.json
    title: Spoor exploration of Juice Shop, 2026-09-30
  - id: screens
    resource: docs/product-sources/juice-shop-screens-2026-09-30/
    title: Spoor screenshots of Juice Shop, 2026-09-30
---

# OWASP Juice Shop: product overview

This wiki covers one product so far: **OWASP Juice Shop**, running locally from
`test-targets/` on port 3000.

## What it is

A web shop that sells juices and Juice Shop merchandise. Its main page lists
products such as Apple Juice (1000ml) at 1.99¤, Fruit Press and a "Permafrost"
2020 Edition, with paging and an "Items per page" setting.[^spoor-map] [^screens]

It is also a training app. A first-time visitor gets a welcome banner with a
"Help getting started" button. Pressing it logs `Starting instructions for
challenge "Score Board"` to the console, so the app has challenges and a guided
tutorial.[^spoor-map]

## What a visitor can do on the mapped pages

- **Start page:** dismiss the cookie notice, close the welcome banner, or start
  the tutorial. See [Start page](entities/juice-shop-start-page.md).
- **Product list:** open the side menu, the account menu (which offers "Go to
  login page") and a language menu with about 40 entries, page through products,
  and open a product. See [Product list](entities/juice-shop-product-list.md).
- **Product details:** a dialog per product with its description, price and
  reviews. See [Product details dialog](entities/juice-shop-product-details-dialog.md).
- **Login:** email and password, Google login, "Remember me", and links to
  register and reset a password. See [Login page](entities/juice-shop-login-page.md).

## The API behind it

While the pages loaded, the browser requested REST paths including
`/rest/products/search`, `/rest/languages`, `/rest/admin/application-configuration`,
`/rest/admin/application-version`, `/api/Challenges/` and `/api/Quantitys/`.
Opening a product also requested `/rest/products/<id>/reviews` and
`/rest/user/whoami`.[^spoor-map] [^spoor-map-2]

## Not mapped yet

Anything behind logging in (the basket, checkout, the account), registering,
search results, paging, and whatever the side menu leads to. The maps reach the
product list, the product dialogs and the login form, but never type into a
form. The source summaries for
[2026-09-29](summaries/juice-shop-spoor-map-2026-09-29.md) and
[2026-09-30](summaries/juice-shop-spoor-map-2026-09-30.md) say what was left out
and why.

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
[^spoor-map-2]: Spoor exploration of Juice Shop, 2026-09-30 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-30.json`)
[^screens]: Spoor screenshots of Juice Shop, 2026-09-30 (`docs/product-sources/juice-shop-screens-2026-09-30/`)
