# game-ontology

```bash
py sweep.py --game Mitosis
```

Name a game the way you would say it out loud, and get back a map of its screens, what
each input does to them, and pictures of all of it. Nothing else is supplied: not the
executable, not the window title, not how long it takes to start, not what any of its
screens look like. Those are found, measured, or discovered.

Sibling experiment to `game-screen-probe`, aimed at the opposite question. That one
asked "can a harness read and drive this specific game", and the answer came as
constants - a board rectangle, an arrow's coordinates, the green threshold that
separates a forest tile from a bush. Every one of those cost calibration work, and
each is worth nothing for the next game. This one asks whether that work can be
*produced* instead of paid for.

So the rule here is that no file may contain a fact about a specific game except
`target.py`, and even there only safety rules a person decided - which coordinates
must never be clicked, and why. Screens, buttons, layouts and behaviours are output. If
a board rectangle ever appears in this directory, the experiment has stopped testing
what it claims to.

That rule is easy to break by accident, because a tuning constant does not look like
game knowledge. Two did: how long to wait for a window to settle, and how much of a
screen must agree for two frames to be the same screen. Both started as module
constants in the general code, which is how one game's calibration silently becomes
every game's default; both then became fields on `Target`, which is honest but still
means a new game needs a person to fill them in. They are now **measured**, which is
the version the experiment was actually claiming - see `calibrate.py`.

## Running it

```bash
py sweep.py --game Mitosis                 # up to five 3-minute passes, 15 minutes all in
py sweep.py --game Mitosis --budget 40      # a longer leash; passes fill it as they fit
py sweep.py --game "tile tale" --no-model   # mechanics only; committing actions stay locked
py recon.py --game Mitosis --minutes 3     # one pass on its own
py describe.py out/<...>/pass5             # annotate the graph, rewrite the report
py mission.py --game Mitosis               # plan against the newest map, then fly the plans
py controller.py --game Mitosis            # smoke test: find it, own a window, read it, close it
py selftest.py                             # no game at all: check the close-ups against a fake one
```

`selftest.py` is the one check that needs neither a game nor a model. It drives the real
session against a synthetic menu built to have the behaviours the imaging code reasons
about, and prints what was filmed, where it was aimed and whether each before/after pair
is actually two pictures - which a real game cannot tell you, because it has no second
opinion about what its own buttons look like. Its second screen answers the wheel and the
drag while its first ignores both, which is how the escalation in item 26 gets checked in
both directions - counting the probes that were *sent*, since an action retired for good is
retired by adding its id to the same set that records the ones that happened. It takes
about two seconds. It is
not in CI and cannot be: `probe.py` calls `ctypes.WinDLL` at import, so importing `recon`
needs Windows, and the workflow runs on ubuntu.

The name is matched loosely against two lists pooled together - installed Steam games
across every library, and every Start-menu shortcut that resolves to an executable - so
`mitos`, `Mitosis` and `mitosis` all work, a game that came from its publisher's own
launcher rather than from Steam is found at all, and an ambiguous name lists what it
matched, and from where, instead of guessing. Output lands in `out/<game>-sweep-<stamp>/` (gitignored):

| file | what it is |
|---|---|
| `sweep.md` | what each pass *added*, and the measurements behind the calibration |
| `passN/ontology.json` | the whole finding: screens, appearances, transitions, refusals |
| `passN/images/*.png` | one per appearance; the JSON references these by relative path |
| `passN/report.md` | the same thing to read, with the images inline |

The last pass's ontology is the whole sweep, not a fifth of it - each pass inherits the
one before. `calibration/<game>.json` is the exception to the gitignore: it is a
measurement this machine made, and it is what makes the second sweep of a game cheaper
than the first.

`recon.py` writes navigation and structure; `describe.py` adds the names and the
per-modality behaviour. The JSON is the artifact, the report is derived - if they ever
disagree, the JSON is right.

## Passes, not one long run

A recon session degrades as it goes. It wanders into a submenu with no route back, the
window breaks, a dialog it cannot read swallows every input. The one move that reliably
returns an unknown game to a known state is a cold launch - and inside a long session
that can only ever be spent as a *recovery*, after the time is already gone.

So the relaunch is the plan instead. Five passes of three minutes: each starts at the
title screen, dies however it dies, and hands everything it learned to the next one.
Both halves of that are load-bearing.

**The map carries.** `recon.py --resume` reloads a previous pass's ontology - screens,
appearances, every key already answered, every verdict already bought, and the cell
masks exactly as they were. Pass 4 rejoins the game knowing the routes and spends its
three minutes past them. The masks have to round-trip precisely rather than
approximately: the protected-cell set is the only reason a screen split stays split, so
a pass that guessed at it would re-merge what its predecessor separated and then pay
for the same split again.

**The calibration carries, and improves.** Each pass recuts `screen_match` from every
transition recorded so far, so the number is standing on more evidence each time.

