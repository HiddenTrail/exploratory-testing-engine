---
type: Entity
entity_kind: screen
title: "sc11 — battle result screen"
description: The most-visited screen in the model and the only one with no exit — sixteen distinct inputs, including its own OK button, all left it unchanged.
tags: [clash-royale, screen, sc11, modal]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc11"
---

# sc11 — battle result screen

- **Kind:** screen (modal panel)
- **Summary:** the post-match result. Model description: "Displays the outcome of a battle
  (Winner banner with player/clan names) with options to close (X) or confirm (OK) and
  return to the game."[^recon]

![sc11](../../out/Clash%20Royale-20260903-153913/images/sc11-v1.png)

> **This is where the run ended, and it could not leave.** Sixteen distinct inputs, the
> most of any screen in the model, and not one of them changed the screen. See
> [Panels that swallow input](../concepts/clash-royale-panels-that-swallow-input.md).

## Details

Seen **28 times**, first at action 0 — the most-visited screen in the model, and more
sightings than the 16 actions this run performed, which is one of the signs the screen
inventory is cumulative across runs.[^recon] **548 of 576 cells held still**; **9 cells
move with no input at all**. **5 appearances stored**; two of the differences are recorded
without explanation and one is labelled `selected '""'` — an empty selection string.

The cells that never held still sit in rows 1–3, spread across x 3–30 — the banner area
with the crowns and names — plus one cell at row 8, x 14.[^recon]

A battle result screen implies a battle happened. Nothing in this run entered one; the
first sighting is at action 0, i.e. the client was already showing it.

### Elements — measured

Six elements. Three of them could not be trimmed and the report says why in each case,
which is unusual candour worth preserving:[^recon]

| Element | Point | Box `[x, y, w, h]` | Why the box is what it is |
|---|---|---|---|
| Winner banner — "Winner!", crown icon, three gold crowns, winning player and clan | (0.500, 0.255) | `[0.150, 0.080, 0.700, 0.350]` | "described, because its contents reach every edge of the margin around it … so its own edges were not measured" |
| VS text | (0.500, 0.380) | `[0.420, 0.340, 0.160, 0.080]` | trimmed except bottom, left, right |
| Losing team banner — "Testing" / "No Clan", three blue crowns | (0.500, 0.655) | `[0.100, 0.480, 0.800, 0.350]` | described, same reason as the Winner banner |
| **Close button (X)** — red X, bottom left | (0.083, 0.900) | `[0.001, 0.870, 0.163, 0.060]` | trimmed except bottom and top |
| **OK button** — blue confirm, bottom centre | (0.520, 0.953) | `[0.380, 0.940, 0.280, 0.025]` | trimmed except left, right, top |
| Battle scene background — river, bridges, troop icons | (0.500, 0.625) | `[0.000, 0.400, 1.000, 0.450]` | "described, because the pixels in it trim to 1.000x0.564 of the window, which is too thin or too large to be one control" |

The account in view lost: "Testing" with three blue crowns is the losing banner, and the
winner is a different player and clan.

### Actions probed — 16, exits 0

| Action | Effect | Cells | Settle |
|---|---|---|---|
| `click:0.030,0.500` | same screen, different appearance | 0 | 3045 ms |
| `click:0.030,0.800` | same screen, different appearance | 0 | 3014 ms |
| `click:0.200,0.030` | same screen, different appearance | 4 | 3012 ms |
| `click:0.500,0.255` (Winner banner) | nothing visible changed | 0 | 3063 ms |
| `click:0.500,0.380` (VS text) | same screen, different appearance | 1 | 3067 ms |
| `click:0.500,0.625` (battle scene) | nothing visible changed | 0 | 3035 ms |
| `click:0.500,0.655` (losing banner) | nothing visible changed | 0 | 3037 ms |
| `click:0.500,0.970` | nothing visible changed | 0 | **372 ms** |
| **`click:0.520,0.953` (OK button)** | **nothing visible changed** | **0** | 3030 ms |
| `click:0.970,0.500` | same screen, different appearance | 1 | **1285 ms** |
| `click:0.970,0.800` | same screen, different appearance | 9 | 3015 ms |
| `drag:0.500,0.500>0.250,0.500` | same screen, different appearance | 6 | 3011 ms |
| `drag:0.500,0.500>0.500,0.250` | same screen, different appearance | 1 | 3001 ms |
| `drag:0.500,0.500>0.750,0.500` | same screen, different appearance | 18 | 3015 ms |
| `scroll:down3:0.500,0.500` | nothing visible changed | 1 | 3021 ms |
| `scroll:up3:0.500,0.500` | nothing visible changed | 0 | 3067 ms |

