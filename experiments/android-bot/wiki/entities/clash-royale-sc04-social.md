---
type: Entity
entity_kind: screen
title: "sc04 — Social screen (first of two)"
description: A social screen with clan prompt, friends list, leaderboard and Quickplay, seen once, with 14 model-placed elements and no measured geometry.
tags: [clash-royale, screen, sc04]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc04"
---

# sc04 — Social screen (first of two)

- **Kind:** screen
- **Summary:** the social hub. Model name: "Social screen (Clash Royale-like game)".
  Description: "Shows social features: clan search/create, online friends list,
  leaderboard, and quick navigation to Quickplay, Add Friends, or camera/profile picture.
  Bottom bar provides tab navigation between game sections."[^recon]

![sc04](../../out/Clash%20Royale-20260903-153913/images/sc04-v1.png)

## Details

Seen **once**, first at action 4. **All 576 cells held still** — yet **20 cells move with
no input at all**, the highest self-animation count of any screen in the model. One
appearance stored, and the still-map is entirely `.`, which is what a single sighting
produces: nothing had a second frame to disagree with.[^recon]

The report pairs this screen with [sc06](clash-royale-sc06-social.md): both were named
"Social screen", differing only in "Clash Royale-**like** game" versus "Clash
Royale-**style** game".[^recon] They are kept separate because the pixel test said so.
The strongest evidence they are genuinely different is the bottom nav: sc06 lists left and
right arrows inside the bar that sc04 does not. The shared icons are close but not equal
(chest 0.100 vs 0.088, cards 0.280 vs 0.264, battle 0.440 vs 0.441) — differences small
enough to be the model estimating twice rather than the bar having moved.

### Elements — model-placed only

No boxes were measured. Every coordinate below is the model's estimate ("around"), and
every function is a guess — "likely", "possibly" appear in most entries.[^recon]

| Element | Around | Model's reading |
|---|---|---|
| Create or Join a Clan banner with Show button | (0.500, 0.280) | panel prompting to search/create a clan |
| Show button | (0.830, 0.360) | purple button that likely opens clan search/creation |
| Social panel header | (0.160, 0.460) | section title with sort and filter icons |
| Online / Leaderboard toggle tabs | (0.500, 0.550) | sub-tabs switching the list view |
| Testing player row | (0.500, 0.610) | leaderboard entry, player "Testing", 0 trophies |
| Quickplay button | (0.190, 0.830) | blue button, likely starts a quick match |
| Add Friends button | (0.630, 0.830) | green button, likely opens friend invite/search |
| Camera icon button | (0.880, 0.830) | possibly taking/uploading a profile photo |
| Bottom nav: Chest icon | (0.100, 0.940) | chests/rewards |
| Bottom nav: Cards icon | (0.280, 0.940) | card collection |
| Bottom nav: Battle icon (crossed axes) | (0.440, 0.940) | battle/home |
| Bottom nav: Social (selected) | (0.660, 0.940) | current tab |
| Bottom nav: Trophy/rank icon | (0.900, 0.940) | tournaments or rankings |
| Small colorful icon top center with X | (0.380, 0.040) | possibly an ad or notification popup |

**Quickplay is a live-match risk that is not on the money denylist.** The model reads
(0.190, 0.830) as "likely starts a quick match"; the report's refusal at (0.630, 0.830)
names the Battle button instead — so the control actually refused here was Add Friends,
and Quickplay went through as "no verdict".

### Actions probed — 1

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `drag:0.500,0.500>0.750,0.500` | went to another screen | [sc05](clash-royale-unnamed-screens.md) | 60 | 798 ms |

Only 60 of 576 cells changed on that transition — an order of magnitude less than the
~520–570 that every other screen change moved. A 60-cell change classified as a new
screen means sc05 differs from sc04 in roughly a tenth of the frame: a panel opening over
it, not a navigation.

**With one caveat that undercuts it:** the before and after frames saved for this drag are
byte-identical, so the 60 is not a measurement of the images on disk. This screen's only
recorded exit is one of the seven counts in the run that contradict their own evidence — see
[the saved frames do not always match the changed-cell counts](../concepts/clash-royale-frames-vs-counts.md).

Nothing was ever observed to arrive *at* sc04.

### Not tried

Fifteen entries. Four carry a stated reason — Battle button at (0.630, 0.830), Shop tab at
(0.100, 0.940), Clan tab at (0.660, 0.940), and a downward centre drag also refused as the
Battle button. Eleven are "no verdict for this action", including Quickplay, the Show
button, both toggle tabs, the camera button and the top-centre popup X.[^recon]

## Related

- [sc06 — Social screen (second of two)](clash-royale-sc06-social.md) — same name, different geometry
- [sc05, and the other unnamed screens](clash-royale-unnamed-screens.md) — where the one probe led
- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md)
- [The observed navigation map](../concepts/clash-royale-navigation-map.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, section "sc04 - Social screen (Clash Royale-like game)"
