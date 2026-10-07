# The final status of each observation, decided by the engine.
#
# A run's conclusion is the final checkpoint's observations, each marked
# "corroborated" or "inconclusive". No model decides this. The engine reads the
# Skeptic's last review: an observation is corroborated only when its check says
# the evidence discriminates it from its rival and no blocking gap is about it.
# Anything else is inconclusive, so a result that wasn't confirmed is never shown
# as confirmed.
#
# Code: trailhound/tools.py (final_observations), trailhound/runner.py (run)

Feature: The engine decides whether each final observation is corroborated
  As someone who needs honest results
  I want each final observation's status worked out by fixed rules from the Skeptic's last review
  So that "corroborated" always means the evidence held up and nothing material is still open

  Scenario Outline: Status follows from the last check and the blocking gaps
    Given the final checkpoint has observation "C3.O1"
    And the Skeptic's last check of it has "discriminates_from_rival" <discriminates>
    And <gap>
    When the engine works out the final observations
    Then "C3.O1" has status "<status>"

    Examples:
      | discriminates | gap                                                             | status       |
      | true          | no gap is about "C3.O1"                                         | corroborated |
      | true          | a gap with "blocks_verdict" false is about "C3.O1"              | corroborated |
      | true          | a gap with "blocks_verdict" true is about "C3.O1"               | inconclusive |
      | false         | no gap is about "C3.O1"                                         | inconclusive |
      | false         | a gap with "blocks_verdict" true is about "C3.O1"               | inconclusive |

  Scenario: An observation with no Skeptic check is inconclusive
    Given the final hypothesis has an observation the Skeptic's review has no check for
    When the engine works out the final observations
    Then that observation has status "inconclusive"
    And its "skeptic_note" is empty

  Scenario: Each final observation carries the Skeptic's note
    Given the Skeptic's last check of "C3.O1" has the note "a cumulative cap predicts the same declines"
    When the engine works out the final observations
    Then "C3.O1" keeps all its own fields
    And it gains "status" and "skeptic_note" "a cumulative cap predicts the same declines"

  Scenario: Only the final checkpoint's observations make up the conclusion, and parked claims
    Given checkpoint 1 had observation "C1.O1" and checkpoint 2 had observation "C2.O1"
    When the run ends after checkpoint 2
    Then output.json "observations" holds "C2.O1" only
    And "C1.O1" is still in checkpoint 1's record under "checkpoints"
    But a parked claim the final checkpoint didn't continue is kept too, inconclusive and marked parked (#305, see new_ground_and_parking.feature)

  Scenario Outline: anomaly_found counts anomalies and bugs, not findings
    Given the final observations have the kinds <kinds>
    When the runner sets "anomaly_found"
    Then it is <anomaly_found>

    Examples:
      | kinds              | anomaly_found |
      | none               | false         |
      | finding            | false         |
      | finding, anomaly   | true          |
      | bug                | true          |
