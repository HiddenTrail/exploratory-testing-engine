# Game Automation Bot — Project Brief

## 1. Goal

Build a Python tool, launched from the terminal, that plays a game running in
the Google Play Games emulator on PC. The tool is **not** meant to teach the
game "to be good" via pure reinforcement learning from scratch. Instead:

- **Claude (via the Anthropic API, vision + tool use)** handles perception and
  moment-to-moment decision-making by reading screenshots of the game.
- An **existing custom ML algorithm** (already written in Python) is attached
  as a secondary component to boost play *efficiency* on a narrower
  optimization problem (e.g. resource allocation, pathing, scheduling — scope
  still to be defined precisely).
- The two are combined either as (a) a tool Claude can call mid-reasoning, or
  (b) a pre/post filter that adjusts or vetoes Claude's proposed action.

The architecture must be **input-agnostic**: it should work whether the game
is an Android app in the Play Games emulator, or later, a browser game with
partial or zero logging/DOM access. Vision-only (screenshot in, action out)
is the lowest common denominator and must always work as a fallback.

## 2. Current status

- Google Play Games is installed on PC; the game runs inside its bundled
  Android emulator.
- No test harness or environment wrapper exists yet — this is the first
  build.
- Existing self-learning/efficiency algorithm exists as a separate Python
  module (not yet wired into anything below — treat as a pluggable
  black-box tool for now, name/interface TBD).
- Anthropic API key is available and intended for the vision/decision loop.

## 3. Target architecture

```
screenshot (ADB) ──► Claude (vision + reasoning, tool use) ──► structured action ──► ADB tap/swipe
                                    │
                                    ▼
                         existing ML algorithm (called as a tool,
                         or as a pre/post filter on Claude's action)
```

### 3.1 Observation layer (the "eyes")

Primary and always-available:
- `device.screenshot()` via ADB (through `adbutils` or `subprocess` wrapping
  the `adb` binary) — full-resolution frame, sent to Claude as base64 image
  input.

Secondary, use if available (query for presence, don't assume):
- `adb shell uiautomator dump` — UI hierarchy XML. Only useful if the game
  renders native Android widgets rather than a single opaque game-engine
  surface (Unity/Unreal/Cocos2d games will not expose anything useful here —
  check early and don't build a dependency on it).
- `adb logcat` — grep for score/state-change lines if the game happens to log
  anything useful. Treat as a bonus reward signal, not a guaranteed one.
- `adb shell dumpsys` — crash/background detection, not a primary signal.

Design constraint: **the environment interface must not assume logs, DOM, or
UI hierarchy exist.** Every non-screenshot signal is optional and should
degrade gracefully to "pixels only."

### 3.2 Action layer (the "hands")

- ADB taps/swipes: `device.click(x, y)`, `device.swipe(x1, y1, x2, y2, duration)`.
- Action space should be **defined up front** as a discrete set (e.g. a fixed
  list of named tap targets/coordinates found via one manual exploration
  pass), not an unconstrained continuous coordinate space — this keeps
  Claude's tool-use action schema small and keeps any attached optimization
  algorithm's search space tractable.

### 3.3 Decision layer (Claude)

- Use the Anthropic Messages API with image input (screenshot as base64
  PNG) and **tool use** for structured output — do not parse free-text
  action proposals.
- Example action tool schema:
  - `action_type`: enum `tap` | `swipe`
  - `x`, `y` (and `x2`, `y2` for swipe)
  - `reasoning`: string (for logging/debugging, not required for execution)
- Expose the existing efficiency algorithm as an additional named tool
  Claude can invoke mid-reasoning when it needs an optimization
  recommendation (e.g. `optimize_allocation`), OR run it as a filter that
  intercepts Claude's proposed action before it's sent to ADB. Both are
  valid; the brief should let Claude Code scaffold the tool-use plumbing
  generically enough to support either without a rewrite.

### 3.4 Loop shape

```python
while True:
    obs = env.get_observation()          # screenshot (+ optional logcat/UI dump)
    action = agent.decide(obs)           # Claude call, tool-use response
    env.take_action(action)              # ADB tap/swipe
    # optional: reward/logging bookkeeping if the algorithm needs it
```

No pre-scripted sequence of actions — every action is decided live per
observation.

## 4. Known constraints / risks to design around

- **ADB availability is not guaranteed.** Google Play Games' emulator is a
  consumer product, not a dev-facing one; some builds block debug/ADB
  access entirely. The harness should fail loudly and early if
  `adb devices` doesn't show the target device, rather than deep into a
  build.
- **Cost/latency:** calling the Claude API per-frame is slow and can get
  expensive in a tight loop. Design the loop so it's easy to add a
  "only call Claude on meaningful state change" gate later (e.g. simple
  pixel-diff or hash check before invoking the API), without that being a
  required feature for v1.
- **Model string:** verify the current Claude model identifier at
  implementation time rather than hardcoding one from this brief — model
  names change.

## 5. Portability target (secondary, not required for v1)

The same Claude-vision decision loop should be reusable against browser
games later with only the observation/action *backend* swapped:

- ADB → **Playwright** (`page.screenshot()`, `page.mouse.click(x, y)`).
- Optional richer signals if available: DOM query (`page.query_selector_all`),
  `console.log` interception (`page.on("console", ...)`), network/XHR
  interception (`page.on("response", ...)`).
- For games with literally no logs/DOM/network signal (pure canvas/WebGL),
  the loop is unchanged — pixels-only vision already covers this case.

**Design implication for v1:** keep `get_observation()` / `take_action()`
behind a small interface/class boundary from the start (e.g. an `Env` base
class with an `AdbEnv` implementation now, `PlaywrightEnv` later) so this
swap is mechanical rather than a rewrite.

## 6. Suggested file/module scaffold

```
game_bot/
  env/
    base.py          # abstract Env interface: get_observation(), take_action(), reset()
    adb_env.py        # ADB-backed implementation
  agent/
    claude_agent.py   # Anthropic API call, tool-use schema, decision loop
    action_schema.py  # tool/action JSON schema definitions
  optimizer/
    integration.py    # wraps the existing efficiency algorithm as a callable tool/filter
  cli.py               # argparse entry point, launched via `python -m game_bot`
  config.py            # device serial/port, model name, action space definition
```

## 7. Open questions to resolve during setup

- What exactly does "efficiency" mean for this game — what does the
  existing algorithm optimize, and what inputs does it expect?
- Tool-call vs. filter integration for the algorithm — pick one for v1.
- Fixed action space: what are the actual tap targets/coordinates for this
  specific game (requires one manual exploration pass before automation
  starts)?
- Reward/success signal: is there anything log-based to use, or is this
  purely vision-judged by Claude in the loop?
- Call-frequency gating: build it into v1, or defer until cost/latency is
  actually a problem?
