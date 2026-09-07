# android-bot

Clash Royale, driven live inside the Google Play Games emulator on Windows, on top of the
`game-ontology` harness next door. Real account, real client, no test build.

```bash
python wait_live.py 60          # is the client up and rendering?
python run_recon.py --minutes 5 --screen-match 0.93
python battle.py --allow-battle --matches 1
```

Sibling to `game-ontology`, which asks whether a harness can map *any* game from nothing.
This one asks the question that only shows up on a real target: what breaks when the game
is not a Windows executable, has no accessibility tree, cannot be launched, and belongs to
somebody's actual account.

It is also **live dependency of the engine**, not an archived prototype:
`engine/adapters/clash_royale/session.py` puts this directory and `game-ontology` on
`sys.path` and imports them at call time, to drive the engine's first non-HTTP SUT. That
import is a knowing debt - its own comment says so - taken because the controller here is
the part that has been hardened against a real client. Breaking a name in this directory can
break that adapter, and nothing in CI will tell you.

## What makes this target awkward

**There is no adb.** The Play Games *consumer* build ships no adb binaries at all, so the
whole Android tooling world - `uiautomator`, view dumps, `input tap` - is unavailable. What
is left is a Win32 window and its pixels. Every element position in this directory is a
fraction of the window measured off a frame, because there is nothing to ask.

**There is no executable.** A Play Games shortcut has a blank TargetPath; the client starts
through a shell URI. So `controller.find_game` reports the game as not installed and the
whole discovery path every earlier target used is gone. `attach.py` replaces it with two
checks that must both hold - exactly one unowned visible window carries the name, and its
process is `crosvm.exe` inside the Play Games install - and then leaves `Target.exe`
**empty on purpose**. Read `attach.py`'s docstring before changing that line; it is
load-bearing in a way that is not obvious.

Consequences of the empty `exe`, all deliberate:

- the harness cannot launch or relaunch the game, so **the client must already be open**;
- **opening it is a person's job.** Nothing here may reach for the launcher;
- `_belongs` has no process relation to test, so window identity rests entirely on
  `Target.owner_image`. Without it a VS Code window titled `Clash Royale - ...report.html`
  is adoptable, and an adopted window is one this harness sends drags into. It happened.

## The safety rules, and which layer holds each one

These are decisions a person made, not inferences:

| rule | held by |
|---|---|
| **money is untouchable** - gems, gold, shop, chests | 6 coordinate boxes in `game-ontology/target.py` **and** the model vetting call |
| **the Battle button stays blocked** - it is a live ladder match | coordinate box at `(0.32, 0.72, 0.37, 0.12)` |
| **Training Camp is the only authorised battle** | `battle.py` refuses without `--allow-battle` |
| **nothing may open the launcher** | `Target.exe` empty, and `_restart` refusing before it acts |

The two layers are not redundant, and the live pass that proved it is worth knowing about.
The vetting call refused a mystery-chest `Claim` at `(0.730, 0.392)` - *"claiming a reward
may consume progress currency or be irreversible"* - and **no coordinate box covers that
control**, because it did not exist when the boxes were drawn. Conversely a box is pure
geometry and screen-blind: the lobby's "Catch Up" offer sits at y 0.60-0.71 and Training
Camp's confirm button is at `(0.681, 0.578)`, about 0.02 clear, so boxing the offer would
block the one battle that is allowed. **Coordinates cannot scale with a game that changes;
descriptions can.** See also `coordinate-denylists-dont-block-destinations`: a swipe once
walked *around* a Shop-tab box and landed on a one-tap purchase, because a denylist filters
where a gesture starts, not where it ends.

## Entry points

| | |
|---|---|
| `wait_live.py [seconds]` | is the client up and rendering? Gates on the window existing and *prints* movement as evidence; `--moving` restores the strict movement bar. Never touches the game - see below. |
| `run_recon.py` | a `game-ontology` recon pass through the emulator: explore, classify screens, write a map and a report |
| `drive.py` | one tap at a time, a person deciding each one |
| `battle.py --allow-battle` | Training Camp matches back to back, measuring how well each went |
| `probe_window.py` | read-only: is this window something the harness could drive at all? |
| `../../clash-royale-kit/cr.py` | all of the above wrapped for somebody who is not going to read this file: checks the machine, runs one recon pass, writes a wiki from it. No agent, no code editing |

Reading the board, for `battle.py` and the `clash_royale` adapter: `arena.py` (where the
fighting is), `hand.py` (what is in hand and whether it can be paid for), `towers.py` (which
princess towers still stand), `plan.py` (which card, where, and when not to play at all),
`touch.py` (a recon session restricted to what a finger can do), `cards.py` (generated -
regenerate with `reference.py`).