**The 15 minutes is a ceiling, not a sum.** `--budget` is wall clock over the whole sweep,
counted from before the game is even resolved, and it governs `--passes` and `--minutes`
rather than being derived from them. That product is not the same promise: it counts only
time inside the exploration loop, while a sweep also pays per pass for a cold launch, a
readiness wait, a report write and a shutdown - about a third again on top, measured. So
each pass is handed whatever is left minus a reserve for its own ends, a pass that cannot
get 45 seconds of exploring is not started, and the summary reports the wall clock it
actually took against the budget it was given.

Behind that is a kill switch: a daemon thread that closes the game and force-exits one
minute past the budget. Trimming a pass only disciplines code that checks a clock, and the
runs worth insuring against are the ones that do not - a launch that never settles, a model
call that never returns. It is the one part of the sweep that cannot be blocked.

The sweep stops after two consecutive passes that add nothing - no new screen, no new
transition. Not on "exhausted", which a session reports while merely stuck, and not on a
fixed count, which either wastes passes on a small game or truncates a large one. Two,
because one is fooled by a single unlucky pass that spent its budget lost in a menu. The
summary says which of the two reasons stopped it, because "it stopped finding things"
and "it ran out of passes" are different results and only one means the map is done.

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
   policy above it can route around it. For a drag it is a *path* test and not two point
   tests: the button is down the whole way across, so the ends being clear says nothing
   about the middle.
2. **Modality gating.** Cursor moves and unmodified arrow keys are safe by construction
   and need no permission. `enter`, `space`, `esc`, every click, every drag, every turn of
   the wheel and any arrow key with a modifier held are *committing* and need a verdict
   first.
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

## Missions: the map as an input

`sweep.py` explores by a fixed policy - arrow keys, then this appearance's committing
keys, then points the cursor was seen to react to, then two turns of the wheel and a drag
at the middle of the window, then breadth-first to the nearest screen with something
untried. That policy is blind on purpose, since it has to work on a
game nobody has looked at, and the price is that it cannot use what it just learned. A
map saying "sc03 is the campaign screen and it has a Level 1 button at (0.31, 0.44)"
reaches the explorer as four arrow keys and a hotspot list, because that is all the
explorer can read.

`mission.py` closes that loop. The model reads a digest of the map, the missions already
flown, and a fresh screenshot of where the harness is standing, and writes **one**
mission: a goal and a short list of steps - `go`, `press`, `click`, `hover`, `drag`,
`scroll`, `wait`, `restart`, `expect`. This program executes them literally and reports
what each step actually did, then asks for the next one, briefed by what the last one
proved. A step that aims can also name a mouse button and modifiers to hold, so
`ctrl+scroll` and `shift+click` are things a plan can say.

**The plan is a hypothesis and the executor is the referee.** Which is why a mission must
contain at least one `expect` step, enforced in the validator rather than requested in the
prompt: "click Campaign, then we should be somewhere new" is a claim that can be wrong,
and when it is wrong the report says so at the step where it broke, naming the screen the
harness was actually on. A plan with no expectation cannot fail, so it cannot teach
anything either - it just moves the game around. A mission stops at its first failed step,
because after that every later step is aimed at a screen the harness is not on.

Nothing here is trusted more than in recon. Every step goes through `Recon.take`, so
identity matching and transition recording are unchanged; every committing action goes
through `Recon.permitted`, so the denylist and the modality gate are unchanged. The one
new thing is where candidates come from: a plan may name a control the cursor never
reacted to, which arrives with no verdict, so `Recon.ask_about` buys one. The model
proposing a coordinate does not make it allowed - it makes it a question, asked with the
same brief and answerable with "no".

That is what should unlock the games the explorer cannot touch. Two of the three games
this has been pointed at have screens that ignore the cursor entirely: nothing reacts, so
there are no click candidates and only arrow keys to spend. The map still holds labelled
coordinates for those screens, because the vetting call reports what it can read whether
or not anything moved. A mission can click them.

**What three missions against Tile Tale actually did.** None of them achieved its goal,
and the run is the most useful thing this experiment has produced in a day. All three set
out to reach a Records screen the annotator had labelled but nothing had ever activated.

1. Clicking Records by label was **refused** before it was sent. `ask_about` bought a
   verdict for a control the explorer had never proposed, and the answer was no: the
   vetter, looking at the whole window, judged that the map's coordinate for Records sits
   near QUIT, and would not risk it. The model proposing a coordinate really is a question
   rather than a permission.
2. So the next plan hovered instead, at a coordinate it reasoned out from the screenshot.
   Nothing happened - 0 of 576 cells - and its own `expect` step called it: "the previous
   step changed nothing visible".
3. So the third plan used the keyboard. `down` also did nothing, `enter` did something,
   and the mission stopped on its last step with the harness on the puzzle screen rather
   than on anything new.

