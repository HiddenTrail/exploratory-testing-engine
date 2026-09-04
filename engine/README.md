# AI Exploratory Testing Engine

A reusable Driver+Skeptic checkpoint-loop harness, hardened from four rounds
of experimentation in `experiments/` (kept there as an untouched historical
archive - this package is a port, not a rewrite). See
`docs/exploratory-testing-engine-concept.md` for the original vision this is
one deliberately narrow slice of.

## What it does

Against a live SUT, each checkpoint:
1. **Casts** a batch of real tests (an adapter-defined test-proposal schema),
   executes them for real, and records predicted vs. actual outcomes.
2. Forms **one hypothesis** about the system's behavior and any anomalies
   noticed (zero, one, or several) - a specific, falsifiable claim per
   anomaly, not a vague suspicion.
3. Gets a **cold Skeptic review** of that hypothesis - a second LLM call that
   never sees the raw test data, only the hypothesis itself. It checks
   whether the cited evidence actually discriminates a claim from its own
   named rival (not just whether evidence exists), tracks whether its own
   prior critique was actually addressed across checkpoints, and gives a
   `weak` (keep going) or `strong_enough` (stop) verdict.
4. The loop continues on `weak`, informed by the critique, or stops on
   `strong_enough` or a checkpoint cap.

If the final hypothesis claims anomalies, a bug report is written per claim -
honestly marked `inconclusive` if the checkpoint budget ran out while the
Skeptic still had objections, `corroborated` only if it was satisfied.

**Known, accepted limitation:** the Skeptic's per-anomaly `discriminates_from_rival`
check (in `anomaly_checks`) doesn't account for realistic value rounding/precision
when deciding whether cited evidence discriminates a claim from its rival - see
the comment on that field in `engine/tools.py`. Carried forward deliberately, not fixed.

`engine/adapters/token_purchase/adapter.py` also pulls its onboarding
evidence's oracle content from `engine/ontology/` - a ranked, prioritized
test-idea list rather than the old flat claim dump - see the root README's
"Ontology layer" section and `docs/ontology-todo.md` for what's proven and
what's still open (claim matching between a Driver-written hypothesis and an
oracle claim is currently exact-string only, so re-ranking doesn't yet
reflect a run's actual results).

## Layout

```
engine/
  adapter.py    # SUTAdapter interface - what a per-SUT adapter must supply
  tools.py      # HYPOTHESIS_TOOL / SKEPTIC_TOOL / BUG_REPORT_TOOL - domain-agnostic, not adapter-overridable
  client.py     # Anthropic client + call_tool_with_retry
  loop.py       # the checkpoint loop itself
  outcome.py    # the typed envelope an adapter puts on each result - the only SUT vocabulary the engine reads
  diagnostics.py # domain-free detectors over those envelopes: facts about the RUN, not the SUT
  report.py     # generic HTML rendering (prose, badges, CSS, page/checkpoint structure)
  runner.py     # orchestrates one full run: readiness probe, loop, bug reports, file output
  cli.py        # python -m engine.cli --adapter <name>
  adapters/
    registry.py           # name -> adapter module, resolved lazily
    token_purchase/        # first adapter, ported from experiments/token-purchase-poc
    complex_sut/            # second adapter - concurrency/rate-limiting domain
    clash_royale/           # third adapter - a live game client, not a web service. Read actions.py first
                            #   known_screens.json is measured data, not configuration: eleven screens a
                            #   game-ontology recon pass fingerprinted against this client, extracted by
                            #   extract_reference.py and loaded by reference.py. Four are classified
                            #   "abort", which is what lets a run notice it has reached the shop
  bootstrap/                # generate a draft adapter from a live SUT - see below  ontology/                  # prioritization layer stack (heuristics/domain/context/ranked oracle) - see root README  tests/                    # deterministic regression + parity tests (no LLM calls)
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
anomalies were found), and `runs/<adapter>/report.html`. Override run
parameters with `--model`, `--max-checkpoints`, `--first-round-budget`,
`--default-budget`, `--out-dir`.

### Authenticating through Bedrock instead of an API key

Set `ENGINE_USE_BEDROCK=1` plus `AWS_REGION` (and `AWS_PROFILE`, if it isn't
your default) instead of `ANTHROPIC_API_KEY`. Credentials then come from the
normal AWS chain - SSO cache, profile, env vars, instance role - so there is no
long-lived key in the repo or the environment.

The default model changes with the provider, because Bedrock names models
differently. Two important details:

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

1. Create `engine/adapters/<name>/` with your mock SUT and an `adapter.py`.
2. In `adapter.py`, define the genuinely per-SUT pieces and build one
   `ADAPTER = SUTAdapter(...)` instance - see
   `engine/adapters/token_purchase/adapter.py` for a complete worked example.
   Required fields: `name`, `display_name`, `base_url`, `test_endpoint_path`,
   `casting_tool_schema`, `casting_system_prompt`, `validate_casting_response`,
   `execute_test`, `render_test_entry`, `render_onboarding_section`.
   `validate_adapter()` (in `engine/adapter.py`) checks these are present and
   raises a clear error naming what's missing, before any HTTP/Anthropic
   calls are made.
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

Runs automatically on every push to `master` and every PR via
`.github/workflows/engine-tests.yml` - no Anthropic API key needed, since no
test makes a real LLM call.

Most tests (`test_sut_regression.py`, `test_client_retry.py`, the
`*_parity.py` files) run in-process against the mock SUT via FastAPI's
`TestClient` or against stubbed clients. `test_complex_sut_regression.py` is
the one exception: its bug is a genuine concurrency race that depends on
Starlette actually dispatching sync handlers across a real thread pool, so
it spins up a real `uvicorn` subprocess and fires genuine concurrent
requests rather than using the in-process test client.
