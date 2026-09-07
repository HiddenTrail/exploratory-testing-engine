---
type: Quality Concept
title: "The observed navigation map"
description: Ten screen changes across eleven screens — a graph with three dead ends, three screens nothing was seen to enter, one inescapable sink, and no route back to the frontier.
tags: [clash-royale, navigation, coverage]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — per-screen action tables"
guidelines_refs: []
---

# The observed navigation map

## What it is

Every screen change the recon run measured, assembled into one graph. Forty-three
screen/action pairs were probed; **ten of them changed screen**.[^recon] Everything below is
that arithmetic — no route is asserted that was not observed.

## Current state / findings

### The graph

```
   sc03 <───────── sc01 <═══════════> sc02 ─────────> sc07 ─────────> sc08
  dead end    dragL   ║  click:0.200,0.970 │  dragU        dragR     no exit
                      ║  + dragR (x2)      │                         found
                      ║                    │ click:0.030,0.850
             dragR    ║                    v
   sc06 ══════════════╝                  sc09 ─────────> sc10
                                                dragR    dead end
   sc04 ─────────> sc05
          dragR    dead end

   sc11   16 actions probed, 0 exits found          sink

   dragL = drag:0.500,0.500>0.250,0.500     dragR = drag:0.500,0.500>0.750,0.500
   dragU = drag:0.500,0.500>0.500,0.250
```

Ten edges, eleven nodes. sc04, sc06 and sc11 have no inbound edge; sc03, sc05, sc10, sc08
and sc11 have no outbound one.

### Six facts the graph makes visible

1. **Two screens carry almost the whole map.** sc02 has three screen-changing actions
   reaching three distinct places (sc01, sc07, sc09); sc01 has three reaching two (sc02
   twice, sc03). Every other screen has one exit or none.
2. **Three screens have no exit because nothing was ever tried on them** — sc03, sc05, sc10.
   They have no action table at all. See
   [the unnamed screens](../entities/clash-royale-unnamed-screens.md).
3. **Two screens have no exit despite being probed.** [sc08](../entities/clash-royale-sc08-offers-shop.md)
   was probed once and the probe stayed; [sc11](../entities/clash-royale-sc11-battle-result.md)
   was probed sixteen times and every probe stayed.
4. **Nothing was ever observed entering sc04, sc06 or sc11.** They were reached — sc11 at
   action 0, the two social screens at actions 4 and 5 — but by no action in any table. The
   graph is not just sparse; it is missing edges that must exist.
5. **The only routes home are sc02's left drag and sc06's right drag.** From sc07, sc08,
   sc09, sc10, sc03, sc05 or sc11, no measured action returns to
   [sc01](../entities/clash-royale-sc01-main-screen.md).
6. **The run confirmed it was stuck, and said so.** After a tap away from any panel at
   (0.03, 0.5) and a home tap at (0.5, 0.95): "tapping home did not reach the frontier -
   sc01, sc02, sc03, sc04, sc05, sc06, sc07, sc08, sc09, sc10 still have untried actions but
   no observed route leads back to them".[^recon]

### The centre drag is not a gesture with one meaning

Five of the ten screen changes are `drag:0.500,0.500>0.750,0.500` — a rightward drag from
the centre. It leads:

| From | To | Cells changed |
|---|---|---|
| sc01 | sc02 | 528 |
| sc04 | sc05 | **60** |
| sc06 | sc01 | 556 |
| sc07 | sc08 | 542 |
| sc09 | sc10 | **188** |
| sc02 | *nothing changed* | 0 |
| sc08 | same screen, new appearance | 13 |
| sc11 | same screen, new appearance | 18 |

The same input produces a full-screen replacement, a tenth-of-a-screen change, a
third-of-a-screen change, and nothing, depending on where it is sent. It is not a "back" or
"next" gesture. **Treating it as one is the mistake this table exists to prevent.**

The changed-cell column separates two kinds of "went to another screen" that the effect
column conflates: ~520–560 cells is a screen replacement; 60 and 188 cells are something
opening or closing over a background that stayed. The pixel identity test is right that
those are different frames, but calling them navigation over-reads it.

**The 60 and the 188 do not survive a check against the screenshots.** Both actions saved
byte-identical before/after frames, so neither count can be a measurement of the frames on
disk, while all eight of the 500+ counts are corroborated. The two-kinds distinction above may
well be real — an overlay is a plausible reading of both screens — but it is currently
supported by the two numbers in this run that contradict their own evidence. See
[the saved frames do not always match the changed-cell counts](clash-royale-frames-vs-counts.md).

### Coordinates that are not elements

Four of the ten transitions were triggered from points no element list mentions:

- `click:0.200,0.970` on sc01 → sc02. y = 0.970 is *below* sc01's measured nav bar and
  close to the browser tab label at 0.981.
- `click:0.030,0.850` on sc02 → sc09. A left-margin probe.
- `drag:0.500,0.500>0.250,0.500` on sc01 → sc03, and `>0.750,0.500` → sc02. Centre-of-screen
  origins.

So a third of the known map runs through points chosen as blind probes rather than as
controls. The controls that *are* named — nav icons, tabs, buttons — contributed almost
nothing to the graph, because nearly all of them were never pressed. See
[Surfaces that are named but unmodelled](clash-royale-unmodelled-surfaces.md).

## Implications for Guidelines / Playbook

- **Do not plan a route through this graph.** It is missing the edges into three screens and
  out of five. Any test case that needs to arrive somewhere specific should establish its own
  route first and record it, rather than reading it from here.
- **The cheapest thing that would improve this map is pressing the bottom nav.** Five icons,
  three of which carry no policy objection, appearing on six screens, and not one of them
  activated. See [the bottom navigation bar](../entities/clash-royale-bottom-navigation-bar.md).
- **A run needs a working return-to-baseline before it needs breadth.** This one ended with
  ten screens holding untried actions and no way to reach any of them; the exploration did
  not run out of ideas, it ran out of reachability.
- **Record changed-cell counts alongside effects.** "Went to another screen" at 60 cells and
  at 555 cells are different events, and only the number distinguishes them — but check the
  number against the saved frames before building on it, because in this run the small ones
  don't hold up.

## Related

- [The saved frames do not always match the changed-cell counts](clash-royale-frames-vs-counts.md)
- [Screen identity is a pixel measurement, not a name](clash-royale-screen-identity-by-pixels.md)
- [Surfaces that are named but unmodelled](clash-royale-unmodelled-surfaces.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`