Two findings fell out of that, and they are worth more than a green tick. `key:down` moves
the menu selection on this screen when the cursor is elsewhere and does nothing at all
when the cursor is parked on the menu, which is the same one mechanism the sticky-hover
work found from the other side: the mouse owns the selection and the arrow keys are
arguing with it.

And **the map has a wrong edge, which only a mission could have exposed.** It records
`tr020 key:enter -> sc01, a different appearance, 42 cells` for the most consequential key
on the main menu; that key starts the game. What happened is that the settle window closed
while the game was still fading, so the frame that was graded was still mostly the menu.
No sweep can catch this, because a sweep grades each transition once and never asks again -
whereas a mission takes a fresh look one step later, and here the two observations of the
same moment disagreed. Not yet fixed: the fix is in how `Recon.take` grades a settle, and
it needs a re-sweep to show it did not break identity matching.

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

   The cost of that choice shows up on a screen that has controls and no hover feedback.
   Mitosis's new-game screen was swept, reacted nowhere, and therefore had no click
   candidates at all - so the sweep stalled at two screens while the vetting call for that
   same screen was describing a *"glowing teal play button in the bottom-right corner"*.
   Taking the coordinate from the model would fix it and would also collapse the two
   judgements the safety design keeps apart: the call that proposes where to click would be
   the call that clears it.

8. **A pixel threshold filed the settings menu as the main menu, and the model had
   already said otherwise.** Pressing `enter` changed 42 of 576 cells - 0.927
   agreement, above the 0.88 threshold in use - so the settings menu was recorded as
   another appearance of the menu it opened over, while the vetting call for that same
   image came back named `'Settings menu'`. Recalibrating to 0.94 (the measured gap
   between "highlight moved", 11-16 cells, and "different screen", 42) fixes this
   game and only relocates the problem. The durable fix is that the disagreement is
   now the signal: the name splits the screen, and the threshold is left to be
   approximately right.

9. **A hover reaction that fades in is invisible to a probe that reads the frame
   straight after moving the cursor.** The sweep reported *1 reacting of 40* on a menu
   that visibly lights up under the mouse. Measured at 50ms steps: of eight reactive
   points, two moved instantly and five faded in over 400-700ms, so a zero-wait probe
   found exactly the instant ones. The probe now holds 0.5s and then keeps looking while
   the diff is still *growing*, capped at 1s - which finds 7-10 of 40 and costs about
   47s a screen, amortized because a swept screen stays swept across passes.

10. **`wait_stable`'s threshold is a per-cell delta, not a count of changed cells.** The
    first fix for the above passed `threshold=1` meaning "one cell may differ" and got
    "any cell that moved by one unit counts", so the frame was never quiet and all forty
    probes burned their full timeout to conclude nothing. Two numbers in the same
    function, both small integers, one a colour distance and one a cell count.

11. **A screen's animation cannot all be measured before anything on it is selected.**
    `screen.animated` is sampled on first sighting, which is the only moment nothing can
    be credited to an input - but a pulsing glow on a *selected* row does not exist yet
    at that moment, so those cells later read as a new appearance every time they were
    caught at a different point in the pulse. There is now a third mask, measured
    per-appearance and never unioned into the screen's, because "this look shimmers" is
    not the same claim as "this place shimmers".

12. **Per-key caps and the frontier route were enforced through different sets.** The cap
    on pressing one arrow key lives in `screen.tried`, and the route that crosses an
    intra-screen frontier deliberately ignores `tried` (see 5) - so a key retired for
    revealing nothing came straight back as the move to the next appearance, forever. It
    took one budget over *all* navigation on a screen to close, which is the general
    shape of the bug: two rules with a shared subject and no shared counter.

13. **A pass that inherits the last one inherits its mistakes, and no later evidence
    removes them.** On a game whose menu buttons repaint 40-odd cells, run at the 0.94
    threshold measured on a game whose highlight moves 16, the hover sweep filed its own
    first reaction as a *new screen* at 0.938 - and with five passes resuming each other
    that screen is then in the map permanently. The threshold has to be right before
    anything is recorded, and the evidence is already there: a cursor move commits to
    nothing, so a frame it produces is by construction "the same place, changed". Widen
    on it, one direction only. The number to widen on is the frame's distance from the
    screen's *first sighting*, not the size of the reaction just caused - the previous
    highlight is gone and the animation has moved on, so an 18-cell reaction can sit 36
    cells from the representative, and relaxing on the reaction clears the frame by luck.

14. **The midpoint of an admissible range is not a safe threshold.** Recutting
    `screen_match` between "widest same-place move" and "smallest screen change" brackets
    [0.44, 0.90] on a busy game, and the midpoint of that, 0.67, means a frame need only
    reproduce two thirds of a screen to be filed as it. The two errors are not
    comparable: too tight invents a screen per highlight, which is a cluttered map, while
    too loose lets one screen absorb its neighbours and its volatile mask then grows over
    the cells that would have told them apart. The cut is at the tight end of the range.

