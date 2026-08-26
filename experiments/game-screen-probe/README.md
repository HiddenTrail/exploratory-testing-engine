# Game Screen Probe

The smallest useful perceive/act probe against a live **native** game window:
deliver one synthetic input, and print whenever anything moves on the game's
screen. No engine, no adapter, no claims, no LLM.

It has since grown far enough to *play* the game - read the board, choose a
move, place a tile, score a match, take a level-up reward - which is a stronger
result than the original question asked for.

Exists because Tile Tale is a GameMaker game (`tile_tale.exe` + `data.win`, a
native DirectX window), so Playwright and every other WebDriver-shaped tool are
structurally out - there's no DOM and no accessibility tree to query, only
pixels. Before designing any ontology or adapter wiring around a game SUT, two
questions were worth answering for near-zero cost: **can we read pixels out of
that window**, and **does synthetic input reach it**. Both are now yes.

Stdlib only - `ctypes` over `user32`/`gdi32`, plus `zlib`/`struct` for the PNG
writer. Nothing to install.

## Usage

```bash
# Look at what's on screen right now
py experiments/game-screen-probe/probe.py --restore --save frame.png

# Watch for motion, touching nothing
py experiments/game-screen-probe/probe.py --restore --watch 6

# Touch, then watch what it did (--map for a per-frame motion map)
py experiments/game-screen-probe/probe.py --restore --touch key --key up --watch 4 --map
py experiments/game-screen-probe/probe.py --restore --touch move --at 0.3,0.35 --watch 4
py experiments/game-screen-probe/probe.py --restore --touch click --at 0.5,0.5 --watch 4
```

`--title` targets any other window; it matches a title substring.

### Scripted runs

Every separate shell invocation costs a permission prompt, and answering one
takes focus off a fullscreen-exclusive game, which minimizes it and invalidates
the next capture. So multi-step work does not belong in a shell loop over
`probe.py` - it belongs in one process:

```bash
# Replay a whole action sequence, capturing as it goes
py experiments/game-screen-probe/play.py snap:00 click:0.3398,0.3361 wait:2 \
    crop:board,0.2415,0.3939,0.1155,0.2033@600 snap:01

# Get the game running and shuffle its board, escalating through 13 input styles
py experiments/game-screen-probe/shuffle_run.py

# Prove a shuffle is board-only, by fingerprinting three regions separately
py experiments/game-screen-probe/shuffle_verify.py
```

`play.py` is the one to reach for. Actions: `snap:NAME[@WxH]`,
`crop:NAME,FX,FY,FW,FH[@LONGEST]`, `click:FX,FY`, `move:FX,FY`, `key:NAME`,
`char:C`, `wait:S`, `watch:S`, `restore`. All coordinates are fractions of the
client area, so they survive a resolution change.

`crop` exists because a 3840x2160 client downsampled to 1280x720 shrinks a board
tile to ~50px - enough to see that a tile changed, not always enough to tell
*which kind* it changed to, and the whole game turns on that distinction.

## What it does

- **Capture** reads the *screen* DC clipped to the window's client rect.
  BitBlt/PrintWindow against a GPU-composited DirectX surface commonly returns
  solid black; compositor output does not. Cost: the window must be visible, so
  the watch loop reports how many frames were taken while the game was not
  foreground.
- **Downsampling** happens inside GDI via `StretchBlt` with `HALFTONE`, so each
  thumbnail pixel is an average of its source block. Frame diffing is then a few
  thousand pure-Python byte comparisons instead of megabytes, and the grid
  doubles as a coarse motion map - *where* it moved, not just whether it did.
- **Keyboard input** is `SendInput` with **scancodes**, not virtual keys: game
  runtimes routinely read the keyboard at a level where VK-only synthetic events
  are invisible. Arrow and navigation keys additionally get
  `KEYEVENTF_EXTENDEDKEY`, or they arrive as their numpad twins.
- **Mouse input** is `SendInput` with an absolute `MOUSEEVENTF_MOVE`, then a
  *held* press. Both halves of that matter, and both are covered under "things
  that bit" below.

## Verified against Tile Tale

- Window resolves, client area is **3840x2160 fullscreen** at (0, 0).
- Capture returns true colour (~250 distinct values per channel).
- Idle options menu is **pixel-static**: 0 of 31 frames showed motion at
  `--threshold 6`, so there are no false positives to calibrate away.
- One `Up` keypress moved the menu highlight from `DARK MODE: OFF` to
  `SCREEN: FULLSCREEN`; the probe reported motion in 2 frames confined to the
  menu rows, and a saved PNG confirmed the highlight moved. Round-tripped with
  `Down`.
