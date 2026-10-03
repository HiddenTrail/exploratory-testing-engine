# How well the Driver answered the Skeptic, measured in every run (issue #257).
#
# The epic "Driver strategy" (#262) wants a Driver that answers objections before they
# are made. Without numbers that's a feeling, so every run now counts, from its own
# checkpoints and with no model call, how the two got on. In milestone run 3 the Skeptic
# objected to the same unexplained "Next page" result in all three checkpoints, and the
# Driver left the blocking gap "not attempted" twice; these numbers make that visible
# without reading the log. Every later change in the epic is judged by them.
#
# Code: engine/interplay.py (measure, summary_lines), engine/runner.py,
# engine/report.py (_render_interplay_section), engine/run_summary.py.
# Tests: engine/tests/test_interplay.py

Feature: Every run measures how well the Driver answered the Skeptic
  As someone making the Driver smarter
  I want each run to count the Skeptic's objections and the Driver's answers
  So that a change to the Driver's strategy can be shown to help, or not

  Scenario: Each checkpoint is counted
    When a run's checkpoints are measured
    Then each checkpoint has its verdict, the gaps the Skeptic raised and how many blocked the verdict
    And how the Driver answered the previous checkpoint's gaps: tested, untestable, resolved, not attempted
    And how many blocking gaps it left "not attempted"
    And how many of its answers the Skeptic accepted, out of how many it judged
    And how many claims the Skeptic objected to, and how many of those it objected to in the checkpoint before

  Scenario: An objection is followed through 'continues'
    # An objection is a blocking gap about an observation, or an observation check that
    # says its evidence doesn't tell it from its rival.
    Given C1.O2, then C2.O2 continuing it, then C3.O2 continuing that, each objected to
    When the run is measured
    Then they count as one claim, "C1.O2", objected to 3 checkpoints in a row
    And it is listed under "stubborn_objections" as ["C1.O2", 3]

  Scenario: Only a gap that blocked the verdict counts as a blocking gap left unattempted
    Given checkpoint 1 raised C1.G2 blocking the verdict and C1.G3 not blocking it
    And checkpoint 2 answered both "not_attempted"
    Then checkpoint 2 has 1 blocking gap not attempted

  Scenario: The debrief is counted too
    # See checkpoint_debrief.feature (#266). The gaps and checks counted above are the
    # ones after the debrief.
    Then each checkpoint has "debrief": questions, defended, conceded, changed_approach, convinced, partly and open_after
    And the run totals them, and lists under "still_open" the questions the last debrief left open
    And the summary says how the Driver answered and how often the Skeptic was convinced

  Scenario: The run says when the Skeptic was satisfied
    Then "satisfied_at" is the first checkpoint whose verdict was "strong_enough"
    And it is empty when the Skeptic never was

  Scenario: The numbers are in the output, the report and the CI summary
    When a run ends, however it ends
    Then output.json has "interplay", measured from the checkpoints that finished
    And the report has a "How the Driver answered the Skeptic" section, linked as "Driver and Skeptic", with the run's sentences and a row per checkpoint
    And a checkpoint with no earlier gaps to answer shows "none"
    And the CI run summary has a "The Driver and the Skeptic" line with the same sentences
    And the report computes it from the checkpoints, so runs made before #257 show it too

  Scenario: A checkpoint cut short doesn't break the count
    Given a checkpoint with no hypothesis or no Skeptic review
    Then it counts as a checkpoint with nothing in it