15. **A screen change of *zero* cells, and it cost a whole game's calibration.** Two
    screens with large volatile masks - a puzzle grid, and the same grid one move on -
    both match almost anything, so which one a frame is filed under comes down to a
    tiebreak the pixels have no say in. An arrow key that moved nothing therefore got
    recorded as travel from one to the other. The mislabel is not the damage: it enters
    the evidence as a screen change of 0 cells, so the recut sees a population of screen
    changes starting *below* every same-place move, concludes no threshold can separate
    them, and hands the whole game over to the model's naming. An identical picture cannot
    be a different place, so classification is now skipped entirely when nothing moved -
    and the recut discards zero-cell screen edges as well, because a resumed map carries
    whatever an earlier pass wrote and one such edge from pass 1 would govern every recut
    after it. With it dropped, Tile Tale's populations still overlap (smallest screen
    change 15 cells, widest same-place move 42) - which is a real finding about a puzzle
    grid rather than an artifact.

16. **Two screens that both match everything swap the frame between them, and a
    `hover` edge is the tell.** Same cause as 15 and a wider symptom: once two places have
    accumulated large volatile masks, nearly every frame qualifies for both, and which one
    takes it is decided by a raw-distance tiebreak that can go either way frame to frame.
    Tile Tale's map filled with `sc05 -> sc04` edges on six different hover points - and a
    cursor move commits to nothing, so it cannot have gone anywhere. The fix is hysteresis:
    among qualifying screens, the one already occupied wins, carried across the step
    boundary as well as within an action. That is only asserting what the threshold was
    asked to decide, and its failure mode is a screen left merged, which the naming still
    splits.

17. **The window that was launched is not always the window the game is in.** A game
    installed by its publisher's own launcher has no Steam directory to search, so it is
    found through its Start-menu shortcut - and what that shortcut starts is the launcher.
    The game arrives in a *separate window of a separate process*, whenever something in
    the launcher gets clicked, which is long after `_launched_window` has returned. The
    failure is silent and total rather than partial: the harness goes on asserting the
    foreground for the window it knows, so it reads and maps the launcher for its whole
    budget while the game it was pointed at sits in front of it, unread. Three signals
    that look obvious were measured and rejected. *Process lineage*: by the time the game
    had a window, its parent PID pointed at a launcher process that had already exited, so
    there was no chain left from our PID to its. *Size*: the game's window here is
    **narrower** than the launcher's (2048x1536 against 2160x1368) and larger only by
    area, so "bigger is the game" would have been a rule that worked on one machine at one
    resolution. *Title*: the launcher's own title changed from `supercell-launcher` to
    `Boom Beach Launcher` seconds after it opened. What does work is the executable's
    image path - readable unelevated via `QueryFullProcessImageNameW` with
    `PROCESS_QUERY_LIMITED_INFORMATION`, where a WMI query returned it blank - and the fact
    that the launcher keeps the games it installs under its own folder. That test is
    directional (the launcher started the game, never the reverse), which is what stops a
    handover from oscillating; the window handed over from is sidelined, never a candidate
    again, and closed at shutdown *after* the game, because a launcher is often the game's
    parent process and closing it first is a kill dressed up as a shutdown.

18. **A `.lnk` stores its target in two halves and one of them looks like an answer.**
    Reading a shortcut's `LocalBasePath` alone returned `C:\Users\` - a directory, not a
    program - and the resolver concluded the game was not installed. The path is that
    field *plus* `CommonPathSuffix`; a shortcut written on a machine with a network view
    of its own drive splits it there. Parsed rather than resolved through the shell
    because the alternative is a COM call or a PowerShell subprocess per shortcut and
    there are around a hundred of them on an ordinary machine.

19. **Half of Steam's game directories were not games.** Twelve of the 23 directories under
    `steamapps/common` on this machine hold no executable at all: Steam leaves the folder
    behind when a game is uninstalled, and two of them (`Steam Controller Configs`,
    `Steamworks Shared`) were never a game. Listing directories is therefore not a listing
    of what is installed, and the difference is not cosmetic - asking for `Dying Light`
    answered "no plausible executable under ..." (a bug report about the resolver) where the
    truth was "that game is not installed" (an answer). The pool now admits a Steam
    directory only if something in it could be started, which is a recursive walk that stops
    at the first hit: the folders that have to be walked to the end are the empty ones.
    Across the 71 programs that survive, all three exact-ish forms of every name resolve to
    that same program, and the only remaining refusals are genuinely ambiguous first words
    (`Git`, `AMD`, `The`), where naming all the candidates is the intended answer.

