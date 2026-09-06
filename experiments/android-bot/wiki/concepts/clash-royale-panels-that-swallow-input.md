---
type: Quality Concept
title: "Panels that swallow input"
description: Two modal panels absorbed 23 of the 24 inputs sent to them, including a confirm button pressed at its measured centre — one cause that looks identical to many independent dead controls.
tags: [clash-royale, modal, finding, sc09, sc11]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — sections sc09 and sc11"
guidelines_refs: []
---

# Panels that swallow input

## What it is

Two of the eleven screens are modal panels drawn over the game rather than screens with
their own status and navigation bars: [sc09, the King Tower info
panel](../entities/clash-royale-sc09-king-tower-info.md), and [sc11, the battle result
screen](../entities/clash-royale-sc11-battle-result.md). Between them they received **24 of
the 43 measured screen/action pairs and produced 1 screen change.**

That is the finding, and its importance is not the count. It is that **one panel refusing
every input is indistinguishable, in the data, from a dozen separately broken controls.** A
model built from this run without that distinction would record five dead stat boxes on sc09
and sixteen dead controls on sc11, when the honest reading is *two panels that did not
respond*.

## Current state / findings

### The evidence

| | sc09 | sc11 |
|---|---|---|
| Probes | 8 | 16 |
| Screen changes | 1 (→ sc10, 188 cells) | **0** |
| "nothing visible changed" | 7 | 7 |
| "same screen, different appearance" | 0 | 9 |
| Settle range | 296–514 ms | 3001–3067 ms for 14 of 16 |
| Self-animating cells | none recorded | 9 |
| Own close control | measured X at (0.914, 0.049) — **never pressed** | measured X at (0.083, 0.900) — **never pressed** |
| Own confirm control | – | OK at (0.520, 0.953) — **pressed, 0 cells changed** |

### The single most checkable claim in the model

`click:0.520,0.953` on sc11 is the OK button, at the point the report measured for it,
described by the model as the control to "accept and close the results screen". It was sent.
**Zero of 576 cells changed.**[^recon]

Every element of that claim is observable: the coordinate came from a pixel trim, not a
guess; the action was executed; the effect is a cell count, not a judgement. There is no
oracle for this SUT, so nothing can say the button *should* have worked — but "the control
the interface offers as the way out did not visibly do anything" is falsifiable, and one
repeat under a changed condition would test it.

**It also survives a check the report doesn't make.** The before and after screenshots saved
for `click:0.520,0.953` are byte-identical, as are those for seven of sc09's eight probes.
Every count this run contradicts outright — identical bytes, non-zero diff — is a count
claiming a *change*; no count of zero is contradicted that way. So the dead-input finding on
both panels is the corroborated half of the measurement. (Four of sc11's other zero-count rows
do have differing bytes, which a tolerant per-cell comparison on a screen with nine animating
cells explains without contradicting anything.) See
[the saved frames do not always match the changed-cell counts](clash-royale-frames-vs-counts.md).

### The rival explanations, and what would separate them

Four accounts fit the sc11 data. None is ruled out by the report.

1. **The panel is genuinely stuck** — a client-side hang holding a modal that cannot be
   dismissed. Predicts: nothing works, ever, including the X.
2. **Every tap was late.** The ~3.0 s settle cluster is the strongest hint that something was
   timing out rather than settling. Predicts: the same taps work when the client is
   responsive.
3. **The panel is not where the pixel test thinks it is** — the frames matched sc11's
   fingerprint at ≥ 0.94 but the live client had moved on. Predicts: taps land on whatever is
   actually there, which explains "different appearance, 0 cells changed" appearing three
   times.
4. **The inputs never arrived** — the client was not accepting them at all. Predicts exactly
   what was seen, for every control at once, which is why it must be considered *before*
   concluding sixteen controls are broken.

The discriminating experiment is cheap and was never run: **press the X at (0.083, 0.900)**.
It is the only named exit that was never tried. If it works, 1 and 4 are out and the OK
button alone is the finding. If it does nothing, the finding is the panel, not the button.

### Why the X was never pressed

The report's own verdict, quoted in full because its shape is the point:[^recon]

> This is a close/X button whose consequence is unclear - it may dismiss the result screen
> but could also navigate away from unsaved state or close the match summary in a way that
> cannot be verified as reversible; treating as dangerous per the rule for unclear-consequence
> confirmations is overly cautious, but since it's a close/dismiss control on a results
> screen it is likely safe. However, no visible confirmation of its effect was captured, so
> caution is warranted.

It argues itself to "likely safe" and then declines anyway. A neighbouring point,
(0.030, 0.850), got a verdict ending "actually this simply dismisses the results screen,
which is safe" — and was still not sent.

sc09's X was refused for a different and worse reason: the coordinate (0.914, 0.049) matches
where the **gem counter** sits on other screens, so a screen-independent coordinate denylist
refused a close button as a real-money purchase flow.[^recon] The one control the model
describes as this panel's exit is the one it will not touch.

### sc09 is the milder version of the same shape

Seven of eight inputs did nothing, but sc09 makes the innocent explanation easy to check:
**all 576 cells held still and no cells self-animate**, so "nothing changed" there is
unambiguous, and every settle was under 520 ms — the client was responsive. Five of the seven
dead taps landed on a title, a level label, character art and two stat boxes. Those are
labels. A panel where the labels are inert and one drag closes it is normal.

The contrast is what makes sc11 suspicious: same shape, but on the screen where the settle
times, the self-animation and the confirm button all say something else is going on.

## Implications for Guidelines / Playbook

- **Before reporting N dead controls on one screen, test whether the screen takes input at
  all.** One unresponsive panel produces an observation identical to N independent defects,
  and it also invalidates return-to-baseline, so every later test in the run starts somewhere
  nobody chose. This run ended stuck for exactly that reason.
- **A settle-time cluster is a measurement failure, not a measurement.** Fourteen values
  inside 66 ms means the column stopped reporting. Treat a settle at the ceiling as "unknown",
  not "slow".
- **"Same screen, different appearance" with zero changed cells is a contradiction worth
  logging.** It means the identity test and the change test disagree on one pair of frames —
  most likely a frame captured mid-animation on a screen with self-animating cells.
- **A denylist keyed to coordinates must be keyed to screens too.** Refusing (0.914, 0.049)
  as a gem counter on a panel whose X is at (0.914, 0.049) removes the exit and adds no
  safety.
- **A "likely safe" verdict that ends in a refusal should be logged as an unresolved
  decision, not a refusal.** Three of sc11's four reasoned verdicts talked themselves into
  safety and stopped anyway; the cost was the run's only remaining exit.

## Related

- [sc11 — battle result screen](../entities/clash-royale-sc11-battle-result.md)
- [sc09 — King Tower info panel](../entities/clash-royale-sc09-king-tower-info.md)
- [The observed navigation map](clash-royale-navigation-map.md)
- [Surfaces that are named but unmodelled](clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
