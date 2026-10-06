# Lean runs, for experiments (issue #295).
#
# Most runs are experiments: did a change make the engine find more? For that the model
# only has to write what decides a finding. In the local Juice Shop run on 2026-10-05
# ($1.30) the testing story was 22% of the cost and the debrief and reconsideration 19%.
# A lean run skips those, and the free text nothing downstream decides on. Each part can
# be switched back on for an experiment that is about it. A part we want after reading
# a run is asked for afterwards, from the saved run, one call at a time.
#
# Code: engine/lean.py, engine/config.py (lean, lean_with, wants), engine/loop.py,
# engine/runner.py, engine/ask.py, engine/tools.py (the validators' lean flag, ASK_TOOL).
# Tests: engine/tests/test_lean.py

Feature: A lean run asks the model only for what decides a finding
  As someone running experiments on the engine
  I want a run that skips what the experiment doesn't need, and a way to ask for it later
  So that experiments cost less and nothing is lost

  Scenario: A lean run skips the testing story, the debrief and the bug report write-ups
    Given the run was started with --lean
    When a checkpoint runs
    Then the model is called for the casting round, the hypothesis and the Skeptic's review only
    And the checkpoint's "debrief" is empty, and the hypothesis has no "areas" or "obstacles"
    And when the run concludes bugs, the log says no bug reports were written and how to ask for them
    And bug replays, signals, coverage, videos and the known-problems score are kept, since they cost no model calls

  Scenario: A lean run asks for fewer fields
    Given the run was started with --lean
    Then the casting prompt asks for one short sentence of reasoning and one short line per predicted outcome
    And the hypothesis tool has no "behaviors" or "untested", and an observation has no "mechanism" or "why"
    And a prior gap's "reason" isn't asked for
    And the Skeptic's tool has no notes and no "coverage.untouched", but keeps "coverage.material"
    And the Skeptic is told to list only the gaps that block its verdict
    And the Skeptic is not sent the empty lists

  Scenario: The dropped fields come back as empty values
    When a lean hypothesis or review comes in
    Then each dropped field is filled in as an empty list or empty text
    And a field the model sent anyway is kept
    And the report, the summary and the next checkpoint read them as before

  Scenario Outline: A skipped part can be switched back on
    Given the run was started with --lean --with <parts>
    Then the run makes the calls for <parts> and skips the others

    Examples:
      | parts         |
      | story         |
      | debrief       |
      | bug_reports   |
      | story,debrief |

  Scenario: --with is checked
    Then --with without --lean is refused: "--with only works with --lean"
    And an unknown part is refused, with the parts it could be: story, debrief, bug_reports

  Scenario: A lean run says so everywhere
    Then the log starts with "Lean run, for experiments: ..." and what was skipped or switched back on
    And output.json has "lean": {"with": [...]}
    And the run summary starts with "Lean run, for experiments (#295): compare it only with lean runs"
    And the report's header ends with "· lean run", and the parts switched back on

  Scenario: The CI workflow can start a lean run
    Given the exploratory-run workflow is started with the input lean
    Then empty means a full run, "on" means --lean, and parts like "story,debrief" mean --lean --with those parts
    And anything else is refused before anything is installed

  Scenario Outline: A saved run can be asked for a part afterwards
    When someone runs python -m engine.ask <run folder> --adapter <adapter> <what>
    Then one model call answers from the run's saved record: its schema, onboarding, test history and checkpoints
    And the answer is written to <run folder>/asked/<file>, never over an earlier one, and output.json isn't changed
    And the log says where it went and about what it cost

    Examples:
      | what                                | file                                    |
      | --story                             | story-C<the last checkpoint>.json       |
      | --story 2                           | story-C2.json                           |
      | --bug-reports                       | bug-reports.json                        |
      | --question "Why was C3.O1 doubted?" | why-was-c3-o1-doubted.json              |

  Scenario: Asking for something the run doesn't have says so
    Then --bug-reports on a run with no bugs stops with "This run concluded no bugs"
    And --story with a checkpoint the run doesn't have stops with "This run has no checkpoint N"
