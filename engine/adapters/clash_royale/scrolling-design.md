# Design note: understanding scrollable screens

Status: **draft for review** — design only. No input primitive and no code is
proposed for merge here; the input/safety question is deliberately deferred (see
§5). The point of this note is to agree *how a scrollable surface should be
modelled* before anything is built.

## The problem

Some screens in this client are not single frames. They are **viewports onto a
larger surface** you can move through:

- **Vertical page scroll** — a screen taller than the window, e.g. the
  news/events feed, where content below the fold only appears once you scroll.
- **Horizontal banner carousels** — a strip of promotional/event banners that
  pages left and right within an otherwise-fixed screen.

Recon today has no concept of this. It sees pixels, identifies a screen by
comparison, and that is the whole vocabulary. A surface you can scroll therefore
breaks the model in two separate ways.

## 1. Why the current identity model over-splits a scrollable surface

Screen identity is a `GRID_COLS`×`GRID_ROWS` grid of downscaled BGR cells (~576
cells), matched against stored fingerprints at the `SAME_SCREEN` cut, with
per-cell `stable` / `animated` / `protected` maps to tolerate moving regions
(see `session.py` and `reference.py`).

That machinery answers *"is this the same frame as one I've seen?"* — and for a
scrollable surface the answer is **no at every scroll offset**, because scrolling
translates most of the grid. So a single feed becomes `sc-a`, `sc-b`, `sc-c`… one
"new screen" per scroll position. This is the **same failure class** we already
observed and flagged in the navigation map: the Social screen was split into
seven IDs because its animated background moved the fingerprint. A scrollable feed
is that bug on purpose and without bound — the surface can be arbitrarily tall, so
the number of spurious screens is limited only by how far the run happened to
scroll.

The fixed **chrome** (top bars, bottom navigation) does *not* translate. That
asymmetry is the signal we can exploit: on a scroll, part of the grid is pinned
and part slides. On a genuine screen change, the whole grid changes together.

## 2. Detection: "this frame is a scrolled view of the same surface"

Proposed as a comparison between the before-frame and the after-frame of a scroll,
computed on the existing grid — no per-screen calibration, in keeping with the
package's rule that identity uses only what a frame yields for free:

1. **Find the pinned region.** Cells that are byte-identical before and after are
   candidate chrome (fixed top/bottom bars).
2. **Find the translation of the rest.** For the non-pinned cells, test whether
   the after-frame equals the before-frame shifted by *k* rows (vertical) or *k*
   columns (horizontal), for small *k*. A strong best-shift with low residual is
   the fingerprint of a scroll; no good shift at any *k* means a real transition.
   This is a bounded cross-correlation over the coarse grid, so it is cheap.
3. **Classify:**
   - best shift ≈ 0, residual ≈ 0 → **same view** (`same_screen`, as today).
   - clear non-zero best shift, pinned chrome intact, low residual →
     **same surface, scrolled** (the new case).
   - no coherent shift → **different screen** (as today).

Thresholds are a measurement, not a constant — they belong in the carried
reference alongside the grid and `SAME_SCREEN`, re-extracted per pass, for the
same reason those are (a looser cut here would silently accept transitions the
fingerprints were never taken under).

Edge cases to settle during prototyping: an animated background *and* a scroll at
once (the Social case combined with a feed); a surface that reaches its end (a
scroll input that produces zero shift because there is nothing more to reveal — a
real and useful observation, "bottom of feed"); and a carousel that wraps.

## 3. Representation in the ontology

Introduce a **surface** as a first-class thing distinct from a screen:

- A **screen** stays what it is: one identifiable view.
- A **surface** is a screen the run has evidence is scrollable, carrying:
  - `axis`: `vertical` | `horizontal` | `both`.
  - `extent`: how far it scrolled before hitting the end / wrapping / the run
    stopping (in scroll steps, honestly labelled as a lower bound when the run
    did not reach the end).
  - `pinned_cells`: the chrome that stayed fixed — this is what lets a later
    visit re-identify the surface from *any* scroll offset, which is the whole
    payoff.
  - `views`: the ordered fingerprints captured at each offset. Kept, not
    collapsed, so the surface can still be re-identified and so a stitched
    panorama can be rendered later, but grouped under one surface id rather than
    masquerading as N screens.

The relationship to the existing `variants` field is worth deciding explicitly:
variants are "the same screen, something small moved"; a scrolled view is "the
same surface, the viewport moved a known amount." They are close enough that
overloading `variants` is tempting and probably wrong — a variant is not ordered
and has no extent. Recommend a separate structure.

Knock-on effects on the navigation map (`generate_nav_map_html.py`): a surface
should render as **one node**, not one-per-offset, which also removes a large
source of the near-duplicate warnings the map currently emits. The detail panel
can show the stitched surface or the ordered views.

## 4. Driver prediction vocabulary

`PREDICTIONS` today is `("same_screen", "known_screen", "new_screen")`. A scroll
needs a fourth structural outcome so the Driver can make a checkable claim about
it:

- **`scrolled_same_surface`** — "this input moves the viewport within the current
  surface without leaving it." Predicting this and instead getting `new_screen`
  (the scroll navigated away) or `same_screen` (nothing moved — end of feed, or a
  dead scroll region) are both exactly the kind of falsifiable navigation anomaly
  this adapter exists to find.

Note this stays *structural* — it never asks the Driver to read what is on the
surface, consistent with the existing contract.

## 5. Input — deferred, but the model must not prejudge it

Per this pass's decision, **no input primitive is added here.** Recorded so the
deferral is a decision and not an omission:

- The action space is **taps only, and swipes/drags are excluded on purpose** —
  a swipe was the single recorded escape from the coordinate guard
  (`actions.py`). Scrolling reintroduces motion input, so it is a safety-posture
  decision for the operator, not a default.
- The controller already has two guarded motion primitives:
  [`scroll`](../../../experiments/game-ontology/controller.py) (mouse wheel —
  "nothing about a wheel is destructive on its own", does not hold a button down
  along a line) and [`drag`](../../../experiments/game-ontology/controller.py)
  (a held-button swipe whose *whole path* is vetted). The wheel is materially
  safer and is the natural candidate for **vertical** scroll; **horizontal**
  carousels conventionally need a swipe over banner content, which is near
  denylisted promotional areas — a materially riskier proposition.

**Design constraint that follows:** the detection (§2) and representation (§3)
must be **input-agnostic** — they operate on before/after frame pairs regardless
of *how* the viewport moved. That keeps this model valid whichever input decision
is made later, and lets the model be validated against recorded scroll pairs with
no live client and no new action in the catalogue.

## 6. Non-goals

- Reading the *content* of a feed (what an event is, what a banner advertises).
  Out of scope for the same reason screen-content reading is: it cannot be done
  honestly without per-screen calibration.
- Purchasing, dismissing, or interacting with anything a scroll reveals. Scrolling
  is looking, not touching.
- Any change to the tap catalogue or the denylist.

## 7. Open questions for review

1. Separate `surface` structure vs. extending `variants` — this note recommends
   separate; confirm.
2. Is `scrolled_same_surface` the right (and only) new prediction token, or do we
   also want to distinguish "hit the end of the surface" as its own outcome?
3. How should a surface re-identify across visits when *only* the pinned chrome
   matches — is chrome alone enough to claim "same surface," given two different
   feeds can share the same top/bottom bars? (This mirrors the `_identify`
   caution that two screens sharing only the navigation bar must not collapse.)
4. Validation data: can we capture a few recorded vertical-scroll frame pairs of
   the news/events feed now (by hand, out of band) to prototype §2 against,
   independent of the deferred input decision?
