# The HTML report: one self-contained page per run, conclusions first.
#
# report.html lays out everything in output.json (and bugs.json, if there is one)
# for a person to read, instead of scrolling raw JSON. The generic parts (hero,
# checkpoints, diagnostics, conclusion, bug reports, CSS) live in the engine. The
# per-SUT parts, how to draw one test entry and the onboarding section, come from
# the adapter's render_test_entry and render_onboarding_section.
#
# Each checkpoint shows how its claims came out (#342) and one line per observation and gap up front,
# and folds the evidence and the tests underneath. Run diagnostics come from the
# last checkpoint only, because each checkpoint's set already covers the whole log
# up to that point. A report can be rebuilt from saved files, which is how a report
# change is checked without paying for a new run.
#
# Code: trailhound/report.py (render_report, render_report_from_dir)

Feature: The HTML report puts the conclusion first and folds the details
  As someone reading a run's results
  I want the verdict and what was found at the top, and how it was found folded below
  So that I see what the run found before I read how it got there

  Scenario Outline: The hero at the top depends on how the run ended
    Given a run output where <state>
    When the report is rendered
    Then the hero's eyebrow is <eyebrow> and its heading is <title>
    And the stats are <stats>

    Examples:
      | state                        | eyebrow                         | title                                                                                                                                                                                                | stats                                                                                                    |
      | "error" is set               | "Run incomplete"                | "Stopped early"                                                                                                                                                                                      | the error cut to 40 characters, labelled "reason"                                                        |
      | there are final observations | counts like "1 bug, 2 findings" | the most serious confirmed thing: the most severe bug report's title, else the most severe corroborated bug or anomaly; else "No confirmed problem", with the known-problems score when there is one | "checkpoints run", "tests executed", "corroborated", and "known problems found" when the run has a score |
      | there are no observations    | "Checkpoints concluded"         | "Nothing looked wrong"                                                                                                                                                                               | "checkpoints run", "tests executed" and "stopped because"                                                |

  Scenario Outline: The top bar links only to the sections the run has
    Given a run output with <content>
    When the report is rendered
    Then the top bar has a "<link>" link to "<anchor>"

    Examples:
      | content                 | link               | anchor       |
      | a testing story         | Where it stands    | #standing    |
      | anything                | Schema             | #schema      |
      | tests or checkpoints    | Checkpoints        | #casting     |
      | at least one checkpoint | Driver and Skeptic | #interplay   |
      | at least one checkpoint | Diagnostics        | #diagnostics |
      | final observations      | Conclusion         | #conclusion  |
      | at least one bug report | Bug report         | #bug-report  |

  Scenario: Each checkpoint shows its conclusion and folds the rest
    Given a checkpoint with a hypothesis, a Skeptic review and 4 tests
    When the report is rendered
    Then the checkpoint heading shows its number and how its claims came out, like "Checkpoint 2: 1 of 2 claim(s) hold up, 1 inconclusive" (see claim_results.feature)
    And the Skeptic's verdict is a badge in the Skeptic's line
    And the Driver's summary, the Skeptic's reason, one line per observation and one line per gap are visible
    And a fold "Details: evidence, coverage and prior gaps" holds behaviours, observation details, untested areas, coverage and prior-gap answers
    And a fold "Tests this checkpoint (4)" holds the tests, drawn by the adapter's render_test_entry
    And when the last casting attempt dropped tests (#288), the fold says "(4, 1 dropped)" and lists each one with its errors
    # A checkpoint with no observations says "Nothing looked wrong this checkpoint."

  Scenario: A checkpoint with no conclusion still shows its tests
    Given tests from checkpoint 3 but no checkpoint 3 record
    When the report is rendered
    Then checkpoint 3 is shown with its tests fold only

  Scenario: A checkpoint where the Driver gave up is still shown
    # It has no tests in the casting log, but it still has a hypothesis and a review.
    Given checkpoint 2 has a record but no tests
    When the report is rendered
    Then checkpoint 2 is shown with its conclusion
    And its tests fold says no rounds were executed because the Driver gave up

  Scenario: Run diagnostics come from the last checkpoint
    Given 3 checkpoints, each with a "diagnostics" list
    When the report is rendered
    Then the "Run diagnostics" section shows only checkpoint 3's findings, each with severity, code, headline, tests and detail
    And with no findings it says "No run-level findings: ..." instead of staying blank
    And with no checkpoints at all the section is left out

  Scenario: The conclusion and bug reports follow the diagnostics
    Given final observations and 1 bug report
    When the report is rendered
    Then the "Findings, anomalies and bugs" section lists each observation with its status and the Skeptic's note
    And a bug that was replayed carries its replay badge (see bug_replay.feature)
    And the "Bug report" section shows the report's title, severity, status, description, steps, expected and actual behaviour and caveats

  Scenario: "Where it stands" is collapsible and short
    # #285: walked through a real report; the old table was crowded and its tags wrapped.
    Then "Where it stands" is a fold, open by default, titled with how many areas it has
    And each area has its approach and oracle, its coverage as a level tag (L1, L2, L3) with what it was of and what wasn't tested, and one status tag such as "OK so far · medium"
    And the "Why" column is only in each checkpoint's own story
    And each obstacle shows who could help: the engine, the map, test data or the product

  Scenario: What came of the oracle's ideas
    Given the Driver was given ranked oracle ideas
    Then a folded section lists each idea, the tests that cited it, how many came out as predicted, the final observations those tests support, and the Driver's answer: held, broke or cannot tell (#312)
    And its title says how many of the ideas were tested at all

  Scenario: A glossary explains the tags the report uses
    Then the report ends with a folded glossary of only the tags that appear in this run: kinds, statuses, coverage levels, what's been seen, confidence, the Skeptic's questions, its check on each observation, the debrief's stances, judgements and outcomes, and replay verdicts
    And the check on each observation shows "tells it from its rival" or "doesn't tell it from its rival": whether a test's result would differ depending on whether the claim or its rival explanation is true (#343)
    And the meanings come from the same definitions the engine and its prompts use

  Scenario: A report can be rebuilt from a saved run folder
    Given a run folder with output.json and no bugs.json
    When render_report_from_dir is called with the folder and the adapter
    Then it returns the same report render_report gives for that output and no bug reports
    And when bugs.json is there, its reports are included
