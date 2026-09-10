# clash-royale-kit

One command that explores Clash Royale for a set number of minutes and writes a wiki about
what it found. Windows, a real client, a real account, nobody sitting with it.

```bat
python clash-royale-kit\cr.py --doctor          :: check the machine, touch nothing
python clash-royale-kit\cr.py --minutes 15      :: explore, then build the wiki
```

The client has to be **open, on the main screen, and idle** before you start. This kit cannot
open it - a Play Games title has no executable to launch, and that limitation is kept on
purpose rather than worked around. Opening the game is a person's job.

## Why this exists

The wiki this produces already existed once, built by a person sitting beside an agent that
kept adjusting code mid-run. That worked, and it is not something anyone else can repeat.

Going back over what those adjustments actually were, almost none of them were code bugs.
They were the same handful of environmental problems every time - a threshold measured against
a lobby that has since changed, a client left on the wrong screen, a window that was really an
editor with the game's name in its title bar, an emulator that had silently stopped rendering.
Each had a ten-second fix, and each was invisible because the symptom never named the cause.

So this kit is not a smarter agent. It is those checks, run before anything starts, each
reporting in a sentence that says what is wrong and what to do about it - and then the
exploration pass that already existed, and a wiki built from its output by arithmetic.

## Install

```bat
git clone <this repo>
cd qes-exploration
py -3.13 -m venv .venv
.venv\Scripts\pip install -r clash-royale-kit\requirements.txt
copy engine\.env.example .env
```

Then edit `.env`. For Bedrock through SSO, which is what this was set up for:

```
ENGINE_USE_BEDROCK=1
AWS_REGION=eu-west-1
AWS_PROFILE=your-profile
```

and log in before a run - `aws sso login --profile your-profile`. An SSO token that has
expired looks perfectly configured and fails on first use, so `--doctor` makes a one-token
call rather than just constructing a client. It costs a fraction of a cent and it is the
difference between finding out now and finding out five minutes into a pass.

`.env` at the repo root, and run from the repo root. `engine/client.py` calls
`python-dotenv`'s `load_dotenv()` with no path, which - for a real script run, not a `python -c`
one-liner - searches upward starting from `engine/`'s own directory, not from wherever you
launched the command. That only reaches the repo root if nothing between `engine/` and the
root has its own `.env`; a stray one anywhere in between (an old `engine/.env` from before this
kit existed, say) is found first and silently shadows the repo-root file, with no error and no
mention of which one won. If auth looks configured but keeps resolving to the wrong provider or
model, run `python -c "from dotenv import find_dotenv; print(find_dotenv())"` from the repo
root to see which `.env` is actually being read, and remove or fix whichever one is not the
repo-root file. `run.cmd` still gets you to the repo root either way.

Verify the install without a game or a model:

```bat
.venv\Scripts\python -m pytest clash-royale-kit
```

112 tests, none of which needs Windows, a window, a client or credentials. Green means the
Python side is sound and anything still wrong is the client or the login.

## Running it

`run.cmd` is the double-clickable front door. It cd's to the repo root, prefers `.venv`, and
keeps the window open so a refusal is still readable. With no arguments it runs the doctor,
because that is the safe default.

```bat
clash-royale-kit\run.cmd --minutes 20 --synthesize
```

| flag | |
|---|---|
| `--minutes N` | how long the exploration pass runs. Default 5. Ten to twenty is a useful pass; the map grows roughly with time but the interesting screens are found early |
| `--doctor` | run every check, touch nothing, print the findings and stop |
| `--synthesize` | after the wiki is built, add three analysis pages written by a model from the run's own measurements. See below |
| `--out DIR` | where to work. Default `clash-royale-kit\out\<timestamp>` |
| `--wiki-only DIR` | skip the game entirely and rebuild the wiki from a run directory that already exists |
| `--no-teardown` | leave the client wherever the pass finished instead of returning it to the main screen |
| `--max-restarts N` | how many times a crashed pass may be resumed from its own map. Default 1 |
| `--drift-samples N` | seconds of idle window watched to derive this session's threshold. Default 60 - this threshold overrides the calibration file for the whole pass rather than blending with it, so a short sample does not just under-measure, it hands the entire pass a threshold nothing survives (see Known limits) |

What happens, in order:

1. **Preflight.** The window is found and identified, the client area is measured, both safety
   layers are verified, the idle animation is sampled for sixty seconds, this session's
   screen-match threshold is derived from that sample, and the screen the client is sitting on
   is identified. Nothing is tapped. Any of these can refuse the run.
