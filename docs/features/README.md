# `docs/features/`: what the engine does, one `.feature` per capability

Each file describes one capability of the engine as it works on `master` today, in
Gherkin. A comment at the top says why the capability exists and which code holds it.
The scenarios say what it does, with the real field names, flags and numbers.

These are documentation for now. Nothing runs them: there are no step definitions,
and the unit tests in `engine/tests` are still what checks the behaviour.

Every change in behaviour adds or updates a file here in the same PR, the same way as
a README ([CLAUDE.md](../../CLAUDE.md), workflow step 7). A new capability gets a new
file and a row in the index below.

The game client (`clash_royale`, `clash-royale-kit`) is out of scope and not covered.

## The Driver and Skeptic loop

| File | Feature |
|---|---|
| [`checkpoint_loop.feature`](checkpoint_loop.feature) | A run is a series of checkpoints that each cast, hypothesise and review |
| [`casting.feature`](casting.feature) | The Driver casts a batch of tests in the adapter's own schema |
| [`hypothesis.feature`](hypothesis.feature) | The Driver forms one structured hypothesis per checkpoint |
| [`skeptic_review.feature`](skeptic_review.feature) | A cold Skeptic reviews each checkpoint hypothesis |
| [`gaps.feature`](gaps.feature) | Gaps carry a next test and must be answered at the next checkpoint |
| [`new_ground_and_parking.feature`](new_ground_and_parking.feature) | Later rounds explore new ground, and claims the tests can't settle are parked |
| [`oracle_and_errors.feature`](oracle_and_errors.feature) | The Driver tests from the oracle and answers for every idea and every error |
| [`ids.feature`](ids.feature) | The engine stamps ids on observations and gaps |
| [`word_limits.feature`](word_limits.feature) | Short fields have word limits that only reject far-too-long answers |

## Trusting the result

| File | Feature |
|---|---|
| [`kind_lowering.feature`](kind_lowering.feature) | The engine lowers a kind the evidence doesn't support |
| [`final_status.feature`](final_status.feature) | The engine decides whether each final observation is corroborated |
| [`bug_reports.feature`](bug_reports.feature) | Bugs get a written report that can't change the engine's verdict |
| [`bug_replay.feature`](bug_replay.feature) | A bug's tests are replayed before it is reported |

## Run diagnostics and coverage

| File | Feature |
|---|---|
| [`outcome_envelope.feature`](outcome_envelope.feature) | Adapters describe each test result in a typed outcome envelope |
| [`run_diagnostics.feature`](run_diagnostics.feature) | The engine checks the run's own mechanics after every batch |
| [`test_coverage.feature`](test_coverage.feature) | The Skeptic gets the values each input field has been sent |

## The model client

| File | Feature |
|---|---|
| [`tool_call_retry.feature`](tool_call_retry.feature) | Every model call is a forced tool call, checked and retried with feedback |
| [`api_error_retry.feature`](api_error_retry.feature) | Transient API errors are retried with backoff, permanent ones fail at once |
| [`prompt_caching.feature`](prompt_caching.feature) | The static prompt and the growing test history are cached |
| [`model_provider.feature`](model_provider.feature) | The engine uses the direct API or Bedrock, with a model to match |
| [`usage_logging.feature`](usage_logging.feature) | Every model response's token use is logged and summed per call type |

## Running a run, and its output

| File | Feature |
|---|---|
| [`run_command.feature`](run_command.feature) | One command runs a session against an adapter |
| [`lean_runs.feature`](lean_runs.feature) | A lean run asks the model only for what decides a finding |
| [`readiness.feature`](readiness.feature) | The engine checks the SUT is up and fetches one real example before spending anything |
| [`run_persistence.feature`](run_persistence.feature) | Progress is saved after every checkpoint |
| [`run_output.feature`](run_output.feature) | A run writes a JSON result, a bug list when there are bugs, and an HTML report |
| [`html_report.feature`](html_report.feature) | The HTML report puts the conclusion first and folds the details |
| [`history_redaction.feature`](history_redaction.feature) | The test history shown to the model is redacted |

## The adapter contract

| File | Feature |
|---|---|
| [`adapter_contract.feature`](adapter_contract.feature) | Any system can be tested through one SUTAdapter |
| [`adapter_registry.feature`](adapter_registry.feature) | Adapters are registered by a person and loaded by name, lazily |

## Web testing: the web_gui adapter

| File | Feature |
|---|---|
| [`web_readiness.feature`](web_readiness.feature) | The web_gui adapter checks its map and the live app before a run starts |
| [`web_action_space.feature`](web_action_space.feature) | A web test is a start and a few steps on the live page |
| [`web_careful.feature`](web_careful.feature) | A web run tests fully, except where the target is tagged careful |
| [`web_path_replay.feature`](web_path_replay.feature) | Each test reaches its state by replaying the mapped path |
| [`web_settling.feature`](web_settling.feature) | Reads wait for a settled page |
| [`web_actuation.feature`](web_actuation.feature) | Controls are pressed by role and name, and a cover is reported |
| [`web_stays_on_site.feature`](web_stays_on_site.feature) | The test browser never leaves the product's site |
| [`web_transition_classification.feature`](web_transition_classification.feature) | Tests predict the kind of move, and each move is classified against the map |
| [`web_dead_controls.feature`](web_dead_controls.feature) | Dead controls are told apart from visual changes |
| [`web_recovery.feature`](web_recovery.feature) | The browser recovers after reaching a new screen |
| [`web_discoveries.feature`](web_discoveries.feature) | Screens beyond the map are recorded and join the run's map |
| [`web_report.feature`](web_report.feature) | The web report and log show each move and its signals |
| [`test_videos.feature`](test_videos.feature) | The tests a run rests on can be watched |

