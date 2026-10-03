# Run output: what a finished run leaves in its output folder.
#
# Every run writes output.json (everything the run saw and concluded) and a
# self-contained report.html. A bugs.json is added only when there were bugs to
# write up: findings and anomalies are already complete in output.json's
# "observations", so they need no extra model call. The folder is runs/<adapter>
# unless --out-dir says otherwise.
#
# "anomaly_found" is true only when the final checkpoint has a real problem in it,
# an anomaly or a bug. Findings alone don't count.
#
# Code: engine/runner.py (run)

Feature: A run writes a JSON result, a bug list when there are bugs, and an HTML report
  As someone reading results
  I want the run's facts in output.json, its bug reports in bugs.json and a report.html to read
  So that both people and other tools can use what the run found

  Scenario: output.json holds the onboarding, the log, the checkpoints and the conclusion
    When a run finishes without an error
    Then output.json has "api_schema", "onboarding_extra" and "happy_day_example"
    And it has "casting_log", "checkpoints" and "stopped_reason"
    And it has "observations", the final checkpoint's observations, each with the status the engine gave it
    And it has "anomaly_found", "usage_log" and "usage_summary"
    And it has "replays" and "replay_log", the bug replays (see bug_replay.feature)
    And it has "interplay", how well the Driver answered the Skeptic (see driver_skeptic_interplay.feature)
    And each checkpoint has "debrief", the recorded exchange after the Skeptic's review (see checkpoint_debrief.feature)

  Scenario Outline: stopped_reason says why the run ended
    When the run ends because <cause>
    Then output.json has "stopped_reason" "<reason>"

    Examples:
      | cause                                             | reason                    |
      | the Skeptic gave the verdict "strong_enough"      | skeptic_satisfied         |
      | the checkpoint cap was reached                    | checkpoints_exhausted     |
      | a "stop" run diagnostic with code "reset_failing" | diagnostics_reset_failing |
      | an exception ended the loop                       | error                     |

  Scenario Outline: anomaly_found is true only for an anomaly or a bug
    Given the final observations include <kinds>
    When the run finishes
    Then "anomaly_found" is <found>

    Examples:
      | kinds                  | found |
      | only findings          | false |
      | no observations at all | false |
      | an anomaly             | true  |
      | a bug and a finding    | true  |

  Scenario: bugs.json is written only when bug reports were written
    Given the final observations include 2 bugs
    When the run writes its bug reports
    Then the console shows "Writing bug reports for 2 bugs..."
    And bugs.json holds 2 reports, each with the "kind", "severity" and "status" of its observation
    And the console shows "Wrote 2 bug report(s) to" and the bugs.json path
    But a run with no bugs makes no bug report call and writes no bugs.json

  Scenario: report.html is always written
    When a run ends, with or without an error
    Then report.html is written next to output.json as UTF-8
    And the console shows "Wrote result to" with the output.json path and "Wrote report to" with the report path

  Scenario Outline: The closing console line depends on what the run found
    Given a run that ended <how>
    When the run has written its files
    Then the last line is <line>

    Examples:
      | how                      | line                                                                                                |
      | with anomaly_found true  | "Now score it by hand against rubric.md."                                                           |
      | with anomaly_found false | "No anomaly or bug found. See checkpoints for the final hypothesis and the Skeptic's review of it." |
      | with an error            | "Wrote report to" and the report path, with no closing verdict line                                 |
