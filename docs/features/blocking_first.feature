# A round answers the questions that block the verdict before it opens new claims (#340).
#
# In the #330 benchmark all 15 checkpoints were weak, and the same blocking question came
# back checkpoint after checkpoint: "About Us TypeError not isolated from third-party
# scripts" was raised at C1, C2 and C3 of one run. Each round opened new claims instead,
# pushed by the oracle (#312) and the follow-up cap (#305). The prompt already said to take
# blocking questions first; now the engine holds the Driver to it, at the cost of one retry
# at most: a question this harness can't answer must never stop a run. A question that
# still won't settle is parked with its claim (new_ground_and_parking.feature).
#
# Code: trailhound/steering.py (blocking_ids, blocking_needed, blocking_answered,
# rules_out_errors, blocking_shortfall, once, limit, casting_note, RULES_OUT_FIELD),
# trailhound/loop.py. Tests: trailhound/tests/test_blocking_first.py

Feature: Blocking questions are answered before new claims are opened
  As someone who wants each checkpoint to settle something
  I want the questions that block the verdict answered first
  So that claims become corroborated or are given up on, instead of piling up

  Scenario: The blocking questions are the last review's open ones about a claim
    Given the last review has questions with "blocks_verdict" true
    Then the blocking questions for the next round are those about a claim ("about" not empty), not about a parked claim
    But not one the debrief settled or the Driver conceded, and not one of kind "not_worth_continuing"
    And the first round has none

  Scenario Outline: One test per blocking question, up to half the round
    Given <blocking> blocking question(s) and a round of <budget> tests
    Then at least <needed> test(s) must answer them, each with "follows_up" set to a different question's id

    Examples:
      | blocking | budget | needed |
      | 1        | 6      | 1      |
      | 5        | 6      | 3      |
      | 2        | 1      | 1      |

  Scenario: Too few answers are sent back once, then the round is taken
    Given 2 questions block the verdict and the round answers 1
    Then it is sent back with "2 question(s) from the last review block the verdict, and this round answers 1. Answer at least 2 of them, ..." naming the questions not answered yet and ending "this is asked once."
    And if the next answer still answers too few, it is taken as it is, and the log line and the checkpoint record show the shortfall
    And a round that gives up isn't held to the count
    And the last-attempt salvage (#288) checks the tests one by one without the count, so it keeps a round that answers them

  Scenario: A test answering a blocking question says what would settle it
    Then every adapter's casting tool gets an optional "rules_out_if" on each test, added by the engine
    And a test whose "follows_up" is a blocking question must fill it with a string, or the round is sent back
    And a "follows_up" that isn't a string is sent back, not a crash
    And the test's casting log entry keeps "follows_up" and "rules_out_if", so the hypothesis and the Skeptic see them

  Scenario: The first test on each doesn't count against the follow-up limit
    Then the first test answering each blocking question runs outside the follow-up cap of #305
    And a second test on the same question counts against the cap like any follow-up
    And a test on a parked claim's question is dropped as before

  Scenario: The Driver is told what comes first, and the run records it
    Then the engine's casting note for a later round starts with "First, the questions that block the verdict: C2.G1, C2.G3. At least 2 test(s) must answer them, one per question, starting from each question's next_test: ..."
    And with an oracle, its next part reads "Of the other tests, most should check an idea from 'oracle_ranked'"
    And the log says "blocking: needed 2 of C2.G1, C2.G3; answered C2.G1"
    And the checkpoint record has "blocking" with the questions, how many were needed and which were answered