20. **The model was being asked about buttons it could not see.** Every call carried one
    picture: the whole window, scaled so its longest side is 1400px. On a 3840x2160 client
    that is a 2.7x reduction, so one grid cell - 120x120 real pixels - arrives 43px across,
    and the two cells a menu button lights up by are about 87x43 in the only image the
    model gets. That is why a vetter could describe where the controls were and never say
    what hovering did to one, and why `hover` behaviour in the ontology was almost always
    a hypothesis. The fix is not a bigger picture but a smaller one: a crop is saved at
    native resolution, so the same button arrives 600x480 at a tenth of the pixels. Three
    per action - before, mid-press, after - plus a rest/hover pair per reacting control and
    three frames of whatever a screen moves on its own. Two things had to be measured
    before they could be aimed, and both are why this is cheap: a control's extent is the
    cells that reacted when the cursor arrived, and a keypress's extent is the cells it
    moved *last* time, which is why the first press of a key has an after picture and no
    before. Writing a PNG is a Python loop over every pixel (43ms for 600x480, 172ms for a
    full window), so the shutter that fires with the mouse button still down grabs pixels
    and nothing else - the file is written after the release, or the 80ms hold would become
    130ms and the harness would be measuring a click nobody else sends.

    The first real game it ran against then produced a pair of pixel-identical pictures
    labelled `at rest` and `with the cursor on it`, which is a statement that the cursor
    does nothing - the opposite of what the sweep had just measured. The cursor there does
    not light a button, it *moves the selection*, and the selection stays where the cursor
    left it, so there is no resting state to photograph while the game is in that state.
    Detected by comparing the two files byte for byte (sound only because both came out of
    one encoder at one size from one box), and kept rather than thrown away: which points
    behave this way is the fact that the mouse and the arrow keys are driving one mechanism.
    Such a point gets one close-up, said to be one, and no pair.

21. **Capture reads the screen DC clipped to the client rect** (inherited from
   `probe.py`, and worth restating): an occluded window returns whatever is on top of
   it as a clean, plausible frame of the wrong application. There is no error. That is
   why foreground is asserted *before* a frame is trusted rather than after something
   downstream looks wrong.

22. **A tool schema is a request, not a guarantee, and the validator has to survive being
    wrong about that.** Two ways this bit in one run of `describe.py`. A property declared
    as `{"type": "string"}` with no description got filled in from context: the annotator
    named every screen after the id the evidence referred to it by, `sc01`, overwriting the
    readable name the vetting call had already got right. A property whose meaning matters
    has to say what it means, even when its type is obvious. Then one call returned a bare
    string where an element object belongs, and `validate` - the function that exists to
    reject exactly that - died inside itself on `'str' object has no attribute 'get'`,
    taking the three screens after it down with it. A validator that assumes the shape it
    is checking is not one; every access on a payload is on data an unrelated process
    chose. Both now do the same thing with a malformed payload that the evidence check
    already did with a fabricated transition id: hand it back and let the retry fix it.