- Menus are keyboard-driven; a bare cursor move gets no reaction on them. The
  **game screen is mouse-driven**, and clicks land there reliably once delivered
  correctly - the first strategy in a 13-way escalation sweep won, so the earlier
  failures were the delivery code, never insufficient force.
- Full play loop exercised end to end: enter a new game, read the board, place
  tiles through the edge arrows, score four 2x2 matches (0 -> 95 points), trigger
  **Level up! - level 2**, and pick a reward from the four-way choice screen.

## What the game turned out to be

Worth writing down, because none of it is guessable from pixels alone and every
line of it was paid for in wrong moves:

- The board is **not clickable cells**. Twelve **edge arrows**, 3 per side, push
  the staged tile into a row or column: it inserts at the near edge, shifts the
  whole line away, and the far tile drops off the board. So a 2x2 is built by
  pushing the same tile type twice into *adjacent lines from the same side* - you
  cannot target a cell.
- Matching a 2x2 of one type scores, **clears the quad to dirt**, and refills the
  deck. Matches chain, with a multiplier (`+10 x2`, `x3`).
- Hovering an arrow stages the tile beside it and turns it blue. The selection
  **persists**, so any subsequent click *anywhere* confirms it and places a tile.
  There is no neutral click on the game screen - a click meant only to dismiss a
  tutorial message also spends a tile.
- Tiles arrive from a visible vertical **queue** on the right; the tile staged
  beside the board is the next one out and the queue is the lookahead.
- Level thresholds: 50 points for level 2, 140 for level 3.
- Shuffling has a **cooldown**. Clicking faster than it does not shuffle faster;
  the extra clicks are simply discarded, which is easy to mistake for a
  successful speed-up because a click that does nothing returns immediately.

### The state machine, as measured

```
main menu  --enter on NEW GAME-->  board
board      --deck reaches 0---->   CHALLENGES
CHALLENGES --any mouse click--->   main menu (NEW GAME pre-highlighted)
```

Corrections to earlier readings of this, each of which was wrong in a way that
looked right:

- **ESC does not leave the board.** It only advances the tutorial. A menu that
  appeared right after an ESC had already been there before the keypress.
- Running out of tiles does not "restart on enter". It raises **CHALLENGES**, the
  game-over screen: score, best score, and 14 locked challenges. `enter`, `esc`
  and `space` are all ignored there - **only a mouse click** dismisses it, and it
  lands on the main menu with NEW GAME already highlighted.
- So there *is* a reset primitive after all, without ever touching the exit icon:
  spend the remaining tiles, click once, press enter. That is what
  `bench_shuffle.py` uses to run itself repeatedly from any starting state.
- The menu **wraps**, and ESC on the menu parks the highlight on **QUIT**. So
  "press up a few times to reach the top" is not safe; the highlighted row has to
  be read off the pixels before enter is pressed.

Two hard rules for anything driving this game:

- **Never click the exit icon** at fraction `(0.9063, 0.9097)`. It quits the game
  outright, and every measurement after that reads a dead window - which looks
  exactly like "the input did nothing" rather than "there is nothing there". A
  whole 10-strategy sweep once ran against a closed game and reported clean
  zeros. No script here holds that coordinate, and `assert_alive` in
  `shuffle_run.py` fails loudly on a flat frame rather than measuring against
  one.
- **Never activate `RESET TUTORIAL`** in the settings menu.

## Things that bit, worth not re-learning

1. `CreateCompatibleBitmap` must be called on the **screen** DC, not on the
   freshly created memory DC. A new compatible DC holds a 1x1 *monochrome*
   default bitmap, so asking it for a compatible bitmap silently yields 1 bpp -
   every captured pixel comes back pure black or pure white and frame diffs
   collapse to two values.
2. `ctypes` defaults unknown return types to C `int`, which **truncates** the
   64-bit `HDC`/`HBITMAP` handles these APIs return. Explicit `restype`/
   `argtypes` are mandatory, not tidiness.
3. The baseline frame must be captured **before** the input is delivered.
   Touching first and then grabbing the baseline hides any reaction fast enough
   to finish in between - it is already in the baseline, diffs to zero, and
   reads as "the game ignored us". This produced one false conclusion before it
   was caught.
4. **The game self-minimizes on focus loss** (fullscreen exclusive). When the
   probe process exits and focus moves elsewhere, Tile Tale minimizes and its
   client rect goes to 0x0, so the next run can't capture anything. `--restore`
   polls `ShowWindow` + `SetForegroundWindow` until the client rect goes
   non-zero, because a background console process is subject to Windows'
   foreground lock and may have `SetForegroundWindow` refused outright.
