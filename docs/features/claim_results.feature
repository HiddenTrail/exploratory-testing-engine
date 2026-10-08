# The report and the summary lead with how each claim came out, not with the checkpoint verdict (#342).
#
# The checkpoint verdict is all or nothing: one blocking question on any claim makes the
# whole checkpoint "weak". With 2 to 5 claims a checkpoint it nearly always is: all 15
# checkpoints of the #330 benchmark were weak, though some had 2 of 3 claims holding up.
# Each claim's own result is the honest measure, and it already existed. So the report and
# the summary now lead with it, and say what holds each inconclusive claim back. The rule
# itself doesn't change: a claim is corroborated only when the Skeptic's last check says
# its tests tell it from its rival, and no blocking question is about it.
#
# Code: trailhound/tools.py (claim_results, final_observations), trailhound/report.py
# (_render_checkpoint, claims_line, _observation_line), trailhound/run_summary.py (_claims,
# _held_back). Tests: trailhound/tests/test_claim_results.py

Feature: The report and the summary lead with each claim's result
  As someone deciding whether to trust a run
  I want to see which claims hold up and what holds the rest back
  So that one open question on one claim doesn't hide the claims that did hold up

  Scenario: Each claim has a result, by the same rule as the run's final status
    Given a checkpoint's claims and the Skeptic's review of them
    Then a claim is "corroborated" when the Skeptic's check says its tests tell it from its rival and no blocking question is about it
    And otherwise it is "inconclusive", held back by "its tests don't tell it from its rival", by "open blocking question C1.G1" for each such question, or both
    And a "harness_limit" doubt about it holds it back too, as "a doubt this harness can't settle, C1.G2", though it doesn't block (#379)

  Scenario: The checkpoint heading says how its claims came out
    When the report is rendered
    Then the heading reads like "Checkpoint 2: 1 of 2 claim(s) hold up, 1 inconclusive", or "No claims"
    And the Skeptic's verdict ("weak" or "strong enough") is a badge in the Skeptic's line
    And each inconclusive claim's line ends with "(held back: ...)"

  Scenario: The summary says how the claims came out, right after the counts
    When the run summary is written
    Then after the counts it says "**Claims:** 1 of 4 claim(s) hold up at the end of the run; by checkpoint C1 0 of 2, C2 2 of 3, C3 1 of 3. The Skeptic's verdicts: weak, weak, weak."
    And when the conclusion keeps claims parked earlier, it says so: "(the last checkpoint's 3, plus 1 parked earlier)"
    And a run that stopped with an error says "**Claims:** the run stopped before its conclusion", then the checkpoints
    And the observations table has a "Held back by" column, empty for a corroborated claim
    And a blocking question comes with its text, cut to 60 characters, since the summary doesn't list the gaps
    And a claim parked by #305 in an earlier checkpoint is held back by "parked: objected to in checkpoints in a row, so it got no more tests"
