# The checkpoint loop: the core of every run.
#
# A run is a series of checkpoints. In each one the Driver casts a batch of tests,
# the adapter runs them against the live SUT, the Driver forms one hypothesis from
# everything so far, and a cold Skeptic reviews it. A "weak" verdict sends the
# review back into the next casting round. A "strong_enough" verdict ends the run.
# The first round gets its own, bigger test budget because it explores wide, and
# later rounds close the gaps the Skeptic named.
#
# The one other exit is a run diagnostic with severity "stop" (today only
# "reset_failing"): a run that can't get back to its own baseline can't tie a
# result to the action that was sent, so more tests would be wasted money.
#
# Code: trailhound/loop.py (run_checkpoint_loop), trailhound/config.py, trailhound/runner.py

Feature: A run is a series of checkpoints that each cast, hypothesise and review
  As someone exploring a live system
  I want the engine to work in checkpoints that each run tests, form a claim and have it challenged
  So that every claim is tested and reviewed, and a settled run stops spending money

  Scenario Outline: The first checkpoint uses the first-round budget, later ones the default budget
    Given a run with "first_round_test_budget" 10 and "default_test_budget" 6
    When checkpoint <checkpoint> asks the Driver for a casting round
    Then the casting call gets a test budget of <budget>
    And the casting prompt is built with is_first_round <first>

    Examples:
      | checkpoint | budget | first |
      | 1          | 10     | true  |
      | 2          | 6      | false |
      | 3          | 6      | false |

  Scenario: Budgets and the checkpoint cap come from the adapter unless the CLI overrides them
    # RunConfig layers an engine fallback, then the adapter's suggested defaults, then CLI flags.
    Given an adapter that suggests its own checkpoint cap and test budgets
    When the run starts with "--max-checkpoints 3 --first-round-budget 10 --default-budget 6"
    Then the run uses 3 checkpoints, a first-round budget of 10 and a default budget of 6
    # A 0 on the CLI reads as "not given" and falls back to the adapter's value.
    And a negative value for any of them is refused before the run starts

  Scenario: Each checkpoint is recorded with its hypothesis, review, coverage and diagnostics
    Given a checkpoint whose tests have run
    When the Skeptic has reviewed the hypothesis
    Then the checkpoint record holds "checkpoint", "hypothesis", "skeptic_review", "test_coverage" and "diagnostics"
    And the run writes a full snapshot of the casting log and checkpoints so far
    # Written after every checkpoint, so a crash later in the run keeps what already finished.
    And the partial output.json has stopped_reason "in_progress"

  Scenario: A weak verdict sends the hypothesis and review into the next casting call
    Given checkpoint 1 ended with the Skeptic's verdict "weak"
    When checkpoint 2 asks the Driver for a casting round
    Then its evidence has "prior_checkpoint_feedback" with checkpoint 1's "hypothesis" and "skeptic_review"
    And the run diagnostics from checkpoint 1 travel under their own key "run_diagnostics"
    And the first checkpoint's casting call has neither of them

  Scenario Outline: The run ends for one of three reasons
    Given a run with "max_checkpoints" 3
    When <what happens>
    Then the run stops with stopped_reason "<stopped_reason>"

    Examples:
      | what happens                                                         | stopped_reason            |
      | the Skeptic's verdict on checkpoint 2 is "strong_enough"             | skeptic_satisfied         |
      | checkpoint 2's diagnostics include a "stop" finding "reset_failing"  | diagnostics_reset_failing |
      | all 3 checkpoints end with the verdict "weak" and no stop finding    | checkpoints_exhausted     |

  Scenario: A diagnostics stop still finishes the checkpoint that raised it
    # The batch was already run and paid for, and its hypothesis and review are the
    # best account of what went wrong. Stopping saves the checkpoints after it.
    Given checkpoint 2's batch produced a run diagnostic with severity "stop"
    When the loop reaches the end of checkpoint 2
    Then checkpoint 2 still has its hypothesis and Skeptic review
    And no checkpoint 3 is cast

  Scenario: A strong_enough verdict wins over a stop finding in the same checkpoint
    Given checkpoint 2's diagnostics include a "stop" finding
    And the Skeptic's verdict on checkpoint 2 is "strong_enough"
    When the loop checks its exits
    Then the run stops with stopped_reason "skeptic_satisfied"

  Scenario: A run that crashes keeps the checkpoints it finished
    Given checkpoint 1 finished and was saved
    When checkpoint 2 raises an error the client can't retry
    Then output.json has stopped_reason "error" and the error text under "error"
    And checkpoint 1 is still in the output
