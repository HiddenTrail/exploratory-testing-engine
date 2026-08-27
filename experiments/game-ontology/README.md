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
py controller.py --game Mitosis            # smoke test: find it, own a window, read it, close it
py selftest.py                             # no game at all: check the close-ups against a fake one
```

`selftest.py` is the one check that needs neither a game nor a model. It drives the real
session against a synthetic menu built to have the behaviours the imaging code reasons
about, and prints what was filmed, where it was aimed and whether each before/after pair
is actually two pictures - which a real game cannot tell you, because it has no second
opinion about what its own buttons look like. It takes about a second and a half. It is
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