## Web testing: signals

| File | Feature |
|---|---|
| [`web_signals.feature`](web_signals.feature) | Each action records what changed around it |
| [`web_signal_trust.feature`](web_signal_trust.feature) | Only trustworthy signals count as evidence |
| [`web_idle_noise.feature`](web_idle_noise.feature) | The engine learns each state's idle noise |
| [`web_signal_audit.feature`](web_signal_audit.feature) | Signal handling can be audited on a live site |

## Web testing: sessions and logins

| File | Feature |
|---|---|
| [`saved_session.feature`](saved_session.feature) | web_gui tests start from a saved login session |
| [`save_session.feature`](save_session.feature) | A session is saved by logging in by hand, or when a condition holds |
| [`session_freshness.feature`](session_freshness.feature) | A stale saved session is refused before a run |
| [`new_tab_start.feature`](new_tab_start.feature) | A web_gui test can start as a new tab of the logged-in browser |
| [`learn_between_runs.feature`](learn_between_runs.feature) | A run starts from the screens earlier runs discovered, and learns for the next one |
| [`pipeline_in_ci.feature`](pipeline_in_ci.feature) | The whole pipeline runs in GitHub Actions and reports as an artifact |
| [`spending_limit.feature`](spending_limit.feature) | A run stops itself at a spending limit |
| [`driver_skeptic_interplay.feature`](driver_skeptic_interplay.feature) | Every run measures how well the Driver answered the Skeptic |
| [`skeptic_memory.feature`](skeptic_memory.feature) | The Driver is told what the Skeptic objected to most in earlier runs |
| [`testing_story.feature`](testing_story.feature) | The Driver tells its testing story, and the Skeptic debriefs it |
| [`checkpoint_debrief.feature`](checkpoint_debrief.feature) | Each checkpoint ends with a debrief the Driver has to win with evidence |
| [`web_sweep.feature`](web_sweep.feature) | A sweep runs every reachable action once and lists what the harness observed |
| [`run_score.feature`](run_score.feature) | A run is scored against a target's known problems |

## Web testing: mapping a site

| File | Feature |
|---|---|
| [`spoor_conversion.feature`](spoor_conversion.feature) | A Spoor map is converted into web_gui's site map by replaying it live |
| [`spoor_contract.feature`](spoor_contract.feature) | CI checks Spoor's saved map against what from_spoor reads |
| [`recon_crawl.feature`](recon_crawl.feature) | The read-only crawler maps a site from its start URL |
| [`recon_safety_gate.feature`](recon_safety_gate.feature) | The crawler's safety gate only allows non-committing actions |
| [`recon_state_identity.feature`](recon_state_identity.feature) | Screens are identified by a signature |
| [`recon_findings.feature`](recon_findings.feature) | The crawler reports functional and structural problems |
| [`recon_wiki.feature`](recon_wiki.feature) | The crawler writes an HTML wiki of the map |

## Oracle and prioritization

| File | Feature |
|---|---|
| [`heuristic_library.feature`](heuristic_library.feature) | A tagged library of testing heuristics, one file per source |
| [`heuristic_selection.feature`](heuristic_selection.feature) | Heuristics are picked by surface and feature |
| [`oracle_ranking.feature`](oracle_ranking.feature) | Test ideas are ranked by what's already known about them |
| [`spoor_context.feature`](spoor_context.feature) | A Spoor map becomes the product's screens, and the oracle builds on them |
| [`oracle_feedback.feature`](oracle_feedback.feature) | A run's results feed back into the next ranking |
| [`discovery_memory.feature`](discovery_memory.feature) | Screens found beyond the map are remembered across runs |
| [`product_layer.feature`](product_layer.feature) | A product's surfaces, features and facts are read from its wiki |
| [`oracle_seeder.feature`](oracle_seeder.feature) | A product's oracle is built from its wiki through the FEW HICCUPPS seeds |
| [`oracle_selection.feature`](oracle_selection.feature) | Each adapter chooses its oracle, and either can turn it off |
| [`oracle_views.feature`](oracle_views.feature) | The ranked oracle and its layers can be viewed in HTML |

## Adapter bootstrap for HTTP APIs

| File | Feature |
|---|---|
| [`bootstrap_pipeline.feature`](bootstrap_pipeline.feature) | A draft adapter is bootstrapped from a live HTTP API |
| [`schema_discovery.feature`](schema_discovery.feature) | The schema is read from the API's own OpenAPI document |
| [`freetext_schema.feature`](freetext_schema.feature) | A schema is drafted from free text when discovery finds nothing |
| [`probing.feature`](probing.feature) | The draft schema is checked by probing the live API |
| [`adapter_generation.feature`](adapter_generation.feature) | A probing result is turned into a draft adapter |
| [`bootstrap_context.feature`](bootstrap_context.feature) | Background context feeds probing and the generated adapter |

## Reference SUTs and test targets

| File | Feature |
|---|---|
| [`token_purchase_sut.feature`](token_purchase_sut.feature) | A mock purchase API with real decline rules to test against |
| [`complex_sut.feature`](complex_sut.feature) | A rate-limited API with a planted race to test against |
| [`scoring_rubrics.feature`](scoring_rubrics.feature) | Each reference SUT has a rubric to score runs by hand |
| [`test_targets.feature`](test_targets.feature) | Real web apps run locally as test targets |

## Product wiki and CI

| File | Feature |
|---|---|
| [`product_wiki.feature`](product_wiki.feature) | A product wiki describes the product under test |
| [`engine_ci.feature`](engine_ci.feature) | CI checks the engine on every pull request |
