# The Skeptic knows what a test here can do, and an untestable doubt doesn't block (#379).
#
# The Skeptic reviews cold: it never learned what a test can do or observe. In 17 runs,
# 44 of 114 blocking questions (39%) asked for a test no test here can run: read the DOM
# or a screenshot, clear cookies, open the network tab, suppress an error. The Driver ran
# something weaker, the Skeptic rejected it, and the question blocked every checkpoint
# (runs/exp379, runs/full363/F3 test 17). Now the adapter says what a test can do, and a
# doubt nothing here can settle is kept, as a doubt, without blocking. Its claim still
# isn't corroborated.
#
# Code: trailhound/adapter.py (test_capabilities), trailhound/adapters/web_gui/adapter.py
# (TEST_CAPABILITIES), trailhound/tools.py (OBJECTION_KINDS, SKEPTIC_SYSTEM_PROMPT,
# stamp_gap_ids, claim_results), trailhound/loop.py (get_skeptic_review),
# trailhound/steering.py (blocking_ids, promises). Tests: trailhound/tests/test_harness_limit.py

Feature: The Skeptic knows what a test can do, and an untestable doubt doesn't block
  As someone who wants checkpoints to settle what can be settled
  I want the Skeptic to ask only for tests this harness can run
  So that a question nobody can answer here doesn't hold every checkpoint back

  Scenario: The Skeptic is told what a test can do
    Given the adapter has "test_capabilities"
    Then the Skeptic's evidence has it as "what_a_test_can_do"
    And for web_gui it names the steps, what a result shows (signals per step, failed requests with their address, page messages, page controls) and what a test can't do (read the DOM, CSS or a screenshot, open a network tab, start logged out or clear storage, block or mock a request, suppress an error, act as a second user)
    And an adapter without it gives the Skeptic nothing more, as before

  Scenario: A blocking question needs a test this harness can run
    Then the Skeptic prompt says a blocking question needs a next_test this harness can run
    And a doubt no test here could settle is a gap of kind "harness_limit", saying what would settle it elsewhere

  Scenario: An untestable doubt never blocks, and doesn't settle anything either
    Given a gap of kind "harness_limit" that the Skeptic marked blocks_verdict true
    Then the engine sets blocks_verdict false and marks it "asked_to_block", with no retry
    And it isn't one of the questions the next round answers first, and it is no promise
    But a claim it's about stays "inconclusive", held back by "a doubt this harness can't settle, C1.G2"
    And it isn't one of the four objections a "weak" verdict rests on: with only such doubts left, the verdict can be "strong_enough" and the run stops as "skeptic_satisfied", its claims still inconclusive
