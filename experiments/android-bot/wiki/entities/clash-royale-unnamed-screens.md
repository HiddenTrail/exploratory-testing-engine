---
type: Entity
entity_kind: screen-group
title: "sc03, sc05, sc10 — the three unnamed screens"
description: Three distinct screens that were each reached once, given no name or element list, and never probed — one page because there is nothing to say about any of them separately.
tags: [clash-royale, screen, sc03, sc05, sc10, gap]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — sections sc03, sc05, sc10"
  - id: shots
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/images"
    title: "Screenshots captured during the run — sc03-v1.png, sc05-v1.png, sc10-v1.png"
---

# sc03, sc05, sc10 — the three unnamed screens

- **Kind:** screen-group — three separate screens, one page
- **Summary:** each is a distinct screen identity by the pixel test, each was reached
  exactly once, each is headed "(unnamed - no model pass)", and none has an element list or
  a single action tried against it.[^recon]

They get one page rather than three because there is nothing to distinguish them *by* — no
name, no description, no elements, no transitions out. Three near-empty pages would imply
three separately understood things.

## Details

| Screen | First seen | Cells held still | Reached by | Screenshot |
|---|---|---|---|---|
| sc03 | action 4 | 576 of 576 | `drag:0.500,0.500>0.250,0.500` from [sc01](clash-royale-sc01-main-screen.md), 555 cells changed | [sc03-v1](../../out/Clash%20Royale-20260903-153913/images/sc03-v1.png) |
| sc05 | action 5 | 576 of 576 | `drag:0.500,0.500>0.750,0.500` from [sc04](clash-royale-sc04-social.md), **60 cells changed** | [sc05-v1](../../out/Clash%20Royale-20260903-153913/images/sc05-v1.png) |
| sc10 | action 5 | 576 of 576 | `drag:0.500,0.500>0.750,0.500` from [sc09](clash-royale-sc09-king-tower-info.md), **188 cells changed** | [sc10-v1](../../out/Clash%20Royale-20260903-153913/images/sc10-v1.png) |

The screenshot is the whole of what is known about each of these, so they are reproduced
here rather than only linked — left to right, sc03, sc05, sc10:[^shots]

![sc03](../../out/Clash%20Royale-20260903-153913/images/sc03-v1.png)
![sc05](../../out/Clash%20Royale-20260903-153913/images/sc05-v1.png)
![sc10](../../out/Clash%20Royale-20260903-153913/images/sc10-v1.png)

All three: one sighting, one stored appearance, an all-`.` still-map, and no
self-animation line.[^recon] The all-still map is not a finding about the screens — a
single sighting has no second frame to disagree with, so every cell trivially "held
still".

### What the changed-cell counts suggest

**Read this section with its own caveat.** For two of these three screens the count below is
contradicted by the saved frames: the arrivals at sc05 (60 cells) and sc10 (188 cells) both
have byte-identical before/after screenshots, and `sc10-v1.png` is byte-identical to
`sc09-v1.png`. See
[the saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md).
Only sc03's 555 is corroborated at the pixel level. What follows was the reading before that
check; the two small-count readings should now be treated as ungrounded.

The three arrivals are very different sizes, and that is the only structural information
available about them:

- **sc03, 555 of 576 cells.** A whole-screen replacement. Whatever a leftward centre drag
  does from the home screen, it does not leave the home screen's furniture behind.
- **sc05, 60 cells.** About a tenth of the frame. This reads as something opening *over*
  sc04 rather than replacing it — a panel, a dropdown, a toast — which the pixel test
  correctly registers as a new identity but which is not a navigation.
- **sc10, 188 cells.** A third of the frame, arriving from a modal panel. Consistent with
  the King Tower panel closing or being partly replaced, i.e. sc10 may be what was *behind*
  sc09.

None of that is tested. It is arithmetic on the changed-cell column plus the identity of the
screen departed from — and for sc05 and sc10 the changed-cell column is the part that does
not survive being checked against the images.

### Why they stayed unnamed

The report gives no reason per screen; the heading is simply "(unnamed - no model pass)".
What it does record is that the run stopped with "nothing left to try" and that no route
was found back to any screen with untried actions, including all three of these.[^recon] A
screen reached at the end of a chain, once, with the frontier already unreachable, never
gets a second visit to describe.

## Related

- [sc01](clash-royale-sc01-main-screen.md), [sc04](clash-royale-sc04-social.md),
  [sc09](clash-royale-sc09-king-tower-info.md) — the three screens these were reached from
- [The observed navigation map](../concepts/clash-royale-navigation-map.md) — the three dead ends in it
- [The saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md) — why two of the three counts above are unusable
- [Screen identity is a pixel measurement, not a name](../concepts/clash-royale-screen-identity-by-pixels.md)
- [Surfaces that are named but unmodelled](../concepts/clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc03", "sc05", "sc10" and "What went wrong"
[^shots]: Screenshots from the same run, `experiments/android-bot/out/Clash Royale-20260903-153913/images/`
