# Most of each round goes to new ground, and what can't be shown gets parked (issue #305).
#
# The Skeptic doesn't stop reports, but it took over the testing after checkpoint 1. In
# the lean Juice Shop run on 2026-10-06, every test of checkpoint 2 repeated an earlier
# one, and no later checkpoint reached a new state. Some questions can't be answered with
# this harness at all ("is the overlay really blocking a real user?", #294), so they came
# back checkpoint after checkpoint. So a later round may spend only a third of its budget
# on earlier questions, and a claim the tests can't settle is parked instead of chased.
#
# Code: trailhound/steering.py, trailhound/loop.py, trailhound/runner.py, trailhound/interplay.py
# (lineages, objected). Tests: trailhound/tests/test_steering.py

Feature: Later rounds explore new ground, and claims the tests can't settle are parked
  As someone who wants the engine to find problems
  I want most of each round spent on what hasn't been tested, and no round spent on an unanswerable question
  So that exploration doesn't stop after the first checkpoint

  Scenario: Each cast test says what it follows up
    Then every adapter's casting tool gets an optional "follows_up" on each test, added by the engine
    And it's the id of an earlier observation (like "C1.O2") or question (like "C1.G3"), or empty for new ground
    And a follows_up naming anything else is sent back with the ids it could be
    And in the first round the Driver is told to leave it empty

  Scenario Outline: A later round runs only so many follow-ups
    Given a later round with a test budget of <budget>
    Then the Driver is told "At most <cap> of this round's tests may follow up an earlier observation or question"
    And the engine runs the first <cap> follow-ups and every new-ground test
    And drops each further follow-up into "dropped_tests" with "over the limit of <cap> follow-up test(s) a round", without a retry

    Examples:
      | budget | cap |
      | 6      | 2   |
      | 8      | 2   |
      | 9      | 3   |
      | 2      | 1   |

  Scenario: Each checkpoint records how much went back over earlier ground
    Then the checkpoint has "follow_ups", the tests that ran declared as follow-ups
    And "repeats", the tests whose action (the outcome's action_id) an earlier checkpoint had already run, declared or not
    And the report's checkpoint says "N of M test(s) followed up earlier questions, K repeated an earlier action."

  Scenario: A claim objected to in two checkpoints in a row is parked
    Given the Skeptic objected to C1.O1, by a blocking gap about it or a check saying its evidence doesn't tell it from its rival
    And it objected again to C2.O1, which continues C1.O1
    Then after checkpoint 2 the claim C1.O1 is parked, and the checkpoint's "parked" says so with the checkpoints in a row
    And the log says "parked C1.O1: objected to in 2 checkpoints in a row"
    # The same rule as interplay's objections that kept coming back.

  Scenario: A parked claim gets no more tests or questions
    Given C1.O1 is parked
    Then the next checkpoint doesn't have to answer the questions only about it; a question also about a live claim stays
    And a test that follows up C1.O1 or C2.O1 is dropped with "which is parked"
    And the Driver's casting, hypothesis and testing story get "parked": the claim's latest id, its first id, and why
    And the testing story lists it as an obstacle

  Scenario: A parked claim stays in the conclusion
    Given C1.O1 was parked and the final checkpoint doesn't continue it
    Then output.json "observations" still has its latest version, as "inconclusive", with "parked": true
    And the report shows it with a "parked" badge
    And the run summary lists it under "Parked"