Measurement and eyeballing: `sweep_stability.py` (which cells of a screen hold still),
`denylist_preview.py` and `preview_elements.py` (draw the safety layers over a real frame),
`arena_preview.py`, `check_vetter.py` (one live vetting call against a PNG on disk).

## Two things that cost the most to learn

**A verified frame grab is a driving call.** `wait_live.py`, whose entire job is to watch
without touching, closed the client - and then reported it as having crashed. The chain:
`fingerprint` calls `grab(verify=True)`, which found the window was not the foreground
because Play Games parks its window *hidden*, so `ensure_readable` went looking for a fix,
and the fix was `_restart`, which closes the game before discovering it has no executable to
reopen it with. Nothing about `fingerprint(controller)` suggests it can do that. **Pass
`verify=False` from anything that only observes.** Fixed in `_restart`, `recon.fingerprint`
and here; covered by `game-ontology/test_no_restart_without_exe.py`.

**Every frame-comparison constant here was calibrated against a lobby that no longer
exists.** The account progressed, the lobby gained an animated offer banner and a ticking
countdown, and idle animation went from a steady 1 cell of 576 to 132 of 2304 - past the
readiness gate's tolerance of 60, so a live and perfectly readable client died with `window
never rendered a settled frame`. `--screen-match 0.93` gets a pass through; it also makes a
real freeze harder to see, which is the actual problem, since one number is answering both
"is this settled" and "is this alive". `sweep_stability.py` exists to measure the better
question - **97.3% of that lobby's cells hold still**, and the movers are all named
decoration - and `game-ontology/README.md` lesson 28 has what a mask would need.

Do not re-measure by comparing frames captured at **different resolutions** (787x1400 vs
393x700 both reduced to 64 columns inflated the same measurement from 24 cells to 84), and
do not assume every high threshold is now wrong: measured the same day, `battle.py`'s
lobby-vs-itself agreement was 0.979-1.000 against its 0.9 bar.

`--screen-match 0.93` is a person's guess repeated until it works. `clash-royale-kit/cr.py`
does the same thing arithmetically instead: it watches the untouched window for six seconds,
takes the *worst* second rather than the mean, and cuts the threshold just below it - so the
number moves with the lobby rather than with whoever last ran a pass. Six seconds because a
healthy lobby measured 5, 0, 0, 0, 0, 5: two samples read no movement about two times in
three, and cut a threshold no frame of that lobby survives. The reasoning and the measurement
are written into `preflight.json` and into the wiki, because a threshold whose argument was
left in a terminal scrollback is one nobody can check later.

Whatever a previous calibration pass measured is applied by `attach.apply_calibration`, which
every caller must ask for: `attach` builds its own `Target` rather than going through
`targets.resolve`, so it hands out the `Target` defaults and not the file. Deliberately still
opt-in - tightening `screen_match` from 0.94 to the measured 0.974 also tightens `wait_stable`
and `_wait_settled`, which is what killed a pass on the animated lobby in the first place.

## Known traps, not yet fixed

- **`battle.py` photographs whatever is on screen at startup as its lobby reference.** Run
  after a recon pass it binds a *profile screen* as "the lobby", which inverts its own
  navigation test while every log line still reads plausible. Put the client on the lobby
  first. What caught it was the positive half of the gate - the elixir-bar check - not the
  change test.
- **`--seconds 210` does not cover an overtime match**, and stopping mid-match cascades:
  the "end" frame is not a result screen, and the dismiss taps land on a live board.
- **Recon exits wherever it finished** rather than returning to a known screen. `run_recon.py`
  itself still does; `clash-royale-kit/cr.py` presses the vetted recovery action afterwards,
  so a pass started through the kit ends on the main screen or says loudly that it did not.
  Which matters because of the `battle.py` trap above: the cost of exiting on a profile screen
  is paid by whatever runs next, not by the pass that left it there.
- **The client freezes silently.** Every Win32 health check reports a healthy window while
  the guest has stopped rendering; only idle drift catches it and only a relaunch - a
  person's job - fixes it.

## Testing

```bash
python -m pytest experiments/android-bot experiments/game-ontology
```

127 tests here, 72 next door. All deterministic and LLM-free; every real-window call is
monkeypatched, so nothing needs to be installed and no game has to be running. **CI does
not run them** - they are Windows-only while CI is Linux - so run them by hand.

Session artifacts, recon maps, frames and write-ups go to `out/`, which is gitignored.
