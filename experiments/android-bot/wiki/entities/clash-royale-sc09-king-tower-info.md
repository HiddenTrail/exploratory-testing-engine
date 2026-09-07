---
type: Entity
entity_kind: screen
title: "sc09 — King Tower info panel"
description: A modal detail panel with measured geometry and hard stat values, where seven of eight probed inputs did nothing and its own close button was never pressed.
tags: [clash-royale, screen, sc09, modal]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc09"
---

# sc09 — King Tower info panel

- **Kind:** screen (modal panel)
- **Summary:** a card-detail overlay. Model description: "Displays stats and upgrade info
  for the King Tower (Level 1) in a card-collection/deck-building game; can be closed via
  the X button."[^recon]

![sc09](../../out/Clash%20Royale-20260903-153913/images/sc09-v1.png)

## Details

Seen **9 times**, first at action 4. **All 576 cells held still**, and the report records
**no self-animating cells** for it — that line appears only on screens that have some, and
sc09 is the only *named* screen without it. One appearance stored, still-map entirely
`.`.[^recon]

That total stillness matters: on a screen where nothing moves on its own, "nothing visible
changed" is an unambiguous reading. Seven of the eight inputs sent here produced exactly
that.

### Elements — measured

Eleven elements with points and boxes. Four are marked "(described)" — the box is a model
estimate rather than a trim — and the rest were trimmed from pixels.[^recon]

| Element | Point | Box `[x, y, w, h]` | Trim |
|---|---|---|---|
| **Close button** — red X to dismiss the panel | (0.914, 0.049) | `[0.870, 0.024, 0.088, 0.051]` | trimmed except bottom and left |
| King Tower title | (0.500, 0.053) | `[0.250, 0.015, 0.500, 0.075]` | trimmed except bottom, left, right |
| Level label — "Level 1" | (0.522, 0.110) | `[0.425, 0.090, 0.195, 0.040]` | trimmed except bottom, right, top |
| King Tower character art | (0.500, 0.438) | `[0.150, 0.150, 0.700, 0.577]` | trimmed except left, right, top |
| Damage stat — "50 +4" | (0.280, 0.710) | `[0.080, 0.680, 0.400, 0.060]` | described |
| Hitpoints stat — "2400 +168" | (0.730, 0.710) | `[0.530, 0.680, 0.400, 0.060]` | described |
| Hit Speed stat — "1sec" | (0.280, 0.770) | `[0.080, 0.740, 0.400, 0.060]` | described |
| Range stat — "7" | (0.730, 0.770) | `[0.530, 0.740, 0.400, 0.060]` | described |
| Level 1 Cards counter — "8/9 needed to level up" | (0.500, 0.850) | `[0.350, 0.820, 0.300, 0.060]` | described |
| Chest/tower icon button | (0.310, 0.960) | `[0.160, 0.930, 0.300, 0.060]` | described |
| Cards icon button | (0.700, 0.952) | `[0.550, 0.930, 0.300, 0.044]` | trimmed except left, right, top |

This is the only screen in the model that yields **product data rather than product
structure**: King Tower at Level 1 has Damage 50 (+4 on upgrade), Hitpoints 2400 (+168),
Hit Speed 1 sec, Range 7, and needs 8 of 9 cards to level. Those are oracle-grade values —
checkable, and the sort of thing a test could assert against.

### Actions probed — 8

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `click:0.280,0.710` (Damage stat) | nothing visible changed | – | 0 | 326 ms |
| `click:0.500,0.053` (title) | nothing visible changed | – | 0 | 296 ms |
| `click:0.500,0.438` (character art) | nothing visible changed | – | 0 | 336 ms |
| `click:0.522,0.110` (Level label) | nothing visible changed | – | 0 | 328 ms |
| `click:0.730,0.710` (Hitpoints stat) | nothing visible changed | – | 0 | 339 ms |
| `drag:0.500,0.500>0.250,0.500` | nothing visible changed | – | 0 | 514 ms |
| `drag:0.500,0.500>0.500,0.250` | nothing visible changed | – | 0 | 332 ms |
| `drag:0.500,0.500>0.750,0.500` | went to another screen | [sc10](clash-royale-unnamed-screens.md) | 188 | 357 ms |

**Seven of eight inputs did nothing, and every one settled in under 520 ms.** All five taps
landed on elements the model had identified — the title, the level label, the art, two stat
boxes — which is the expected result if those are labels rather than controls. Two of three
drags did nothing too.

The one that worked changed **188 of 576 cells** — about a third of the frame. Compare the
~520–570 cells that a real screen change moved elsewhere. A 188-cell change reads as a
panel opening or closing over a background that stayed put, which fits sc10 being what is
*behind* this panel as much as a new place.

**That 188 does not hold up.** The before and after frames saved for this drag are
byte-identical, and `sc10-v1.png` is byte-identical to `sc09-v1.png` — so nothing about the
one input that appeared to work on this screen can be reproduced from the images. The seven
that did nothing, by contrast, are all confirmed byte-identical, exactly as reported. See
[the saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md).
On current evidence this panel has **no confirmed exit at all**, which puts it closer to
[sc11](clash-royale-sc11-battle-result.md) than the action table suggests.

### Not tried

Two entries only, and one of them is the way out:[^recon]

- `sc09 drag:0.500,0.500>0.500,0.750` — refused as the Battle button.
- `sc09 click:0.914,0.049` — refused as "the gem counter and its + button - the entrance to
  the gem shop, which is a real-money purchase flow".

The second is the **Close button**. On this screen (0.914, 0.049) is a red X, measured and
trimmed from pixels; on sc01, sc02 and sc08 the same neighbourhood holds the gem counter.
The refusal is keyed to the coordinate, not to the screen, so the only control the model
itself describes as the way out of this panel is the one control it will not press. The
panel is therefore closable in principle and not closable in this model.

## Related

- [sc02 — Battle Deck screen](clash-royale-sc02-battle-deck.md) — the one measured way in, via `click:0.030,0.850`
- [sc10, and the other unnamed screens](clash-royale-unnamed-screens.md) — where the one working drag led
- [Panels that swallow input](../concepts/clash-royale-panels-that-swallow-input.md) — the same shape, worse, on sc11
- [Surfaces that are named but unmodelled](../concepts/clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, sections "sc09 - King Tower info panel" and "What was not tried, and why"
