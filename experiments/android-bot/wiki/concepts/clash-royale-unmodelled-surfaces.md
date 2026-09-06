---
type: Quality Concept
title: "Surfaces that are named but unmodelled"
description: 120 identified controls were never activated, and 66 of them - the majority - were skipped for want of a decision rather than for want of permission.
tags: [clash-royale, coverage, gap, method]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — 'What was not tried, and why'"
guidelines_refs: []
---

# Surfaces that are named but unmodelled

## What it is

The report's "What was not tried, and why" section lists **120 controls that were located and
never activated**.[^recon] Against 43 measured screen/action pairs, most of the identified
interface has a coordinate and no observed behaviour.

The split inside those 120 is the point of this page: **54 were declined for a stated reason,
and 66 were not declined at all.**

## Current state / findings

### The census

| Reason | Count |
|---|---|
| **"no verdict for this action"** — no decision was reached | **66** |
| Battle button — starts a live match | 13 |
| Clan tab — chat and card donations | 9 |
| Gold / coin counter and its + button | 8 |
| Gem counter and its + button | 8 |
| Pass Royale banner — paid subscription | 6 |
| Shop tab — the whole tab is offers | 5 |
| Verdicts argued individually | 5 |
| **Total** | **120** |

By screen, and how much of each screen's gap is a missing decision rather than a policy:

| Screen | Not tried | of which "no verdict" |
|---|---|---|
| [sc01](../entities/clash-royale-sc01-main-screen.md) | 26 | 13 |
| [sc02](../entities/clash-royale-sc02-battle-deck.md) | 20 | 10 |
| [sc06](../entities/clash-royale-sc06-social.md) | 20 | 15 |
| [sc08](../entities/clash-royale-sc08-offers-shop.md) | 19 | 11 |
| [sc04](../entities/clash-royale-sc04-social.md) | 15 | 11 |
| [sc07](../entities/clash-royale-sc07-collection.md) | 9 | 6 |
| [sc11](../entities/clash-royale-sc11-battle-result.md) | 9 | **0** |
| [sc09](../entities/clash-royale-sc09-king-tower-info.md) | 2 | **0** |
| sc03, sc05, sc10 | 0 | – |

112 of the 120 are taps and only 8 are drags. The three unnamed screens contribute nothing:
with no element pass, they had no candidates to decline. And the two panels are the only
screens where every single entry was reasoned — the discipline was best exactly where the run
was stuck.

### The 66 are the finding

A refusal is a decision with a reason attached; each of the 54 can be read, argued with or
narrowed. **"No verdict for this action" is not a decision.** It means the vetting step
produced nothing and the control was set aside, so that part of the interface is unmodelled
for a reason that has nothing to do with the interface.

Two "What went wrong" bullets account for some of them:[^recon]

> could not get a verdict for click:0.200,0.970, click:0.500,0.970, click:0.030,0.200,
> click:0.030,0.800 ('name')

> could not get a verdict for click:0.970,0.800 ('str' object has no attribute 'get')

Both are exceptions, not judgements. Each is followed by a bullet saying the failure left the
candidates "unplanned again rather than retired unsent" — for 7 candidates once and 2 the
second time. So a lower bound of the 66 is a handful lost to two crashes, re-queued rather
than closed out. The report does not account for the remainder.

### What is missing, in order of what pressing it would buy

**1. The bottom navigation bar, entirely.** The Cards, Battle-arena and Rank icons carry no
policy objection on any of the five screens that show them, and none was ever pressed;
neither was any of the four arrows inside the bar. This is the product's primary navigation and
it is completely unobserved. See
[the bottom navigation bar](../entities/clash-royale-bottom-navigation-bar.md).

**2. The ad/offer X in the top bar.** Described as a close control on six screens, refused on
one, pressed on none — the only persistent control whose described effect is dismissal. See
[the top status bar](../entities/clash-royale-top-bar.md).

**3. sc11's X at (0.083, 0.900).** A measured, trimmed red X whose verdict reached "likely
safe" and declined anyway. It is the only named exit from the screen the run got stuck on, and
pressing it separates four rival explanations. See
[Panels that swallow input](clash-royale-panels-that-swallow-input.md).

**4. sc07's navigation bar.** Five icons whose coordinates came back at y = 1.33 — below the
window — so they were dropped rather than declined and appear in *neither* list. The screen has
no modelled navigation at all.

**5. Quickplay, on both social screens.** (0.190, 0.830) on sc04 and (0.202, 0.826) on sc06,
described as likely starting a quick match — the same hazard as the Battle button, which is
denylisted 13 times. **Quickplay is denylisted zero times**; both entries are "no verdict".
This is the one item here that should be closed by adding a rule rather than by testing.

**6. sc03, sc05 and sc10.** Fingerprints and screenshots, no description and no probes. See
[the unnamed screens](../entities/clash-royale-unnamed-screens.md).

## Implications for Guidelines / Playbook

- **Count "no verdict" separately from "refused", and treat it as a run defect.** 66 of 120 is
  not a safety posture; it is a step that failed quietly 66 times. A run that cannot reach a
  verdict should surface that as a blocker rather than filling the gap with silence.
- **A failed vetting call must retire its candidates, not return them to the pool.** The report
  names this itself, twice on one screen — which is how a loop spends its budget re-deciding
  the same controls.
- **Quickplay needs a denylist entry before the next run.** It matches the Battle button's
  hazard and none of the words the money filter looks for.
- **Named controls should be probed before blind coordinates.** Four of the ten known
  transitions came from margin probes and centre drags rather than from elements, so the map
  was built out of the parts of the screen nobody identified while 120 identified controls sat
  untouched. See [the observed navigation map](clash-royale-navigation-map.md).
- **This coverage is cheap.** Three unnamed screens need one visit each, the nav bar needs five
  taps, the X needs one. That is less budget than this run already spent, and it addresses the
  three largest holes in the model.

## Related

- [The observed navigation map](clash-royale-navigation-map.md)
- [Monetisation surfaces](clash-royale-monetisation-surfaces.md) — the 28 money refusals in detail
- [Panels that swallow input](clash-royale-panels-that-swallow-input.md)
- [Screen identity is a pixel measurement, not a name](clash-royale-screen-identity-by-pixels.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