23. **The worst bug in this experiment so far: it drove somebody's editor.** `py sweep.py
    --game Mitosis` attached to a Visual Studio Code window and spent a minute hovering,
    clicking and pressing keys in it. The game was not running; the remembered title
    `Mitosis` was matched as a substring against every visible window, and the editor
    happened to be showing a file called `mitosis-last-run.log`. Two independent paths had
    the same hole - `running_window`, which attaches at the start, and `_belongs`, which
    adopts a window mid-session when a launcher hands over - and both were phrased as *the
    game's name appears in this title*, which is true of every window naming a file, a
    folder or a branch after the game.

    Two things are worth keeping about how it failed. **None of the three safety layers
    could have caught it**: the coordinate denylist, the modality gate and the vetting call
    all answer "is this action allowed on this screen", and not one of them asks whether the
    screen belongs to the game. The vetting call actually *read* the screen correctly - it
    named it `VS Code Editor - game-ontology project`, reported the selected item as
    `mitosis-last-run.log`, and then cleared 14 of 14 actions as safe, because nothing in
    its brief said that "this is not a game" is an answer it is allowed to give. It says so
    now. **And the check that fixes it was already in the file**: `_belongs` had the right
    relation - the window's process is the executable that would have been launched, or
    lives under its folder - it just let a title match stand as an alternative to it rather
    than as a fallback for when the process image cannot be read at all. A weak piece of
    evidence in the same `or` as a strong one is not a fallback; it is the rule.

    **And then a target arrived for which the strong relation cannot exist, so the weak one
    was the rule again.** A Google Play Games title has no executable at all - its shortcut
    stores a blank TargetPath, and the client cannot be started from a path - so `Target.exe`
    is empty by construction and all three process relations are unreachable. Every window
    naming the game was adoptable on the title alone, permanently, and one was: a VS Code
    window titled `Clash Royale - live client exploration (...report.html)`. The fix cannot
    be "make the fallback stricter", because there is nothing to fall back *from*.
    `Target.owner_image` names the process that draws the game - here `crosvm.exe` under
    `C:\Program Files\Google\Play Games` - and is checked *before* the four relations rather
    than after, so it outranks any title resemblance instead of competing with it.
    `Target.disowns` fails closed: a window whose process image cannot be read is refused,
    because the cost of a wrong refusal is a handover that does not happen and the cost of a
    wrong acceptance is input sent into another program. Verified firing in production - it
    declined that editor window on every invocation of a live session.

24. **Nothing checked that a coordinate was inside the window.** The annotator wrote
    `at: [697, 190]` for a control - pixels of the screenshot it was shown, where fractions
    belong - and that value sat in a committed map, describing a real button, waiting for
    something to aim at it. `Controller.point` would have computed `left + width * 697`,
    `mouse_move_to` would have sent the cursor thousands of pixels below the game, Windows
    would have clamped it to the edge of the desktop, and the click would have landed on
    whatever was sitting there. That is the editor bug again with a different first move:
    input leaving the game, and no layer noticing, because all three safety layers ask
    whether an *action* is allowed and none of them asks whether a *coordinate* is real.
    Fixed in three places on purpose - `describe.py` refuses to write one, `mission.py`
    refuses to aim at one an older map already holds, and `point` refuses to convert one,
    which is the guarantee under the other two and holds for a caller nobody has written
    yet. One `is_fraction` shared between them, from the file that defines the coordinate
    system, because three copies of a rule is three chances for one to be laxer than the
    one that matters.

    The same pass hardened the rest of that validator, for the reason in item 22: every
    field the code reads with `[...]` rather than `.get` is now checked before the call is
    accepted, so a payload missing one costs a retry naming the field instead of a
    `KeyError` that ends the run and takes the screens after it down.

25. **A model wrote an arrow and it killed a live run.** `UnicodeEncodeError: 'charmap'
    codec can't encode character '→'` - between planning mission 2 and flying it, with
    the game already launched. Windows hands a Python process a cp1252 stdout, `print`
    raises rather than dropping the character, and every log line in this experiment can
    contain a model's prose: why a mission was planned, why an action was refused, what it
    called a control. The fix is `readable_output()`, called first in every entry point,
    which is process-wide rather than a guard inside `log` because `log` is not the only
    thing that prints model text - `engine/client.py` prints the validation errors it feeds
    back on a retry, and those quote the payload. The general lesson is the cheap one: a
    string that came from a model is untrusted input all the way to the console, and no
    sentence it writes should be able to end a session that has a game open.

