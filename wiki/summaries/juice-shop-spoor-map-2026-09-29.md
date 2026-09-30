---
type: Source Summary
title: "Spoor map of Juice Shop, 2026-09-29"
description: What Spoor's first exploration of Juice Shop found, 7 screens, 12 transitions and 7 skipped actions.
tags: [juice-shop, spoor, ui-map]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: "2026-09-30T09:50:00Z" }
sources:
  - id: spoor-map
    resource: docs/product-sources/juice-shop-spoor-map-2026-09-29.json
    title: Spoor exploration of Juice Shop, 2026-09-29
---

# Spoor map of Juice Shop, 2026-09-29

Spoor explored the local Juice Shop (`http://127.0.0.1:3000`) on 2026-09-29 at
06:50 UTC, in sandbox mode. It recorded 7 screens (S0 to S6), 12 transitions and
7 actions it skipped.[^spoor-map] Spoor tells screens apart by the controls it can
reach through the accessibility tree, so a "screen" here is a distinct set of
controls, not a distinct URL.

## Screens

| Id | What it is | Controls |
|---|---|---|
| S0 | Start page, welcome banner open | 6 |
| S1 | Product list with the tutorial started | 23 |
| S2 | Product list, banner closed | 22 |
| S3 | S1 with the account menu open | 24 |
| S4 | S1 with the language menu open | 64 |
| S5 | Product details: Apple Juice (1000ml) | 5 |
| S6 | Product details: Apple Pomace | 6 |

## Transitions

- **From S0:** "Help getting started" goes to S1, and "Close Welcome Banner" goes
  to S2. The cookie buttons and the `https://owasp-juice.shop` link stayed on
  S0.[^spoor-map]
- **From S1:** "Show/hide account menu" goes to S3, "Language selection menu" to
  S4, "Apple Juice (1000ml)" to S5 and "Apple Pomace" to S6. A button named "×"
  goes to S2. The cookie buttons stayed on S1.[^spoor-map]

## Skipped actions

- On S0, the "Open Worldwide Application Security Project (OWASP)" link couldn't
  be found again after 3 replays.[^spoor-map]
- On S1, six controls were "blocked by an unresolved layer": Open Sidenav, Back
  to homepage, Previous page, Next page, the search textbox and "Items per
  page".[^spoor-map] Something drawn over the page stopped Spoor from using them.
  The source doesn't say what; the tutorial is a likely guess.

## Console and API

- Every screen from S1 on logs `Starting instructions for challenge "Score Board"`.[^spoor-map]
- The API paths requested during the session are listed in the
  [overview](../overview.md).

## Open questions

The [second run](juice-shop-spoor-map-2026-09-30.md) started from S2 and answered
some of these: it opened every product and reached the login page.

- The side menu, paging and search were never used, because of the layer on S1.
  Exploring from S2 (banner closed, no tutorial) might reach them.
- "Go to login page" (S3) and the review buttons (S5, S6) were found but not
  followed.
- The map has no screenshots, so these pages describe controls, not layout.

[^spoor-map]: Spoor exploration of Juice Shop, 2026-09-29 (trimmed export in `docs/product-sources/juice-shop-spoor-map-2026-09-29.json`)