2. **The model check.** One token, to prove the vetting call the pass depends on can be made.
3. **The pass.** `experiments\android-bot\run_recon.py`, run as a child process, exploring for
   the time you asked for and writing `ontology.json`, `report.md`, `session-log.log` and a
   few dozen PNGs. Console output names the action about to be sent and the cleared candidates
   already queued behind it, so a person watching a live account sees what is coming, not just
   what just happened.
4. **Teardown.** One vetted tap to return the client to the main screen.
5. **The wiki.** Built from `ontology.json`, then indexed and rendered to HTML if Node.js is
   on `PATH`. If it is not, you get the markdown and a note saying so.

Output lands in the workspace directory:

```
out\20260907-141230\
  preflight.json         every number the checks measured, and why
  recon-1\               the pass's own output: ontology.json, report.md, images\
    session-log.log        one row per action, in the order it happened: at; screen;
                            action; result; notes - `report.md` groups by screen, this
                            is the same run cut by wall-clock instead, for retracing
                            what happened at a given moment
  wiki\                  the bundle: overview.md, summaries\, entities\, concepts\, log\
  wiki-html\             the same thing browsable, if Node.js was available
```

## What is in the wiki

Everything except the three synthesis pages is derived, not written: the screen names and
purposes, the element labels and the refusal reasons are all prose the *pass itself* produced
while exploring, and the pages arrange it and count it.

