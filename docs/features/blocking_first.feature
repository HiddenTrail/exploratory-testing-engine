# A round answers the questions that block the verdict before it opens new claims (#340).
#
# In the #330 benchmark all 15 checkpoints were weak, and the same blocking question came
# back checkpoint after checkpoint: "About Us TypeError not isolated from third-party
# scripts" was raised at C1, C2 and C3 of one run. Each round opened new claims instead,
# pushed by the oracle (#312) and the follow-up cap (#305). The prompt already said to take
# blocking questions first; now the engine holds the Driver to it. A question that still
# won't settle is parked with its claim (new_ground_and_parking.feature), so it can't eat
# every round.
#
# Code: trailhound/steering.py (blocking_ids, blocking_needed, blocking_errors, limit,
# casting_note, RULES_OUT_FIELD), trailhound/loop.py. Tests: trailhound/tests/test_blocking_first.py

Feature: Blocking questions are answered before new claims are opened
  As someone who wants each checkpoint to settle something
  I want the questions that block the verdict answered first
  So that claims become corroborated or are given up on, instead of piling up

  Scenario: The blocking questions are the last review's
    Given the last review has questions with "blocks_verdict" true, and none of them is about a parked claim
    Then those are the blocking questions for the next round
    And the first round has none

  Scenario Outline: A round must answer one blocking question per test, up to half of it
    Given <blocking> blocking question(s) and a round of <budget> tests
    Then at least <needed> test(s) must answer them, each with "follows_up" set to a different question's id

    Examples:
      | blocking | budget | needed |
      | 1        | 6      | 1      |
      | 5        | 6      | 3      |
      | 2        | 1      | 1      |

  Scenario: A round that leaves them open is sent back
    Given 2 questions block the verdict and the round answers 1
    Then it is sent back with "2 question(s) from the last review block the verdict, and this round answers 1. Answer at least 2 of them first, ..." ending with the ids not answered yet
    But a round that gives up isn't held to the count

  Scenario: A test answering a blocking question says what would rule the rival out
    Then every adapter's casting tool gets an optional "rules_out_if" on each test, added by the engine
    And a test whose "follows_up" is a blocking question must fill it, or the round is sent back

  Scenario: Those tests don't count against the follow-up limit
    Then the first test answering each blocking question runs outside the follow-up cap of #305
    And a second test on the same question counts against the cap like any follow-up
    And a test on a parked claim's question is dropped as before

  Scenario: The Driver is told what comes first
    Then the casting prompt of a later round starts its rules with "First, the questions that block the verdict: C2.G1, C2.G3. At least 2 test(s) must answer them, ..."
