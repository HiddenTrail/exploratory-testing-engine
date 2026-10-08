# What the Driver promises in the debrief, the next round runs first (#352).
#
# In the debrief the Driver answers each of the Skeptic's questions, and a change of
# approach is a plan: "next round I'll open the basket in a new tab". Nothing made the next
# round carry it out. In the full run runs/full340/F1 none of the 13 debrief answers came
# with a test, 9 were plans, and the new-tab test was promised at C1, C2 and C3 and never
# ran. It wasn't blocking, so #340 didn't hold the Driver to it, and the oracle and new
# claims took each round. Now a promise is held to like a blocking question. Running the
# promised test inside the debrief would need a round of tests there; the next round is
# where tests already run.
#
# Code: trailhound/steering.py (promises, blocking_shortfall, casting_note), trailhound/loop.py
# (run_checkpoint_loop, get_casting_round), trailhound/tools.py (DEBRIEF_ANSWER_SYSTEM_PROMPT,
# DEBRIEF_ANSWER_TOOL), trailhound/report.py (_steering_line).
# Tests: trailhound/tests/test_debrief_promises.py

Feature: The next round runs what the Driver promised in the debrief
  As someone who wants each checkpoint to settle something
  I want a promised new approach to be tested in the next round
  So that the same plan doesn't come back checkpoint after checkpoint without a test

  Scenario: A change of approach is a promise
    Given the Driver answered question "C1.G4" in the debrief with stance "change_approach"
    Then the question's outcome is "new_approach" and it is a promise for the next round, whether it blocks the verdict or not, and whether or not it's about a claim
    And the debrief prompt tells the Driver: "It's a promise: the next round is asked to run that test first, so only promise what you can run."
    But a question whose claim is parked is no promise any more: it's gone from the review the next round answers
    And a question of kind "not_worth_continuing" is no promise: the Skeptic said to drop it, and neither is a "harness_limit" one, which no test here can answer
    And a lean run without the debrief has no promises

  Scenario: The next round answers promises first, like blocking questions
    Given the last debrief promised "C1.G4"
    Then the next round's casting evidence has "promises": each id with the Driver's own words
    And the round's "answer_first" starts "First, what you promised in the debrief: C1.G4 (your words are in 'promises')", after the blocking questions when there are any (blocking_first.feature)
    And the promises count with the blocking questions: one test per question, up to half the round, each with "follows_up" and "rules_out_if"
    And a promised test without "rules_out_if" is sent back with "... which comes first because you promised it in the debrief: say in 'rules_out_if' ..."
    And a round that answers too few is sent back once with "... come first (they block the verdict, or you promised them in the debrief), and this round answers ...", then taken as it is, so a promise can go unkept
    And with more questions than half the round, a round that answers enough of them passes, and the rest may go unkept
    And the first test on each of them, up to that half, doesn't count against the follow-up limit; the rest count like any follow-up, so promises never take the whole round

  Scenario: Kept and broken promises are recorded and shown
    Then the checkpoint record has "promises": each id, the promise and "kept", true when a test following it up ran this round (not dropped, not skipped, and not a round that gave up)
    And the "blocking" record lists the promised questions with the blocking ones
    And the log says "debrief promises: kept C1.G4; not kept none"
    And the report's line under the checkpoint says "Promised in the last debrief: kept C1.G4; not kept C1.G1."