Three readings, in descending order of confidence:

1. **The OK button did not work.** It is the control the model's own description names as
   the way to "accept and close the results screen", it was pressed at its measured point,
   and 0 of 576 cells changed. That is the single most checkable claim the model supports —
   and it checks out: the before and after screenshots saved for that click are byte-identical
   ([the saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md)).
2. **Fourteen of the sixteen settle times fall in 3001–3067 ms.** The two that do not are
   372 ms and 1285 ms, and both are among the "same screen"/"nothing changed" results too.
   A 66 ms spread across fourteen measurements is not fourteen measurements; it reads as a
   ceiling. The report never states a settle cap, so this is inference — but it means the
   settle column on this screen carries almost no information.
3. **"Same screen, different appearance" with 0 changed cells appears three times** — at
   (0.030, 0.500), (0.030, 0.800) and, with 1 cell, (0.500, 0.380). A different *stored
   appearance* with zero changed cells is the identity test disagreeing with the change
   test on the same pair of frames. On a screen with 9 self-animating cells, that is what a
   frame captured at the wrong moment looks like.

### Not tried

Nine entries, and this is where the report's reasoning is least mechanical.[^recon] Five are
coordinate-denylist refusals (gold ×1, gem ×1, Clan tab ×1, Pass Royale ×1, Battle-button
drag ×1) that are all misfires on this screen — there is no shop, clan tab or Battle button
on a result panel.

The other four are individually argued, and three of them concern getting out:

- `click:0.083,0.900` — **the X itself.** The verdict talks itself in a circle: "treating as
  dangerous per the rule for unclear-consequence confirmations is overly cautious, but since
  it's a close/dismiss control on a results screen it is likely safe. However, no visible
  confirmation of its effect was captured, so caution is warranted." Never pressed.
- `click:0.030,0.850` — near the X: "actually this simply dismisses the results screen,
  which is safe" — and still not sent.
- `click:0.200,0.970` — refused because "this point lands on empty background grass/tree
  decoration near the bottom, not on the visible X close button".
- `click:0.030,0.200` — "lands on background scenery (rocks/bushes) with no visible
  interactive element".

So the panel's two named exits were treated differently: OK was pressed and failed; X was
argued about and never pressed. Which of those is the reason the run got stuck is not
determined by this report.

Note also that four of this screen's candidate actions were lost to crashes rather than
decisions: the report records "could not get a verdict for click:0.200,0.970,
click:0.500,0.970, click:0.030,0.200, click:0.030,0.800 ('name')" and separately "could not
get a verdict for click:0.970,0.800 ('str' object has no attribute 'get')", after which "the
top-up's vetting call failed, so the 7 new candidates are unplanned again rather than
retired unsent" — twice.[^recon]

## Related

- [Panels that swallow input](../concepts/clash-royale-panels-that-swallow-input.md) — this screen and sc09 together
- [sc09 — King Tower info panel](clash-royale-sc09-king-tower-info.md) — the milder case
- [The observed navigation map](../concepts/clash-royale-navigation-map.md) — why nothing led here and nothing led away
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc11 - battle result screen", "What went wrong" and "What was not tried, and why"
