# Written bug reports, for bugs only.
#
# Once the loop has concluded, every final observation of kind "bug" gets a
# written report from one model call. Findings and anomalies are already complete
# in output.json "observations" and need no call. The reports keep the real
# values from the test history, because a developer needs literal repro steps.
#
# The model writes the text only. Kind, severity and status are copied from the
# observation afterwards, so a report can't contradict the engine's verdict. And
# the call is isolated from the run: if it fails (for example, retries used up on
# a max_tokens cutoff), the run keeps its verdict and records "bug_report_error"
# instead of turning a finished run into an "error".
#
# Code: engine/loop.py (get_bug_reports), engine/runner.py (run),
# engine/tools.py (BUG_REPORT_TOOL, validate_bug_reports)

Feature: Bugs get a written report that can't change the engine's verdict
  As someone handing results to developers
  I want one report per bug with title, description, repro steps, expected and actual behaviour and caveats
  So that bugs arrive ready to read, and a failed or wayward report never spoils the run's result

  Scenario: Only bugs get a report, from one model call
    # Bugs are replayed first (bug_replay.feature). One that doesn't reproduce is an
    # anomaly by now, so it gets no report.
    Given the final observations are "C3.O1" a "bug", "C3.O2" an "anomaly" and "C3.O3" a "finding"
    When the runner writes bug reports
    Then it makes one "submit_bug_reports" call for "C3.O1" only
    And the reports are written to "bugs.json"

  Scenario: A run with no bugs makes no bug-report call
    Given the final observations have no "bug"
    When the run finishes
    Then no "submit_bug_reports" call is made
    And no "bugs.json" is written

  Scenario: The bug-report call gets the bugs, their blocking gaps and the full test history
    Given bug "C3.O1" and a final Skeptic review with gaps
    When the engine builds the bug-report evidence
    Then it holds "bugs", "blocking_gaps", "stopped_reason" and "all_tests_this_session"
    And "blocking_gaps" has only gaps with "blocks_verdict" true whose "about" names a bug
    # The history goes through the adapter's history redaction. The default one only
    # drops bookkeeping like round_reasoning, so the literal test values stay in.

  Scenario: Each report has a fixed set of fields
    Given the model answers "submit_bug_reports"
    Then each entry has "observation_id", "title", "description", "steps_to_reproduce", "expected_behavior", "actual_behavior" and "caveats"
    And "steps_to_reproduce" must be a non-empty list
    And there must be exactly one entry per bug id, and none for an id that isn't a bug

  Scenario Outline: Report fields have word limits, rejected only above twice the limit
    Given a bug report whose <field> has <words> words
    When validate_bug_reports checks it
    Then it is <result>

    Examples:
      | field                 | words | result   |
      | title                 | 30    | accepted |
      | title                 | 31    | rejected |
      | description           | 120   | accepted |
      | description           | 121   | rejected |
      | each step             | 61    | rejected |
      | expected_behavior     | 61    | rejected |
      | actual_behavior       | 61    | rejected |
      | caveats               | 100   | accepted |
      | caveats               | 101   | rejected |

  Scenario Outline: The number of repro steps is limited to 8, rejected above 16
    Given a bug report with <steps> steps to reproduce
    When validate_bug_reports checks it
    Then it is <result>

    Examples:
      | steps | result   |
      | 0     | rejected |
      | 8     | accepted |
      | 16    | accepted |
      | 17    | rejected |

  Scenario: Kind, severity and status are copied from the observation
    Given bug "C3.O1" has severity "high" and status "inconclusive"
    And the model's report for "C3.O1" includes "severity" "low" and "status" "corroborated"
    When the engine builds the final report
    Then the report has kind "bug", severity "high" and status "inconclusive"

  Scenario: A failed bug-report call leaves the run's verdict alone
    Given the run concluded with stopped_reason "skeptic_satisfied" and one bug
    When the bug-report call raises an error
    Then output.json has "bug_report_error" with the error text
    And stopped_reason stays "skeptic_satisfied" and "anomaly_found" stays true
    And output.json has no "error"
    And no "bugs.json" is written
