# Run persistence: output.json is rewritten after every checkpoint.
#
# A run spends real money on every checkpoint. A crash partway through (a
# non-retryable API error, a bug in the engine) used to lose every checkpoint that
# had already finished. Now the checkpoint loop calls back after each checkpoint,
# and the runner writes a full snapshot of the run so far, marked "in_progress".
#
# The mid-run save goes to output.json.tmp first and is then moved over
# output.json, so a crash during the write can't leave half a file behind. When
# the run ends, for any reason, output.json is written once more with the real
# stopped_reason.
#
# Code: engine/runner.py (save_progress), engine/loop.py (on_checkpoint)

Feature: Progress is saved after every checkpoint
  As someone running long sessions
  I want output.json rewritten safely after each checkpoint
  So that a crash or a stop keeps every checkpoint that already finished

  Scenario: Each finished checkpoint triggers a full snapshot
    Given a run with "max_checkpoints" 3
    When checkpoint 1 and then checkpoint 2 complete
    Then the loop calls on_checkpoint twice, first with 1 checkpoint and then with 2
    And each call carries the whole casting log and every checkpoint so far

  Scenario: A mid-run save is marked in progress
    When the runner saves progress after a checkpoint
    Then output.json has "casting_log", "checkpoints", "usage_log" and "usage_summary" as they are so far
    And "stopped_reason" is "in_progress"

  Scenario: The mid-run save is atomic
    When the runner saves progress after a checkpoint
    Then it writes "output.json.tmp" in the output folder
    And then replaces "output.json" with it

  Scenario Outline: An error ends the run but keeps the saved checkpoints
    Given a run where checkpoint 2's Skeptic call fails with <error>
    When the run ends
    Then output.json has "stopped_reason" "error" and the message under "error"
    And output.json still has checkpoint 1
    And the console shows "<console>"
    And report.html is still written
    # The unexpected kind also prints the full traceback, since it is worth debugging.

    Examples:
      | error                                  | console                                       |
      | a RuntimeError from spent retries      | Stopped early: ...                            |
      | any other exception, e.g. a ValueError | Stopped early due to an unexpected error: ... |

  Scenario: A finished run replaces the in-progress marker
    Given a run that ends with stopped_reason "skeptic_satisfied"
    When the run ends
    Then output.json has "stopped_reason" "skeptic_satisfied"

  Scenario: A failed bug report doesn't turn a finished run into an error
    # The loop has already reached its verdict, so the run keeps it.
    Given a run that finished with a bug
    And writing the bug report fails
    When the run ends
    Then "stopped_reason" is still the loop's reason
    And output.json has the failure under "bug_report_error"
    And no bugs.json is written