26. **The harness could send three of the five things a mouse does.** Hover, click, and a
    key - so a game that pans a map, scrolls a list, or drags a unit somewhere was
    unreachable by construction, and `shift+click` was not a sentence a plan could write.
    The missing part was never the plumbing (`SendInput` with `MOUSEEVENTF_WHEEL` is four
    lines) but four things above it.

    **A denylist that is a point test cannot vet a drag.** Every other input touches
    exactly where it was aimed; a drag holds the button down along a line, and the two ends
    being clear is no statement at all about what is between them. So `Target.forbids_path`
    clips the segment against each forbidden box exactly, rather than sampling points along
    it - with sampling, the step size silently becomes the real safety limit, and the box
    you drove a drag straight through is the one that was smaller than the step.

    **`Action.id` is on-disk identity, so a new field cannot change an old id.** The ids
    key `screen.tried`, the vetting verdicts, the crop-box table and the image filenames of
    every map already saved. Two kinds and five fields were added and every pre-existing id
    is still byte-identical, because the new parts only appear when they are not the
    default: `click:0.500,0.600` is unchanged and `click:ctrl+right:0.500,0.600` is new. One
    thing did have to be renamed - the saved verdicts were called `click_verdicts` and
    filtered on the `click:` prefix, which would have silently dropped every drag and scroll
    verdict on the way to disk, so they are `mouse_verdicts` and the reader accepts both
    names. `SCHEMA` is deliberately *not* bumped: an old checkout reading a new map fails
    loudly the first time it routes through a drag edge, while bumping would refuse every
    map on disk today - a certain loss, to insure against a loud failure in a checkout
    nobody is running.

    **The wheel and the drag are blind, and hover is not.** Click candidates come from a
    hover sweep, which is evidence; nothing tells you a list scrolls until the wheel has
    already turned. A screen therefore gets one wheel each way and one drag, aimed at the
    middle of the window and nothing else, and the eight escalated probes - the wheel over
    every hotspot, the other three drag directions - are spent only where those landed.
    Without the gate a hover-inert screen carries twenty untried candidates, each wanting a
    verdict and a settle, and the frontier search keeps travelling back to it because they
    are all still untried.

    **And then the measurement of "did it land" was polluted by the aiming.** The cursor has
    to travel to the target before a wheel can be sent, and on a game whose controls light
    under the hand that journey repaints part of the window. On the synthetic menu a wheel
    probe at the middle came back with 40 changed cells: every one of them a button lighting
    up and going dark, not one of them the wheel. The before frame is now read *after* the
    journey. A screen that animates was the same failure from the other side - its own
    shimmer was enough to leave the before frame matching no known appearance, which was
    then classified as a variant change of *zero cells* and taken as proof that the screen
    drags. So the evidence is the changed cells minus the screen's animation mask, and not
    the classification.

    The one input that fails invisibly is a held modifier: it does not error, it changes the
    meaning of every input for the rest of the session. `holding` releases in reverse order
    in a `finally`, and attempts every release even if an earlier one throws.

    **The escalation then did not fire once, and the map said so plainly enough that
    nobody read it.** Five passes at Tile Tale, 27 minutes, and the wheel turned out to do
    something after all - 1 to 3 cells on each of its settings menus, against a prediction
    that a keyboard game would ignore it. But of the 19 blind probes recorded against one
    of those screens only 3 were ever sent. The vetting call carries the screen's
    candidates *once*, on the first appearance (`vet`, `if first:`), and the escalated
    probes are minted afterwards by definition - the gate that mints them opens on evidence
    the first call predates. So they arrived with no verdict, and a missing verdict is not
    a temporary refusal: `prune_blocked` retires everything except `UNVETTED` permanently,
    and `tried` is on the map, so all 16 were retired unsent forever. `blocked_actions` in
    that map contains twenty rows reading `no verdict for this action`, which is the bug
    stated in full, written down at the time and skimmed past twice.

    The escalated probes now buy their own verdict at the moment the gate opens, through
    the same `ask_about` a mission uses for a control the cursor never reacted to. What the
    call will not rule on is retired with the reason spelled out rather than left to be
    re-offered every step - worded so it cannot be mistaken for the model's own judgement -
    and a call that fails outright retires nothing, so a later pass asks again.

    The selftest had reported this feature working. It printed `screen.tried` as "blind
    actions tried", and retiring an action for good is done by *putting its id in
    `screen.tried`* - so a probe that was refused and never sent was indistinguishable
    from one that was sent and filmed. It now counts the transitions, which is the only
    record that a probe actually happened, and prints what was retired without being sent
    as its own line. Five of the fake game's eight escalated probes had been dying there in
    silence the whole time.

    What is verified against a real game, from that sweep: the aiming no longer pollutes
    the measurement (every probe that found nothing recorded exactly 0 changed cells, where
    before the fix it was ~40), the path denylist and the modality gate both hold, and the
    refusals are legible - a drag was refused on five of nine screens, one of them because
    *"a horizontal drag starting near the centre (around MUSIC: 20% or SCREEN: FULLSCREEN)
    could adjust a slider value"*. The animation half of the evidence test was not
    exercised: no Tile Tale screen animates at all. And `drag_does_something` is cruder
    than it sounds - the screen that set it did so with a drag that hit a control and left
    for the main menu, which is not the panning it is meant to detect.

27. **A health check closed the client it was checking, and then reported it as crashed.**
    `_restart` closes the game and *then* launches it again, and the check for "can this
    even be launched" lived in the launching half. For a target with no executable that is
    the order that loses: WM_CLOSE goes to the game, taskkill follows if it does not take,
    and only afterwards does `_launch` raise `cannot find an executable`. A window that went
    funny is recoverable; a game shut with nothing able to reopen it is not.

    The chain was entirely made of parts doing their documented jobs. `wait_live.py` - whose
    whole purpose is to watch without touching - called `fingerprint`, which calls
    `grab(verify=True)`, which found the window was not the foreground, because Play Games
    parks its window *hidden* (`IsWindowVisible 0` with `IsIconic 0`, which is neither of the
    two states `ensure_readable` is written around). `ensure_readable` went looking for a fix
    and the fix was a relaunch. **A verified grab is a driving call**, and that is not
    visible at the call site: nothing about `fingerprint(controller)` suggests it may close
    the game. `recon.fingerprint` now takes `verify=False`, which is what an observer passes,
    and the guard in `_restart` refuses before touching anything - because refusing loudly
    *after* `close()` is no better than not refusing.

    Worth the note that the harness must never reach for this game's launcher, and that rule
    is what made the failure survivable: `Target.exe` being empty is why `_launch` raised
    instead of starting a second client over the first. A safety property held by accident is
    still worth converting into one held on purpose - `test_no_restart_without_exe.py`, 8
    tests, 5 of which fail with the guard removed.

    And the reporting failure is its own lesson. Asked what happened, the first answer was
    "the game opened and closed again", which read as a crash. The harness had done it.

