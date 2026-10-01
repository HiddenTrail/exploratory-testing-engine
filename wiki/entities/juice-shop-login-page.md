---
type: Entity
entity_kind: screen
title: "Juice Shop login page"
description: The login form, reached from the account menu, with email, password, Google login and links to register and reset a password.
tags: [juice-shop, screen]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-10-01T04:59:40Z" }
product: juice-shop
features: [login, form, input-field, email, password-reset, registration]
facts:
  - id: F1
    kind: shown
    text: The login form has Email and Password fields, both marked required.
    source: screens
  - id: F2
    kind: shown
    text: "\"Log in\" is greyed out while the fields are empty."
    source: screens
  - id: F3
    kind: shown
    text: The form offers "Remember me", "Log in with Google", "Forgot your password?" and "Not yet a customer?".
    source: spoor-map-2
sources:
  - id: spoor-map-2
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-30.json
    title: Spoor exploration of Juice Shop, 2026-09-30
  - id: screens
    resource: docs/product-sources/juice-shop-screens-2026-09-30/S21.png
    title: Spoor screenshot of the login page (S21)
---

# Juice Shop login page

- **Kind:** screen (S21 in the [second Spoor map](../summaries/juice-shop-spoor-map-2026-09-30.md))
- **Summary:** reached from the [product list](juice-shop-product-list.md) through
  the account menu's "Go to login page"

## Details

A "Login" card with:[^spoor-map-2] [^screens]

- **Email** and **Password** fields, both marked required, with a button to show
  the password
- **"Log in"**, shown greyed out while the fields are empty[^screens]
- a **"Remember me"** checkbox (its accessibility label is "Checkbox to stay
  logged in or not logged in")
- **"Log in with Google"**
- links: **"Forgot your password?"** and **"Not yet a customer?"**

The toolbar stays: the side menu, back to homepage, account and language
buttons.[^spoor-map-2]

Nothing here has been used yet. Spoor didn't type into the form.

## Related

- [Product list](juice-shop-product-list.md): the account menu that leads here

[^spoor-map-2]: Spoor exploration of Juice Shop, 2026-09-30 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-30.json`)
[^screens]: Spoor screenshot of the login page (`docs/product-sources/juice-shop-screens-2026-09-30/S21.png`)