5. **`SetCursorPos` injects nothing into the input stream.** It relocates the
   cursor, so a screenshot and `GetCursorPos` both agree it worked - but a game
   that tracks the mouse from move *events* rather than polling every frame never
   learns the cursor arrived. The press that follows is hit-tested against
   wherever the game still believes the pointer is, which is usually nothing. An
   absolute `MOUSEEVENTF_MOVE` through `SendInput` is indistinguishable from a
   real mouse being dragged there. Its coordinates normalize to 0..65535 across
   the **virtual** desktop, not the primary monitor, or a multi-monitor setup
   lands the cursor at a fraction of the intended position.
6. **A click needs a real hold.** Sending the button-down and button-up in one
   `SendInput` batch puts both in the same input frame, so a runtime sampling the
   mouse once per frame sees the button already released by the time it looks and
   registers no click at all. 80ms of hold is enough. A hover delay before
   pressing is also needed, so the game hit-tests the new cursor position first.
7. **Bundled state changes read as a single cause.** On the tutorial's first
   beat, one click anywhere advances the tutorial text, drops the deck counter,
   stages a tile *and* rearranges the board. Fingerprinted as one screen that is
   indistinguishable from a shuffle, and it got reported as a successful shuffle
   twice before `shuffle_verify.py` started fingerprinting the board, the counter
   and the tutorial box **separately**. A real shuffle is board-only.
8. **A mean colour hides a thin foreground.** The deck counter is a few dark
   digit pixels on a large cream field, so 5 -> 0 barely moves the region's mean
   and the metric reported "unchanged" while a screenshot plainly showed the
   change. Anything small against a big flat background needs a different
   statistic than the mean.
9. **Not every moving sprite is a tile.** A pink animal wanders to a different
   cell every turn, drawn over whatever tile is beneath it. Three consecutive
   board reads disagreed with each other and with the push rules before the cause
   was clear. Read the tile under the overlay, not the cell as drawn.

## Implication for the ontology/adapter direction

Point 4 is the real constraint, not capture or input. Fullscreen exclusive means
an automated run **cannot share the desktop** - the game must hold focus for
every captured frame, so nothing else can be on screen while a run is in
progress. Two ways out, both untried:

- Set `SCREEN` to windowed in the game's own options menu (that setting is right
  there on this screen), which makes capture cooperative.
- Skip pixels entirely and go the injected-control-channel route, which is
  cheaper than driving the game's own menus for a reset.

State can only be moved through the game's own menus, so anything built on this
needs to record *which* state an observation came from before results can be
compared across runs. There *is* a usable reset (drain the deck, click,
enter) - see the state machine above - but it costs a whole game to get one.

## Speed: `bench_shuffle.py`

One measured task - new game, shuffle until the deck counter hits 0, stop -
re-run under six configurations, each stage removing one source of cost. Run
`py experiments/game-screen-probe/bench_shuffle.py --stage N --cycles 3 --verify`.

| # | Change | Cycle s | s / landed | Landed | Captures | KiB |
|---|---|---|---|---|---|---|
| 1 | baseline (the habits the earlier scripts had) | 26.19 | 3.417 | 100% | 465 | 1325 |
| 2 | adaptive settle instead of a fixed 2.2s sleep | 24.04 | 2.773 | 79% | 536 | 1915 |
| 3 | restore once per cycle, cache the client rect | 16.65 | 2.172 | 68% | 663 | 2018 |
| 4 | closed loop: poll the counter, not the board | 9.21 | 1.152 | 73% | 546 | 1973 |
| 5 | drop the 25-region fingerprint for one 16x16 read | 7.47 | 0.934 | 67% | 439 | 369 |
| 6 | park the cursor, drop the pre-click hover | 6.15 | 0.683 | 64% | 324 | 294 |

4.3x on wall clock, 5.0x per shuffle that actually landed, 4.5x fewer pixel bytes
read per cycle (6.9x down from the peak at stage 3).

Two things about that table are the actual lesson:

- **`--verify` exists because a speed-up was fake.** Trimming the click hold from
  80ms to 30ms improved seconds-per-click and made the run look faster, but the
  landing rate fell to 44%: a click the game discards animates nothing, so the
  settle poll returns instantly and a wasted iteration reads as a cheap success.
  Any per-attempt metric rewards not doing the work. So the benchmark counts
  clicks that **moved the counter** and reports seconds per landed shuffle, which
  cannot be gamed that way.
- **The stage order is not the order these were tried in.** Shrinking the reads
  (5) and parking the cursor (6) were measured first and both came out *slower*
  end to end, because of the shuffle cooldown: clicking sooner without knowing the
  game is ready just spends clicks into the cooldown, and cheap reads buy latency
  the loop then throws away waiting. Closing the loop on the counter first turns
  both back into wins. Ordering the file by the causal dependency rather than by
  the order of discovery is what makes every step monotone.

Where the remaining time goes: 36% of clicks still land during the cooldown. The
floor is the game's, not the harness's - the next win is timing the cooldown
rather than probing for it.
