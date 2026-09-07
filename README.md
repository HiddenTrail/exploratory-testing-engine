# qes-exploration

[![engine tests](https://github.com/HiddenTrail/exploratory-testing-engine/actions/workflows/engine-tests.yml/badge.svg)](https://github.com/HiddenTrail/exploratory-testing-engine/actions/workflows/engine-tests.yml)

An LLM-based **disconfirmation engine** for exploratory API testing: instead of
running a fixed, pre-scripted test plan, it drives a live system, forms a
falsifiable hypothesis about its behavior, and puts that hypothesis through a
cold, adversarial review before trusting it - mirroring how real scientific
method works rather than how most AI-testing tools work (which mostly confirm,
rarely try hard to disprove themselves). See
[`docs/exploratory-testing-engine-concept.md`](docs/exploratory-testing-engine-concept.md)
for the original vision this project is one deliberately narrow, implemented
slice of.

## How a run works

Against a live system under test (SUT), each **checkpoint**:

1. **Casts** a batch of real tests (an adapter-defined test-proposal schema),
   executes them for real, and records predicted vs. actual outcomes.
2. Forms **one hypothesis** about the system's behavior and any anomalies
   noticed - a specific, falsifiable claim per anomaly, not a vague suspicion.
3. Gets a **cold Skeptic review** of that hypothesis: a second LLM call that
   never sees the raw test data, only the hypothesis itself. It checks
   whether the cited evidence actually discriminates the claim from its own
   named rival explanation - not just whether evidence exists - and returns a
   `weak` (keep going) or `strong_enough` (stop) verdict.
4. The loop continues on `weak`, informed by the Skeptic's critique, or stops
   on `strong_enough` or a checkpoint cap.

If the final hypothesis claims anomalies, a bug report is written per claim -
honestly marked `inconclusive` if the checkpoint budget ran out while the
Skeptic still had objections, `corroborated` only if it was satisfied. Output
is a JSON result, a JSON bug list, and a self-contained HTML report.

## Bootstrapping a new adapter automatically

Testing a new API normally means hand-writing an *adapter* (see below). The
`engine/bootstrap/` pipeline can generate a first draft of one instead, by
actually pointing itself at a live system and working out the schema for real:

```
Discover      → try the live SUT's own OpenAPI/Swagger doc first (free, exact)
Draft (LLM)   → only if discovery found nothing: infer a schema from free text
Probe (LLM)   → send real requests to confirm/correct the draft against
                 the live system's actual responses - a 422 naming a missing
                 field resolves an unknown more reliably than a guess would
Generate      → emit a real, runnable adapter.py from what was confirmed
```

Run all four phases end to end with:

```
python -m engine.bootstrap.cli \
  --name my_api --display-name "My API" --base-url http://localhost:8000
```

This never auto-registers or auto-runs the result - it prints the line to add
to `engine/adapters/registry.py` and the command to run it, keeping
registration a deliberate human step. A generated adapter that never achieved
a real success is refused outright (`status == "failed"`); one that ran out
of probing budget while still uncertain is generated anyway, with a
prominent warning comment carrying forward exactly what's still unconfirmed.
See [`docs/examples/bootstrap_demo/`](docs/examples/bootstrap_demo/) for a
real, unedited run of this pipeline - including the adapter it generated and
the bug it found.

Other flags:
- `--discover-only` - stop after Phase 1 (schema discovery) and write
  `runs/<name>/discovered_schema.{json,html}`, then exit - no LLM calls at
  all, so it's a free way to check what a SUT publishes before spending any
  probing/generation budget on it.
- `--spec-text <text>` - a schema-inference fallback, read only if Phase 1
  discovery finds nothing at all (i.e. no OpenAPI/Swagger doc).
- `--max-probes N` - cap on Phase 3 probing rounds (default 8).

### Context-enriched bootstrap

Beyond the schema itself, free-text background - what the API does, its
normal use cases - can be supplied and gets threaded into both Phase 3
probing and the generated adapter (baked into its schema doc and system
prompt, so it persists into every future checkpoint-loop run against that
adapter, not just the one-off bootstrap):

```
--context-source file --context-file <path>     # (default) read a plain text file
--context-source jira --ticket <id>              # read a MOCKED ticket store
```

This is a 4-phase roadmap, being built incrementally:
1. ✅ Thread context into probing.
2. ✅ Persist context into the generated adapter.
3. ✅ Prove the source is swappable via a mocked `jira` ticket store
   (`engine/bootstrap/jira_mock.py`) - no real JIRA calls.
4. ⏳ Not started - real JIRA API integration (auth, live ticket fetch),
   left as a `TODO` in `jira_mock.py` until explicitly requested.

## Ontology layer (prioritization)

`engine/ontology/` sits between the domain-grounded oracle claims and the
Driver: a 4-layer flat-file stack (generic heuristic library → per-SUT
business/domain facts → context/results → a ranked, prioritized test-idea
list) that scores claims up or down based on what's already been tested,
refuted, or flagged in a ticket, instead of handing the Driver an unranked
dump. Proven end to end on `token_purchase` (a live Driver run consumed the
ranked list, and its results were fed back into the context layer). Each
ranked idea carries a stable id the Driver can cite (`oracle_claim_id`) when
a test targets it, so feedback actually reprioritizes claims on the next run
rather than only ever matching on the Driver's own free-text hypothesis.
Full status and backlog: [`docs/ontology-todo.md`](docs/ontology-todo.md).

```
python -m engine.ontology.oracle_creator --sut token_purchase   # layer 4: rank
python -m engine.ontology.website --sut token_purchase          # view all 4 layers
python -m engine.ontology.feedback --sut token_purchase --run <output.json>  # close the loop
```

## Layout

```
engine/
  adapter.py    # SUTAdapter interface - what a per-SUT adapter must supply
  tools.py      # HYPOTHESIS_TOOL / SKEPTIC_TOOL / BUG_REPORT_TOOL - shared across every adapter
  client.py     # Anthropic client + call_tool_with_retry (tool-forced calls, retried on transient errors)
  loop.py       # the checkpoint loop itself
  outcome.py    # the typed envelope an adapter puts on each result - a SUT's behaviour in terms the
                #   engine can compare and count, replacing prose no generic code could read
  diagnostics.py # domain-free detectors over those envelopes - facts about the RUN rather than the SUT:
                #   a state whose actions are all inert, a batch that didn't start from one place, a
                #   baseline reset that stopped working, a prior that matched nothing
  report.py     # generic HTML rendering (prose, badges, CSS, page/checkpoint structure)
  runner.py     # orchestrates one full run: readiness probe, loop, bug reports, file output
  cli.py        # python -m engine.cli --adapter <name>
  adapters/
    registry.py           # name -> adapter module, resolved lazily at run time
    token_purchase/        # first adapter: single request/response, decline-reason logic
    complex_sut/            # second adapter: concurrency/rate-limiting, proves the interface generalizes
    clash_royale/           # third adapter: a live game client - no URL, no response body, taps and frames.
                            #   The first non-HTTP SUT, which is what moved the engine's HTTP assumption
                            #   behind check_sut_ready / fetch_happy_day_example. Read actions.py first:
                            #   it is the whole safety argument for driving a real account. known_screens.json
                            #   carries eleven screens an earlier recon pass measured against this client, four
                            #   of them classified "abort" - which is how a run notices it reached the shop.
  bootstrap/
    discovery.py  # Phase 1 - fetch and parse a live OpenAPI/Swagger document
    freetext.py   # Phase 2 - LLM fallback: infer a schema from free-text spec text
    schema.py     # ties discovery and the free-text fallback together
    probe.py      # Phase 3 - active probing loop against the live SUT
    generate.py   # Phase 4 - generate a real adapter.py from a confirmed/inconclusive result
    report.py     # renders a DiscoveredSchema as HTML for --discover-only
    jira_mock.py  # stubbed ticket store for context-enriched bootstrap - see above; real JIRA is a TODO
    cli.py        # python -m engine.bootstrap.cli - chains all 4 phases end to end
  ontology/       # prioritization layer stack (heuristics/domain/context/ranked oracle) - see above
  tests/          # deterministic regression + parity tests (no LLM calls, runs in CI)
experiments/      # mostly earlier prototypes this package was hardened from, kept as a historical
                  #   archive. Two are NOT archive: they are worked on, and the clash_royale adapter
                  #   imports them at run time (see session.py's own note on that debt), so a rename
                  #   in either can break the engine with nothing in CI to catch it:
  game-ontology/  #   the general game harness - window identity, readiness, input safety, screen
                  #   discovery. Has its own pytest suite (72 tests). Read its README's "Things that
                  #   bit" before changing anything in controller.py.
  android-bot/    #   the Clash Royale target built on that harness: attach, recon, errands, one
                  #   authorised Training Camp battle, and the measurement tools (127 tests). Its
                  #   README carries the safety rules and which layer holds each - read it first,
                  #   because this one drives somebody's real account.
clash-royale-kit/ # the two directories above, packaged as one command for somebody who is not
                  #   going to read either README: check the machine, explore for N minutes,
                  #   write a wiki from what was found. No agent and no code editing at run time -
                  #   the interventions a person used to make were environmental, so they are
                  #   checks with sentences attached now. 98 tests, and they DO run in CI.
docs/
  exploratory-testing-engine-concept.md  # the original, broader vision
  examples/bootstrap_demo/                # a real worked example of the bootstrap pipeline's output
```

`engine/*` never imports from `engine/adapters/*` - adapters import from
`engine`, never the reverse. `engine/adapters/registry.py` is the only place
that crosses that boundary, and it does so lazily (`importlib`) at CLI run
time. `engine/bootstrap/` follows the same rule: it depends on `engine/`, not
on any concrete adapter.

## Getting started

```
# terminal 1
pip install -r engine/requirements.txt
uvicorn engine.adapters.token_purchase.sut:app --port 8000

# terminal 2
cp engine/.env.example engine/.env   # fill in ANTHROPIC_API_KEY
python -m engine.cli --adapter token_purchase
```

To authenticate through Amazon Bedrock instead of an API key, set
`ENGINE_USE_BEDROCK=1` and `AWS_REGION` (plus `AWS_PROFILE` if needed) - see
[`engine/README.md`](engine/README.md) for the model-ID caveats, which are not
the same IDs `aws bedrock list-inference-profiles` reports.

Writes `runs/<adapter>/output.json`, `runs/<adapter>/bugs.json` (if any
anomalies were found), and `runs/<adapter>/report.html`. Override run
parameters with `--model`, `--max-checkpoints`, `--first-round-budget`,
`--default-budget`, `--out-dir`.

See [`engine/README.md`](engine/README.md) for adding a new adapter by hand,
and the CI/testing setup.

### Mapping the game client instead

The non-HTTP target has its own front door, on Windows, against an already-open
client:

```bat
python clash-royale-kit\cr.py --doctor        :: check the machine, touch nothing
python clash-royale-kit\cr.py --minutes 15    :: explore, then build a wiki from it
```

That is a different question from a checkpoint loop: it explores an interface
and writes down what is there, rather than forming a hypothesis and trying to
disprove it. It exists because the wiki it produces used to need a person
sitting beside an agent, and the interventions turned out to be environmental
rather than bugs - a stale threshold, a client on the wrong screen, an editor
window carrying the game's name - so they are now checks that refuse with a
sentence saying what to do. See
[`clash-royale-kit/README.md`](clash-royale-kit/README.md), which assumes no
knowledge of the rest of this repo.

## Testing

```
pip install -r engine/requirements.txt
python -m pytest engine/tests
```

Runs automatically on every push to `master` and every PR via
[`.github/workflows/engine-tests.yml`](.github/workflows/engine-tests.yml) -
no Anthropic API key needed, since no test makes a real LLM call. That workflow
also runs `clash-royale-kit`'s 98 tests, which are cross-platform on purpose:
the kit drives a Windows client, but its decisions live in modules that import
no Win32, and the ones that do keep those imports function-local so a stub can
be put under the name. What that buys is having the assertions that matter -
no frame is ever grabbed with verification, the safety layers are checked
before any frame is scored, `--allow-battle` is never constructed - checked on
every PR rather than only on the one machine with the game installed.

The game harness carries its own suites, which CI does **not** run - they are
Windows-only (Win32 window handles, GDI capture) while CI is Linux:

```
python -m pytest experiments/game-ontology experiments/android-bot
```

Those are also LLM-free and deterministic; every real-window call is
monkeypatched, so no game has to be installed to run them. Run them by hand
before touching `controller.py`, because what they cover is which window
receives input and whether the harness may close a client - the two failures
there are a drag sent into somebody's editor and a game shut with no way to
reopen it, and both have happened.
