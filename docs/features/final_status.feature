# The final status of each observation, decided by the engine.
#
# A run's conclusion is every claim the run made, each marked "corroborated" or
# "inconclusive". No model decides this. The engine reads the Skeptic's last review:
# an observation is corroborated only when its check says the evidence discriminates
# it from its rival and no blocking gap is about it. Anything else is inconclusive,
# so a result that wasn't confirmed is never shown as confirmed.
#
# Until #405 the conclusion was the final checkpoint's observations only. A claim the
# Driver stopped repeating fell out of it, though nothing told the Driver to repeat
# one, and a run that stopped with an error had no conclusion at all. In the last 6
# CI runs, one lost a finding that way and one lost all 3 of its claims.
#
# Code: trailhound/tools.py (final_observations), trailhound/runner.py (run, conclusion),
# trailhound/steering.py (keep_every_claim), trailhound/verify.py (replay_bugs)

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

  Scenario: A claim the Driver stopped repeating stays in the conclusion (#405)
    Given checkpoint 1 had "C1.O1" and "C1.O2", and checkpoint 2 had "C2.O1" with "continues" "C1.O1"
    When the run ends after checkpoint 2
    Then output.json "observations" holds "C2.O1" with the status its review gives it
    And then "C1.O2", in its latest wording, "inconclusive" because the last review never checked it, with "dropped": true and an empty "skeptic_note"
    But a parked claim the final checkpoint didn't continue is marked "parked": true instead (#305, see new_ground_and_parking.feature)
    And claims are followed through "continues", so a claim restated under a new id without it is kept twice

  Scenario: A run that stops early concludes from the checkpoints that finished (#405)
    Given checkpoints 1 and 2 finished, and checkpoint 3 stopped with an error or the spending limit
    When the runner writes the output
    Then the console shows "The run stopped early. Its conclusion is from the checkpoints that finished:"
    And output.json "observations" is worked out from checkpoints 1 and 2 as if the run had ended there, and "anomaly_found" with it
    But no test runs again: each bug is lowered to an anomaly as "couldn't replay", because "the run stopped early, so nothing was run again" (see bug_replay.feature)
    And no bug report is written

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