| page | |
|---|---|
| `overview.md` | what was explored, for how long, and against which reference measurement |
| `summaries\recon-*.md` | the pass's own report, framed |
| `entities\screen-*.md` | one page per screen: what it is, what is on it, what leaves it, what was never pressed, and - where the screen has any - where it animates on its own: a picture with the regions boxed (needs Pillow; `pip install Pillow` - the coordinates render as a table either way), red for a sub-second cycle, orange for a slower one caught only by the longer of the two sampling tiers `map_animation` runs before anything is done to the screen. A scrollable screen also gets a **whole page** section: the frames it scrolled through, stitched into one long picture (needs Pillow; the scroll facts show either way) |
| `entities\persistent-elements.md` | controls that appear on three or more screens, i.e. the navigation chrome |
| `concepts\navigation-map.md` | the routes, the screens with no recorded exit, the ones never entered |
| `concepts\refused-and-unmodelled.md` | what the safety layers declined, kept separate from what the budget simply never reached |
| `concepts\frames-vs-counts.md` | transitions that reported a change between two **byte-identical** crops |
| `concepts\screen-identity.md` | how screens were told apart, and the threshold that decided it |
| `concepts\clickable-elements.md` | every named element across the whole run, one row each, with what happened to it: pressed, refused (and why, in the model's own words), cleared but never got its turn, or never vetted at all |

That frames-vs-counts page is the one worth reading first, and it deliberately does not
overclaim: the change count is measured over the whole frame while the saved crop covers only
part of it, so identical crops prove the *saved evidence does not show the reported change* -
not that the screen held still.

### `--synthesize`

Three extra pages, each one model call with a forced schema, a fixed budget and no ability to
run code or ask for more:

- `concepts\what-this-interface-is-for.md`
- `concepts\where-this-target-asks-for-money.md`
- `concepts\where-this-map-is-weakest.md`

Every claim on them must cite a measurement from the run by name, carry a `measured` /
`inferred` / `speculative` marker in a column of its own, and name the rival explanation it
would lose to. A claim that cites nothing is rejected and rewritten into an explicit
"could not be settled" list. What a model happens to know about Clash Royale in general is
inadmissible, and the citation rule is what makes that enforceable rather than aspirational.

They are built *after* the deterministic wiki, which is why they can fail softly: no
credentials, or a model that will not answer, costs you three pages and a printed note. The
wiki is already complete.

## What it will never do

The rules below are decisions a person made about somebody's real account. This kit inherits
them and cannot switch any of them off.

| rule | held by |
|---|---|
| **money is untouchable** - gems, gold, shop, chests | 6 coordinate boxes in `experiments\game-ontology\target.py` **and** the model vetting call |
| **the Battle button stays blocked** - it is a live ladder match | a coordinate box, verified in preflight before any frame is scored |
| **no battle is fought** | `battle.py` refuses without `--allow-battle`, and this kit never passes it - there is a test asserting the flag is never even constructed |
| **nothing opens the launcher** | `Target.exe` is empty on purpose, and the restart path refuses before it acts |
| **watching never touches** | every frame this kit takes for itself is grabbed with `verify=False` |

That last one is the most expensive thing this project has learned. A *verified* grab of a
window that is not in the foreground sends the harness looking for a fix; the fix is a
restart; the restart closes the client before discovering it has no executable to reopen it
with. Play Games parks its window hidden, so that is the ordinary path, not an unlikely one. A
liveness check has closed the client it was checking, and there is a test here whose only job
is to assert no frame is ever verified.

Two layers guard the taps rather than one, and they are not redundant. A coordinate box is
pure geometry and screen-blind, so it cannot cover a control that did not exist when the box
was drawn - the vetting call refused a mystery-chest `Claim` that no box covers. Conversely
the model cannot be trusted to notice the Battle button every single time. Both must hold,
which is why a run with either one missing refuses to start rather than warning.

## When it refuses

Every refusal names the cause, says what to do, and tells you whether anything was tapped.
The four you are most likely to see:

**"no Play Games window named 'Clash Royale' is open"** - and then two things to check. Is the
client actually running the game, not sitting on the launcher's library page? And did a window
above get named as ignored? A Chrome tab or an editor showing a file *about* this game carries
the name too, and one was adopted and sent drags before this check existed.

**"the client area measures ... smaller than ... will drive"** - almost never a small window.
It means DPI awareness was not claimed, so Windows is reporting a scaled rect and every
fractional coordinate would resolve against geometry the game is not using. Taps land
somewhere else and nothing errors, which is why this refuses instead of continuing.

**"the client is on <screen>, not on the main screen"** - press back or the home tab by hand
and run again. Not a safety problem, a labelling one: a run treats its first screen as the
place it returns to after every discovery, so starting elsewhere makes every navigation
finding an artefact.

**"the model could not be reached"** - usually an expired SSO token. `aws sso login` and run
again. Refused rather than warned about, because that call is one of the two safety layers. If
the error names `claude-sonnet-4-6` (the direct-API model) instead of the Bedrock one even with
`ENGINE_USE_BEDROCK=1` set, see the shadowed-`.env` note under Install first - the venv is
probably reading a different `.env` than you think it is. If the error is
`ModuleNotFoundError: No module named 'botocore'`, the venv predates `anthropic[bedrock]` being
added to `requirements.txt`: re-run `.venv\Scripts\pip install -r clash-royale-kit\requirements.txt
--upgrade` to pull in `boto3`/`botocore` and the `anthropic>=1.0` floor `AnthropicBedrockMantle`
needs.

One thing this deliberately never concludes is that a client is *dead*. A frozen emulator and
a quiet lobby look identical to every Win32 health check, and a live lobby once measured one
changed cell out of 576 for ninety seconds while rendering perfectly. Idle movement is
reported as evidence, in the output and in the wiki, and never as a verdict - because the
action a "dead client" verdict invites is a restart, and a restart here closes a client that
nothing can reopen.

## Known limits

- **The carried fingerprints have a date on them.** Screens are named by comparison against a
  pass measured on a specific day against a client that updates itself. A confident name may
  be describing a screen that has since changed; the wiki says so on the identity page and
  `preflight.json` records which pass it scored against.
- **The threshold is a compromise.** One number answers both "has this screen settled" and
  "is this the same screen", and this kit derives it from the current session's own idle
  drift rather than trusting the file. That is better than a stale constant and still one
  number doing two jobs. It also means the derivation's own sample window has to actually
  catch the screen's animation to be trustworthy: on 2026-09-08 a six-second sample read the
  main screen as calmer than it is, derived a threshold preflight itself passed, and then the
  real pass failed its settle-wait repeatedly on bursts the short sample never saw - because
  the derived value *replaces* the calibration file for the whole pass rather than blending
  with it. `--drift-samples` now defaults to 60s rather than 6 for this reason; a game whose
  idle animation cycles slower than that would need it raised further.
- **A pass explores; it does not verify.** The output is a map and a set of observations about
  an interface, not a test result. Nothing here has an expectation to fail.
- **`--minutes` is a budget, not a promise of coverage.** The refusals page keeps "the safety
  layer declined this" and "the budget never reached this" as separate counts on purpose,
  because merging them would read as a much stricter guard than actually exists.

## Layout

| file | |
|---|---|
| `cr.py` | the entry point: the sequence above, and nothing else |
| `preflight.py` | the checks. Windows-only, every Win32 import function-local so the tests can stub them |
| `checks.py` | the decisions those checks make - thresholds, verdicts, retry policy. No Win32 at all |
| `wikibuild.py` | `ontology.json` to an OKF wiki bundle. Pure arithmetic and string formatting |
| `synthesize.py` | the three optional model pages, with the citation rule |
| `fixtures\ontology.json` | a hand-written map the wiki tests build from, so they need no game |
| `test_*.py` | 112 tests, cross-platform, no game and no credentials |

It leans on three things already in this repo rather than copying them: the harness in
`experiments\game-ontology`, the target in `experiments\android-bot`, and the safety layers in
`engine\adapters\clash_royale`. Read
[`experiments\android-bot\README.md`](../experiments/android-bot/README.md) if you are going to
change any of it - it carries the reasoning behind the rules this kit only enforces.
