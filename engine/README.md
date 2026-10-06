# AI Exploratory Testing Engine

A reusable Driver+Skeptic checkpoint-loop harness, hardened from earlier
experiments in `.experiments/` (most of them now an archive - this package is
a port, not a rewrite). See `docs/exploratory-testing-engine-concept.md` for
the original vision this is one deliberately narrow slice of.

The "archive" framing has exceptions. `adapters/clash_royale/session.py` puts
`.experiments/game-ontology`, `.experiments/android-bot` and
`.experiments/game-screen-probe` on `sys.path` and imports them at call time,
rather than copying about 1,800 lines of Win32 window handling that have been
hardened against a real client. `adapters/web_gui/session.py` does the same
with `.experiments/web-recon`. Both comments record this as a knowing debt, and
moving that code out of the archive is issue #48. Those folders are
**maintained, not frozen**. game-ontology and android-bot have their own pytest
suites, which are Windows-only, so CI runs neither. The parity tests also read
`.experiments/complex-sut-poc` and `.experiments/token-purchase-poc` (issue #77).

## What it does

Against a live SUT, each checkpoint:
1. **Casts** a batch of real tests (an adapter-defined test-proposal schema),
   executes them for real, and records predicted vs. actual outcomes.
2. Forms **one hypothesis** about the system's behavior (`HYPOTHESIS_TOOL`):
   a one-sentence summary, confirmed behaviors, and zero or more
   **observations**. Each observation is a finding, an anomaly or a bug, cites
   its test numbers and a genuine rival, and says how it reproduced. A bug must
   name the known fact it violates and reproduce consistently. Every field has
   a word limit.
3. Gets a **cold Skeptic review** of that hypothesis (`SKEPTIC_TOOL`) - a second
   LLM call that never sees the raw test data, only the hypothesis itself. Per
   observation it checks whether the cited evidence actually discriminates the
   claim from its own rival (not just whether evidence exists) and gives its
   own view of the kind; the engine keeps the more cautious of the two. For
   coverage it also gets `test_coverage`, which the engine works out from the
   log: the values each input field has been sent, and for an enum or boolean
   field the values never tried. It
   checks whether the Driver's answers to its prior gaps hold up, and names new
   gaps with the test that would close each. Its verdict must follow from its
   objections: `weak` needs at least one (evidence that doesn't discriminate,
   material coverage, a blocking gap, or a rejected prior answer), and
   `strong_enough` allows none. The validator enforces this. Before the review,
   the Driver tells its **testing story** in its own call (`TESTING_STORY_TOOL`):
   per area what it has seen, how it tested, how deep and of what, and what got
   in the way; the Skeptic gets it with the previous checkpoint's.
4. A **debrief** when the review is `weak` (`DEBRIEF_ANSWER_TOOL`,
   `RECONSIDER_TOOL`): the Driver answers each question (defend with tests,
   concede, or change approach), the engine attaches what the cited tests
   recorded, and the Skeptic reconsiders. It can't say `strong_enough` while a
   blocking question hasn't convinced it. Settled and conceded questions drop
   out; the rest carry into the next checkpoint. Recorded on the checkpoint as
   `debrief`.
5. The loop continues on `weak`, informed by the questions still open, or stops
   on `strong_enough` or a checkpoint cap.

The engine stamps ids on observations (`C<n>.O<k>`) and gaps (`C<n>.G<k>`), so
the next checkpoint can answer a gap or continue an observation by id.

At the end, every observation of the final checkpoint gets a status decided by
the engine, not by a model: `corroborated` if the Skeptic's last check says its
evidence discriminates it from its rival and no blocking gap is about it,
otherwise `inconclusive`. All observations go into `output.json` under
`observations`. Only **bugs** get a written bug report (one LLM call for all of
them), because findings and anomalies are already complete as they are.

Before any bug is written up, the engine runs every test it cites again, exactly as
cast (`engine/verify.py`, #177). The adapter says whether each replay came out the
same. A bug whose tests don't all reproduce, or can't be replayed, is lowered to an
anomaly with the reason, so it never gets a bug report. No model is called for this.
Replay is opt-in through the adapter's `compare_replay` hook: so far only `web_gui`
has it, and other adapters' bugs are marked "not replayed" in the report.

**Known, accepted limitation:** the Skeptic's per-observation `discriminates_from_rival`
check (in `observation_checks`) doesn't account for realistic value rounding/precision
when deciding whether cited evidence discriminates a claim from its rival - see
the comment on that field in `engine/tools.py`. Carried forward deliberately, not fixed.

`engine/adapters/token_purchase/adapter.py` also pulls its onboarding
evidence's oracle content from `engine/ontology/` - a ranked, prioritized
test-idea list rather than the old flat claim dump - see the root README's
"Ontology layer" section and `docs/ontology-todo.md` for what's proven and
what's still open. Each ranked idea has a stable id the Driver cites as
`oracle_claim_id`, so a run's results do change the ranking on the next run.

## Layout

```
engine/
  adapter.py    # SUTAdapter interface - what a per-SUT adapter must supply
  tools.py      # HYPOTHESIS_TOOL / SKEPTIC_TOOL / BUG_REPORT_TOOL - domain-agnostic, not adapter-overridable
  client.py     # Anthropic client + call_tool_with_retry. Its retryable-error list is written out
                #   by name rather than by base class on purpose: OverloadedError (529) is a *sibling*
                #   of InternalServerError, not a subclass, and the SDK tests 529 before its >= 500
                #   branch - so a list built on subclassing let 529 propagate on the first attempt
  loop.py       # the checkpoint loop itself
  outcome.py    # the typed envelope an adapter puts on each result - the only SUT vocabulary the engine reads
  diagnostics.py # domain-free detectors over those envelopes: facts about the RUN, not the SUT
  interplay.py  # how well the Driver answered the Skeptic: gaps, answers, objections that came back
  steering.py   # most of each later round goes to new ground; claims the tests can't settle are parked
  coverage.py   # what the tests have sent so far, per input field, for the Skeptic
  report.py     # generic HTML rendering (prose, badges, CSS, page/checkpoint structure)
  runner.py     # orchestrates one full run: readiness probe, loop, bug reports, file output
  verify.py     # replays each bug's tests before it's reported, and lowers one that doesn't reproduce
  run_summary.py # a run's outcome as Markdown, for a CI job's summary page
  budget.py     # the hard spending limit: stops a run at ENGINE_MAX_MODEL_CALLS calls or about ENGINE_MAX_COST_USD
  cli.py        # python -m engine.cli --adapter <name>
  lean.py       # lean runs for experiments: the fields and calls a lean run skips (#295)
  ask.py        # python -m engine.ask <run>: asks a saved run for a part it didn't write
  config.py     # RunConfig: model, checkpoint and test budgets, output folder
  http.py, redact.py, util.py  # small shared helpers
  adapters/
    registry.py           # name -> adapter module, resolved lazily
    token_purchase/        # first adapter, ported from .experiments/token-purchase-poc
    complex_sut/            # second adapter - concurrency/rate-limiting domain
    clash_royale/           # third adapter - a live game client, not a web service. Read actions.py first
                            #   known_screens.json is measured data, not configuration: the screens a
                            #   game-ontology recon pass fingerprinted against this client (twenty today),
                            #   extracted by extract_reference.py and loaded by reference.py. Some are
                            #   classified "abort", which is what lets a run notice it has reached the shop
    web_gui/                # fourth adapter - a live web app in a browser. A test is a start and steps
                            #   on the live page; a web-recon/Spoor map is its guide. See its README
  bootstrap/                # generate a draft adapter from a live SUT - see below
  ontology/                 # prioritization layer stack (heuristics/domain/context/ranked oracle, and the seeder that builds a product's oracle from its wiki) - see root README
  tests/                    # deterministic regression + parity tests (no LLM calls)
```

`engine/*` never imports from `engine/adapters/*` - adapters import from
`engine`, never the reverse. `engine/adapters/registry.py` is the only place
that crosses that boundary, and it does so lazily (`importlib`) at CLI run
time.

## Running it

```
# terminal 1
pip install -r engine/requirements.txt
uvicorn engine.adapters.token_purchase.sut:app --port 8000

# terminal 2
cp engine/.env.example engine/.env   # fill in ANTHROPIC_API_KEY
python -m engine.cli --adapter token_purchase
```

Writes `runs/<adapter>/output.json`, `runs/<adapter>/bugs.json` (if any
bugs were found), and `runs/<adapter>/report.html`. Override run
parameters with `--model`, `--max-checkpoints`, `--first-round-budget`,
`--default-budget`, `--out-dir`. `--learn [product]` feeds the run's results,
discovered screens and the Skeptic's objections (by kind) into the context layer
when it ends, so the next run starts from them (#159, #258). Each run's Driver is
told the kinds of objection the Skeptic raised most before. `ENGINE_CONTEXT_DIR`
moves the context files to another folder, for benchmarks.

`--lean` makes a lean run, for experiments (#295): the model writes only what
decides a finding, and the testing story, the debrief and the bug report
write-ups are skipped. `--with story,debrief,bug_reports` switches parts back on.
Compare a lean run only with lean runs. To get a skipped part after reading a
run, ask the saved run for it, one call each, written to `<run>/asked/`:

```
python -m engine.ask runs/<run> --adapter web_gui --story [N]
python -m engine.ask runs/<run> --adapter web_gui --bug-reports
python -m engine.ask runs/<run> --adapter web_gui --question "Why was C3.O1 doubted?"
```

### Authenticating through Bedrock instead of an API key

Set `ENGINE_USE_BEDROCK=1` plus `AWS_REGION` (and `AWS_PROFILE`, if it isn't
your default) instead of `ANTHROPIC_API_KEY`. Credentials then come from the
normal AWS chain - SSO cache, profile, env vars, instance role - so there is no
long-lived key in the repo or the environment.

The default model changes with the provider, because Bedrock names models
differently: `claude-sonnet-4-6` on the direct API and
`anthropic.claude-sonnet-5` on Bedrock (see `engine/client.py`). Override it
with `--model`. Two important details:

- Bedrock's Messages-API endpoint exposes a **different, smaller catalogue**
  than the `aws bedrock list-inference-profiles` output. The `eu.anthropic.*`
  and `global.anthropic.*` inference-profile IDs from that listing are for the
  older `bedrock-runtime` InvokeModel path and are rejected here.
- Because the catalogues differ, a Bedrock run may not be on the same model as
  a direct-API run. Check `output.json`'s `model` before comparing results
  across providers.

Discover what actually works by attempting a one-token call per candidate ID -
an unavailable model fails fast with a 404 and costs nothing.

## Adding a new adapter

1. Create `engine/adapters/<name>/` with an `adapter.py` (plus a mock SUT if
   you are testing one).
2. In `adapter.py`, define the genuinely per-SUT pieces and build one
   `ADAPTER = SUTAdapter(...)` instance - see
   `engine/adapters/token_purchase/adapter.py` for a complete worked example.
   Required fields: `name`, `display_name`, `casting_tool_schema`,
   `casting_system_prompt`, `validate_casting_response`, `execute_test`,
   `render_test_entry`, `render_onboarding_section`. To reach the SUT, set
   `base_url` and `test_endpoint_path` for a web service, or supply both
   `check_sut_ready` and `fetch_happy_day_example` for anything else.
   `validate_adapter()` (in `engine/adapter.py`) checks all this and raises a
   clear error naming what's missing, before any HTTP/Anthropic calls are made.
3. Register it in `engine/adapters/registry.py`'s `_ADAPTERS` map.
4. Do **not** touch `engine/tools.py` - the hypothesis/Skeptic schema is
   shared across every adapter by design.

Alternatively, `engine/bootstrap/cli.py` can generate a first draft of steps
1-2 automatically by discovering/probing a live SUT for real - see the root
[`README.md`](../README.md#bootstrapping-a-new-adapter-automatically). Still
scoped to the "one request in, one response out" case; still ends with a
manual registration step. Free-text background on the API can also be
supplied (from a file or a mocked ticket store) to inform probing and persist
into the generated adapter - see the root README's "Context-enriched
bootstrap" section.

## Testing

```
pip install -r engine/requirements.txt
python -m pytest engine/tests
```

Runs on every push to `master`, every PR into `master`, and on demand, via
`.github/workflows/engine-tests.yml` - no Anthropic API key needed, since no
test makes a real LLM call. The same workflow compile-checks `engine/` and
runs the `clash-royale-kit` and `.experiments/web-recon` tests.

`.github/workflows/exploratory-run.yml` runs the whole pipeline on a throwaway Juice
Shop with real model calls, by hand or on a PR labelled `run-exploration` (#255). See
the root README.

Most tests (`test_sut_regression.py`, `test_client_retry.py`, the
`*_parity.py` files) run in-process against the mock SUT via FastAPI's
`TestClient` or against stubbed clients. `test_complex_sut_regression.py` is
the one exception: its bug is a genuine concurrency race that depends on
Starlette actually dispatching sync handlers across a real thread pool, so
it spins up a real `uvicorn` subprocess and fires genuine concurrent
requests rather than using the in-process test client.