28. **"Settled" and "alive" were one number, and the two have diverged.** `_wait_settled`
    asks a single question of the whole window - did more than `(1 - screen_match) * 2304`
    cells move - and its docstring claimed *"a startup transient crosses it by construction,
    idle animation does not"*. A live, perfectly readable Clash Royale lobby falsified that
    when the account progressed and the lobby gained an animated offer banner: idle animation
    moved **132 of 2304** cells against a tolerance of 60, and the run died with `window never
    rendered a settled frame`. Three days earlier the same lobby had held a steady 1 of 576
    for ninety seconds. This is lesson 3 and lesson 15's hole biting in the *other* direction:
    tight enough to catch a freeze is now too tight to admit a live screen.

    The premise is that a screen is either moving or it is not, and games are not like that.
    `experiments/android-bot/sweep_stability.py` measures the question that is actually
    useful - per cell, how many of N consecutive frame pairs it changed in. On that lobby,
    16 frames a second apart: **97.3% of cells hold still**, the top bar and the trophy band
    read 0.0%, and every moving cell belongs to a named piece of decoration - a glowing icon,
    two pulsing chest thumbnails, a shine crossing the button plate, the arena's flag tips.

    So a per-screen stable mask works, with a condition that was not obvious and that only a
    **held-out** test exposes. A mask fitted on every pair scores zero on every pair, which
    proves nothing; scored on pairs it has never seen, a mask learned from 8 frames reads at
    worst 10 of 2304 where the whole window reads 33 - but the same mask learned from **3**
    frames reads 49 against a tolerance of 59. The animation cycles on something longer than
    three seconds, so a short fit has not met most of it. `Screen.animated` already learns a
    mask this way across repeat visits and is the right shape; a readiness gate meeting a
    screen for the first time has not had a cycle to learn from, which argues for two stages
    rather than a looser threshold. **Not yet changed** - the measurement is committed, the
    gate is not.

    Two smaller traps found underneath it. Frames captured at *different resolutions* cannot
    be compared: 787x1400 and 393x700 both reduced to 64 columns flicker every high-contrast
    edge, and that alone inflated the same measurement from 24 cells to 84. And a frame can
    differ by **brightness alone** - a lobby behind an overlay that had not finished fading
    read 13% darker and moved 1045 of 2304 cells, which a downstream check duly reported as
    an unknown screen when it was the right screen under a veil.

29. **A scrollable screen was a new screen at every offset, and one feed became a dozen.**
    The wheel and drag from item 26 could *reach* a scrollable list, but identity had no
    notion of one: a scroll changes most of the frame, so `observe` filed each offset as a
    fresh screen and a news feed split into eight look-alikes named `sc10`..`sc17` - the
    same over-split an animated background causes (item 15/16), except unbounded, since a
    surface can be arbitrarily tall. It is also the exact shape the model kept re-describing
    with slightly different words, which the split ceiling could not catch because the
    frames genuinely differ.

    `scroll_shift` recognises the shape a scroll leaves *before* `observe` mints a screen:
    the content is the previous frame translated along one axis, under fixed chrome, with
    new content at the leading edge. It is done on **row and column profiles, not cells**,
    and that is a measured choice - a real scroll moves a fractional number of the 18 grid
    rows and the HALFTONE downsample then blends each cell across two source rows, so at the
    *correct* shift under 10% of cells reproduce. Averaging a whole grid line together
    smooths through that blur and through a moving background: on a live feed the genuine
    scroll steps all aligned at one shift with a mean per-byte line distance of 29-49, where
    navigations between distinct screens sat at 52-90 and could not beat 0.83x the no-shift
    distance. A `scrolled` transition keeps `after_screen == the source screen`, so it is a
    self-loop and **cannot merge two distinct screens** - the worst it can do is record a
    scroll that was not one, on the screen you were already on. A live pass confirmed it: 9
    feed scrolls recorded as self-loops with a consistent magnitude, versus 0 before.

    The surface is then one node, so it can be shown as one page. `stitch.py` composes the
    saved per-offset frames into a panorama - the fixed chrome once, then each frame's
    newly-revealed strip - finding the seam by the same profile correlation and **stopping
    at a bad seam rather than splicing** a near-duplicate. It is offline-testable against
    sliced synthetic frames and needs Pillow only for the picture; the `surface` facts and
    the raw frames are the record either way. Two limits are deliberate: the offset search
    caps at ~80% of the viewport, so a fling that scrolls almost a whole page off-screen
    leaves nothing to align and the chain stops (a truncated page beats a fabricated one),
    and frames are kept for the **first axis scrolled only**, since a page stitches along
    one axis and mixing them would break the seam chain. The live *capture* of those frames
    is gated behind item 28: the feed screens that scroll are the animated ones the
    readiness gate cannot settle, so a clean end-to-end capture is still pending that fix.

## What is reused, and what standalone means

`probe.py` is imported for capture, input, PNG writing and window finding - it was
already fully general, and it stayed that way through one addition: the wheel, and the
three modifier keys, which are input primitives no game knowledge went into. Everything
above them - what a drag is made of, where it may go, whether it is worth trying - is
here. `bench_shuffle.py` and `game_session.py`'s constants are
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
