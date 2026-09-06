---
type: Quality Concept
title: "The saved frames do not always match the changed-cell counts"
description: Hashing every before/after screenshot pair shows 7 of 43 actions report a change between two byte-identical frames — including both of the small-count transitions the model reads as panels opening.
tags: [clash-royale, method, measurement, finding]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T14:10:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — per-screen action tables"
  - id: shots
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/images"
    title: "Screenshots captured during the run — before/pressed/after triplets and stored appearances"
guidelines_refs: []
---

# The saved frames do not always match the changed-cell counts

## What it is

Every action in the recon report carries a **changed-cell count** — how many of the 576 grid
cells differed after the input.[^recon] Every action also saved a `-before.png` and an
`-after.png`.[^shots] The two should agree, and in seven cases they cannot.

**This page is not from the report.** It comes from hashing all 43 before/after pairs (SHA-1
over the file bytes) and comparing the result against the count the report gives for the same
action. It is cheap to reproduce and it changes how several other pages should be read.

## Current state / findings

### The cross-check

| Reported change | Actions | Frames differ | Frames byte-identical |
|---|---|---|---|
| **≥ 200 cells** | 8 | **8** | 0 |
| 1–199 cells | 16 | 9 | **7** |
| 0 cells | 19 | 5 | 14 |

Two different things are going on in that table, and only one of them is a problem.

**"0 cells but the bytes differ" (5 actions) is benign.** A per-cell comparison at threshold
0.94 is meant to tolerate compression noise and antialiasing, so two frames can differ as
files and still match cell by cell. Four of the five are on
[sc11](../entities/clash-royale-sc11-battle-result.md), which has nine self-animating cells.

**"N cells changed but the frames are byte-identical" (7 actions) is not.** Identical input
cannot produce a non-zero diff. For those seven, the frames on disk are not the frames that
were compared — either the capture was retaken when the file was written, or the same buffer
was saved twice.

### The seven

| Screen | Action | Report says | Cells |
|---|---|---|---|
| [sc09](../entities/clash-royale-sc09-king-tower-info.md) | `drag:0.500,0.500>0.750,0.500` | **went to another screen (sc10)** | **188** |
| [sc04](../entities/clash-royale-sc04-social.md) | `drag:0.500,0.500>0.750,0.500` | **went to another screen (sc05)** | **60** |
| [sc08](../entities/clash-royale-sc08-offers-shop.md) | `drag:0.500,0.500>0.750,0.500` | same screen, different appearance | 13 |
| [sc01](../entities/clash-royale-sc01-main-screen.md) | `click:0.970,0.500` | same screen, different appearance | 4 |
| sc01 | `click:0.030,0.850` | same screen, different appearance | 1 |
| [sc02](../entities/clash-royale-sc02-battle-deck.md) | `click:0.970,0.500` | same screen, different appearance | 1 |
| sc11 | `click:0.970,0.500` | same screen, different appearance | 1 |

**Both of the run's small-count "went to another screen" rows are in this list.** They are
also the two the model reads as an overlay opening rather than a navigation — precisely
because their counts are small. That reading now rests on two numbers whose own evidence
contradicts them.

### sc09 and sc10 have the same stored appearance

Independently of the before/after pairs: `sc09-v1.png` and `sc10-v1.png` are **byte-identical**
(both `6ab53ebf…`).[^shots] The pixel test scored them as two screen identities at threshold
0.94, which two identical frames cannot be.

So for sc10, three pieces of evidence disagree: it has its own identity, its arrival is
recorded as 188 changed cells, and its stored screenshot is the same bytes as the screen it
came from. At most one of those can be describing the frame the others describe. See
[the unnamed screens](../entities/clash-royale-unnamed-screens.md), where 188 cells was the
only structural information available about sc10 — and should now be treated as no
information at all.

### What this corroborates

The check is not all bad news, and the good half is more useful than the bad half:

- **All eight transitions of 500+ cells are confirmed at the pixel level.** Every big screen
  change in [the navigation map](clash-royale-navigation-map.md) has before/after frames that
  genuinely differ. The backbone of the map holds.
- **sc11's OK button is confirmed dead.** `click:0.520,0.953` reports 0 cells changed, and its
  before and after frames are byte-identical. The most checkable claim in the model survives
  the check — see [Panels that swallow input](clash-royale-panels-that-swallow-input.md).
- **Seven of sc09's eight probes are confirmed to have done nothing**, by the same test.

The pattern that emerges: **the measurement is trustworthy when it reports a lot or nothing,
and unreliable in between.** Every count over 200 is corroborated; every count of 0 is either
corroborated or innocently explained; the seven contradictions all report between 1 and 188.

## Implications for Guidelines / Playbook

- **Treat a changed-cell count under ~200 as unverified.** Not wrong — unverified. Seven of
  the sixteen in that band are contradicted by their own frames, and there is no way to tell
  from the report which.
- **Never draw a structural conclusion from a small count alone.** "60 cells means a panel
  opened over sc04" is exactly the inference this check breaks.
- **Save the frames that were compared, not a fresh capture.** Whichever of the two causes it
  is, the fix is the same: the diff and the artefact must come from one pair of buffers, and
  the run should assert that a non-zero diff implies non-identical saved frames.
- **Hash the artefacts as a matter of course.** This whole finding cost one pass of SHA-1 over
  a directory. It should be a post-run self-check, not something a wiki ingest stumbles on.
- **A stored appearance that duplicates another screen's should fail the run.** Two identities
  with one set of bytes is a contradiction the tool can detect on its own.

## Related

- [Screen identity is a pixel measurement, not a name](clash-royale-screen-identity-by-pixels.md)
- [The observed navigation map](clash-royale-navigation-map.md)
- [Panels that swallow input](clash-royale-panels-that-swallow-input.md)
- [sc03, sc05, sc10 — the three unnamed screens](../entities/clash-royale-unnamed-screens.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
[^shots]: Screenshots from the same run, `experiments/android-bot/out/Clash Royale-20260903-153913/images/`
