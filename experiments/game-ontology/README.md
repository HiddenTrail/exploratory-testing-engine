# game-ontology

Point this at a game it has never seen, let it run for ten minutes, and get back a
map of the game's screens, what each input does to them, and pictures of all of it.

Sibling experiment to `game-screen-probe`, aimed at the opposite question. That one
asked "can a harness read and drive this specific game", and the answer came as
constants - a board rectangle, an arrow's coordinates, the green threshold that
separates a forest tile from a bush. Every one of those cost calibration work, and
each is worth nothing for the next game. This one asks whether that work can be
*produced* instead of paid for.

So the rule here is that no file may contain a fact about Tile Tale except
`target.py`, and even there only what the OS needs (what to launch, what the window
is called), safety rules a person decided, and per-game calibration that a session's
own report shows how to re-cut. Screens, buttons, layouts and behaviours are output. If
a board rectangle ever appears in this directory, the experiment has stopped testing
what it claims to.

That rule is easy to break by accident, because a tuning constant does not look like
game knowledge. Two did: how long to wait for a window to settle (this game opens
windowed and switches to fullscreen ~3.3s later) and how much of a screen must agree
for two frames to be the same screen (measured off one session's own transitions).
Both were plain module constants in the general code, which is how one game's
calibration silently becomes every game's default. They now live on `Target`, next to
the measurement that justifies them.

## Running it

```bash
py recon.py --minutes 10                 # explore, vetting each new appearance
py recon.py --minutes 10 --no-model      # mechanics only; committing actions stay locked
py describe.py out/tile-tale-<stamp>     # annotate the graph, rewrite the report
py controller.py                         # smoke test: own a window, read it, close it
```

Output lands in `out/<target>-<stamp>/` (gitignored):

| file | what it is |
|---|---|
| `ontology.json` | the whole finding: screens, appearances, transitions, refusals |
| `images/*.png` | one per appearance; `ontology.json` references these by relative path |
| `report.md` | the same thing to read, with the images inline |

`recon.py` writes navigation and structure; `describe.py` adds the names and the
per-modality behaviour. The JSON is the artifact, the report is derived - if they ever
disagree, the JSON is right.

## The unit is a transition, not an image

The output has to be able to say things like "this settings entry sits in a list on
the front page, and clicking it opens a screen of settings". That is three claims
about edges and one about a node, so a pile of labelled screenshots cannot express
it. The session builds a labelled multigraph instead: nodes are screens, edges are
(screen, action) -> screen, and every edge records the input modality that produced
it.

**Two granularities, because one is never right.** A *screen* is a place ("the main
menu"), matched loosely. A *variant* is an exact appearance ("the main menu with the
third row lit"). Collapse them and you lose the most useful finding available:
`down` changes the variant and not the screen, while `enter` changes the screen. That
*is* "what does the keyboard do here", and it falls out of the split for free rather
than needing a rule per game.

**Where geometry cannot decide, the model arbitrates.** A screen match is a threshold
on how much of the stable area a frame reproduces, and a threshold has to be wrong
somewhere - opening a menu over a menu can move fewer cells than a busy screen moves
on its own. So when a vetted appearance comes back with a name that disagrees with the
screen it was filed under, it is split into a screen of its own and its transitions
are re-filed, which turns an edge that stayed inside one screen into a screen change.
Only in that direction: two names differing is evidence of two places, while two names
matching is no evidence that two screens are one, since "inventory" is a fine name for
eight different inventories. Splits are counted in the JSON - the number climbing says
`screen_match` is cut too loose for this game.

**Which pixels identify a screen is learned.** On each revisit, cells that differ
from the screen's first sighting are marked volatile and dropped from its identity
test, so a scoreboard, an animated background or an entire game board stops breaking
recognition. The accumulated mask is itself an output - it says where the dynamic
content lives, which is the hand-measured rectangle from the other experiment,
arrived at without measuring.

## Safety, in three layers

Exploration is destructive by default. An explorer poking at an unmapped UI will
eventually find the control that quits the game, and it takes the rest of the
session's budget with it.

1. **A coordinate denylist** in `target.py`, enforced inside `Controller.click` so no
   policy above it can route around it.
2. **Modality gating.** Cursor moves and arrow keys are safe by construction and need
   no permission. `enter`, `space`, `esc` and every click are *committing* and need a
   verdict first.
3. **Vetting.** A new appearance is read by the model before anything may be
   committed on it. This is the only layer that can protect a keyboard-driven menu,
   where the dangerous action is `enter` on a row whose position nothing knows in
   advance and no coordinate rule can help.

`SAFETY_BRIEF` tells the model the two ways of being wrong do not cost the same:
a safe control called dangerous loses one branch, a dangerous control called safe can
end the session and destroy save data. It is instructed to be conservative rather
than accurate.

This works. On the first vetted run the only hover-reactive point on the main menu
turned out to be **QUIT**, and the model refused to click it - a control the
coordinate denylist did not cover, because nobody knew it was there.

## Cost

The fast loop is pure stdlib Python and does not call a model. Model calls are per
*newly discovered appearance*, not per action, which is what makes ten minutes
affordable: a few dozen calls, against several hundred actions. Gating each action on
a vision call instead would cut the action budget by roughly a factor of five and buy
nothing the transition record does not already contain.

`--no-model` is the honest floor: no third safety layer, so committing actions stay
locked and the session maps only what cursor moves and arrow keys reveal. On Tile Tale
that is the main menu's highlight and nothing else. It is a real result about what
this machinery can discover with no intelligence in the loop, and it is not much.

## Every behaviour claim is sourced

`describe.py` writes, for each element, a behaviour entry per input modality - `click`,
`hover`, `key:down`, `key:enter` - and each entry either cites the transition IDs that
witnessed it or is marked `hypothesis`.

That is enforced in `_validate_annotation`, not requested in the prompt. A cited
transition ID that is not in the evidence is a rejected tool call, and the retry loop
hands the model its own invented IDs back. Asking nicely for provenance produces
confident prose about buttons that were never pressed; refusing the call produces
either a citation or an admission. The distinction survives into the JSON, so a later
consumer can take the observed claims and leave the guesses.

## Things that bit

1. **A screen-level verdict on `enter` is unanswerable, and the model rightly refused
   it.** The first vetted run cleared 0 of 4 committing actions on the main menu and
   went nowhere. The refusal was correct - *"NEW GAME appears highlighted, so pressing
   Enter could overwrite existing save progress"* - and it was the question that was
   wrong. `enter` acts on whatever is selected, so its safety is a property of the
   *variant*, not the screen. Verdicts for keys now live on variants and verdicts for
   clicks on screens, matching how each names its target: by selection, or by
   position. Paralysis and prudence look identical from outside; the tell was that
   the refusals cited a specific row.

2. **A fullscreen-exclusive window minimizes itself during startup, and waiting
   politely never recovers.** The window reached 3840x2160, then parked at
   `(-32000, -32000)` with a 0x0 rect, and the readiness loop watched it happen and
   reported "never rendered a settled frame". Restoring has to happen *inside* the
   settle loop: the timeout describes the symptom and discards the one fix that
   works.

3. **Readiness cannot wait for a recognizable screen, and cannot trust the first
   rect.** `game_session.py` could wait for a screen the harness knew. Here there is
   nothing to recognize, so readiness is: the rect has stopped changing, the frame
   has variance, and consecutive frames agree. The rect clause is not optional - the
   game opens windowed 1280x720 and switches to fullscreen about 3.3s later, so any
   quiet period short enough to be useful also fires before the switch, and every
   fraction then resolves against a rect the game has already discarded. The symptom
   is not a geometry error; it is a session where no input ever lands.

4. **"Stop when the result is familiar" ends a list walk on its first step.**
   Navigating a menu alternates between new rows and rows already seen, and the first
   press back down the list lands somewhere known - which read as exhausted with most
   of the menu unvisited. The rule is a *run* of presses that reveal nothing new,
   which is what actually happens at the end of a list.

5. **Retiring an action per screen strands every other row of a menu.** Once the arrow
   keys had gone stale and the current row's `enter` was settled, other rows still had
   untried `enter`s and nothing could reach them - the only way to a row is to
   navigate to it. Arrow keys therefore come back onto the table as the move that
   crosses an *intra-screen* frontier, which is a different job from the one they were
   retired for.

6. **A pure search and a side-effecting one must not share a function.** The frontier
   search calls the "what should I do next" check on every screen it walks past. While
   that check also marked blocked actions as tried, searching consumed the frontier it
   was searching for. Split into a pure `next_action` and an explicit `prune_blocked`.

7. **Hover is the only input safe to sweep blind.** A cursor move is the least
   state-changing thing that can still provoke a visible reaction, so the click
   candidates on a new screen are drawn from a hover sweep rather than from a grid of
   guesses. Most games ignore hover entirely, so a screen that has not reacted after
   14 widely-spread probes is abandoned - and the probe order is strided, so bailing
   early has still sampled the whole screen instead of the top rows.

8. **A pixel threshold filed the settings menu as the main menu, and the model had
   already said otherwise.** Pressing `enter` changed 42 of 576 cells - 0.927
   agreement, above the 0.88 threshold in use - so the settings menu was recorded as
   another appearance of the menu it opened over, while the vetting call for that same
   image came back named `'Settings menu'`. Recalibrating to 0.94 (the measured gap
   between "highlight moved", 11-16 cells, and "different screen", 42) fixes this
   game and only relocates the problem. The durable fix is that the disagreement is
   now the signal: the name splits the screen, and the threshold is left to be
   approximately right.

9. **Capture reads the screen DC clipped to the client rect** (inherited from
   `probe.py`, and worth restating): an occluded window returns whatever is on top of
   it as a clean, plausible frame of the wrong application. There is no error. That is
   why foreground is asserted *before* a frame is trusted rather than after something
   downstream looks wrong.

## What is reused, and what standalone means

`probe.py` is imported as-is for capture, input, PNG writing and window finding - it
was already fully general. `bench_shuffle.py` and `game_session.py`'s constants are
Tile Tale knowledge and are deliberately not reused (they are the output this
experiment is trying to produce); the parts of the latter worth
keeping (Steam library discovery, the foreground-lock retry, WM_CLOSE-then-force) are
reimplemented here without the game.

`engine/client.py` provides transport: Bedrock-or-API-key auth, forced tool calls,
schema validation and informed retries. Reusing it does not make this part of the
engine - what is standalone is the ontology schema and the exploration policy, and
reimplementing auth and backoff to prove a point would only add a second thing to
keep working. `call_tool_with_retry` passes `user_message` through as the message
content untouched, so handing it a list of blocks gets image support with no change
on that side.
