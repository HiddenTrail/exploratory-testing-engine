---
type: Entity
entity_kind: screen
title: "sc06 — Social screen (second of two)"
description: The other social screen, seen once, with 19 model-placed elements including left and right arrows inside the bottom navigation bar, and the only observed route home.
tags: [clash-royale, screen, sc06]
status: draft
generated: { by: "claude-opus-5/wiki-ingest", at: "2026-09-04T13:25:00Z" }
sources:
  - id: recon
    resource: "experiments/android-bot/out/Clash Royale-20260903-153913/report.md"
    title: "Clash Royale recon report, 2026-09-03 — section sc06"
---

# sc06 — Social screen (second of two)

- **Kind:** screen
- **Summary:** the social hub again, or a second appearance of it. Model name: "Social
  screen (Clash Royale-style game)". Description: "Shows social features - clan
  search/join, online friends list, leaderboard, and quick actions like Quickplay, Add
  Friends, and a camera/screenshot button. Bottom nav bar allows switching between game
  sections."[^recon]

![sc06](../../out/Clash%20Royale-20260903-153913/images/sc06-v1.png)

## Details

Seen **once**, first at action 5. **All 576 cells held still**; **11 cells move with no
input at all**. One appearance stored, all-`.` still-map — the signature of a single
sighting.[^recon]

Paired with [sc04](clash-royale-sc04-social.md) by the report as two screens the model
named the same thing.[^recon] The element lists overlap almost item for item, but sc06's
list is longer: it separates the Online and Leaderboard tabs into two entries, separates
the sort and filter icons out of the header, and — the substantive difference — carries
**two arrows inside the bottom navigation bar** that sc04 has no equivalent for.

### Elements — model-placed only

No boxes were measured. Coordinates are "around", functions are guesses.[^recon]

| Element | Around | Model's reading |
|---|---|---|
| ad close button (X) | (0.328, 0.043) | small ad banner at top with close X |
| Create or join a Clan! panel | (0.500, 0.220) | promotional panel with Show button |
| Show button | (0.826, 0.318) | opens clan search/creation flow |
| Social header | (0.166, 0.360) | section title |
| sort/reorder icon | (0.779, 0.362) | up/down arrows, likely toggles sort order |
| filter/settings icon | (0.881, 0.362) | sliders icon, likely opens filter settings |
| Online tab | (0.503, 0.415) | show online friends list |
| Leaderboard tab | (0.503, 0.443) | show leaderboard |
| Testing player entry | (0.500, 0.503) | player row, name "Testing", 0 trophies |
| Quickplay button | (0.202, 0.826) | blue button, likely starts a quick match |
| Add Friends! button | (0.632, 0.826) | green button to add friends |
| camera icon button | (0.879, 0.826) | possibly screenshot/share |
| chest/treasure icon (bottom nav) | (0.088, 0.940) | likely Battle/Chests section |
| cards icon (bottom nav) | (0.264, 0.940) | Cards section |
| crossed axes icon (bottom nav) | (0.441, 0.940) | likely Clan/Battle section |
| **left arrow (bottom nav)** | (0.529, 0.940) | **scroll nav tabs left** |
| Social shield icon (bottom nav, active) | (0.664, 0.940) | currently selected tab |
| **right arrow (bottom nav)** | (0.794, 0.940) | **scroll nav tabs right** |
| sword/wreath icon (bottom nav) | (0.917, 0.940) | likely Trophy/Ranking section |

Two adjacent details in that list disagree: the Online tab at y = 0.415 and the
Leaderboard tab at y = 0.443 are 0.028 apart — 56 px at this window height — which is
tighter than any tap can reliably distinguish given every coordinate here is an estimate.
Do not treat them as separately addressable without measuring first.

The two arrows are the reason this screen matters beyond its own content: see
[The bottom navigation bar](clash-royale-bottom-navigation-bar.md).

### Actions probed — 1

| Action | Effect | Goes to | Cells | Settle |
|---|---|---|---|---|
| `drag:0.500,0.500>0.750,0.500` | went to another screen | [sc01](clash-royale-sc01-main-screen.md) | 556 | 1015 ms |

The **only observed route back to the main screen** other than sc02's left drag. Note that
the *same action* — a rightward centre drag — leads to sc05 from sc04, to sc02 from sc01,
to sc08 from sc07, to sc10 from sc09, and nowhere at all from sc02 and sc11. It is not a "back" gesture; it means something different on every screen.

Nothing was ever observed to arrive *at* sc06.

### Not tried

Twenty entries. Five carry a stated reason — Battle button at (0.632, 0.826), Shop tab at
(0.088, 0.940), Clan tab at (0.664, 0.940), Clan tab **again** at (0.794, 0.940) (which
the element list calls the right arrow), and a downward centre drag refused as the Battle
button. The other fifteen are "no verdict for this action", including Quickplay, the ad X,
the Show button, both list tabs, the sort and filter icons, and the left arrow.[^recon]

The (0.794, 0.940) refusal is a coordinate denylist misfiring on a different control than
it was written for — the same pattern as sc02's Collection tab. The right arrow is
unmodelled, not unsafe.

## Related

- [sc04 — Social screen (first of two)](clash-royale-sc04-social.md) — same name, one probe each
- [sc01 — main/home screen](clash-royale-sc01-main-screen.md) — where the one probe led
- [The bottom navigation bar](clash-royale-bottom-navigation-bar.md)
- [The observed navigation map](../concepts/clash-royale-navigation-map.md)
- [Clash Royale recon report, 2026-09-03](../summaries/clash-royale-recon-report-2026-09-03.md)

[^recon]: Clash Royale recon report, `experiments/android-bot/out/Clash Royale-20260903-153913/report.md`, section "sc06 - Social screen (Clash Royale-style game)"
