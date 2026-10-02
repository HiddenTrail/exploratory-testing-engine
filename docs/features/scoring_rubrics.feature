# Scoring rubrics: a rubric.md per reference SUT, for scoring a run by hand.
#
# Green tests say the engine runs. They don't say whether a run was any good. Each
# reference SUT has a rubric.md that a person fills in after reading a run's
# output.json and bugs.json. The two differ in kind. complex_sut has a planted bug,
# so its rubric checks the run found and explained it. token_purchase has no planted
# bug, so its rubric scores how rigorous the process was, and any claimed anomaly has
# to be checked against sut.py by hand. Nothing in the code reads these files.
#
# Code: engine/adapters/token_purchase/rubric.md, engine/adapters/complex_sut/rubric.md

Feature: Each reference SUT has a rubric to score runs by hand
  As someone judging the engine's quality
  I want a written rubric per reference SUT
  So that runs can be scored the same way each time, even where there is no ground truth

  Scenario: The token_purchase rubric scores the process, since there is no known bug
    Given a finished token_purchase run
    When I score it with "engine/adapters/token_purchase/rubric.md"
    Then I check whether auth, card authorization, Luhn, expiry, CVV, credit_count and pricing tiers were each exercised
    And whether any test probed a card's hidden spending capacity, for example until "insufficient_funds"
    And whether each anomaly names test numbers, a mechanism and a real competing explanation
    And whether the Skeptic's "observation_checks" and "gaps" give a real alternative and a way to tell it apart
    And whether each "inconclusive" bug's "caveats" name what wasn't resolved
    And when "anomaly_found" is false, whether the summary and behaviors are honest rather than thin coverage
    And I record in a table whether each claimed anomaly held up against the real "sut.py"

  Scenario: The complex_sut rubric checks the planted race was found and explained
    Given a finished complex_sut run with "anomaly_found" true
    When I score it with "engine/adapters/complex_sut/rubric.md"
    Then I score sections 1 to 7
    And they ask whether the Driver reasoned about concurrency before testing it
    And whether the anomalous test really has "actual_correctness" "overcounted"
    And whether the claim names a check-then-act race on shared state
    And whether the competing explanation is a fair rival
    And whether the disconfirm test is truly sequential, with "concurrent" false and "request_count" above 1
    And whether "prediction_matched" was true for both the confirm and the disconfirm test
    And whether the Skeptic's alternative differs from the Driver's own rival

  Scenario: A complex_sut run that found nothing is scored on its behavior checkpoints
    Given a finished complex_sut run with "anomaly_found" false
    When I score it with "engine/adapters/complex_sut/rubric.md"
    Then I skip to section 8
    And I check whether the summary matches what was tested
    And whether the Skeptic's gaps named that everything so far was sequential
    And whether a later checkpoint went after the earlier gaps

  Scenario: A bug report that claims a root cause it can't see counts against the run
    Given a complex_sut run that wrote a bug report
    When I read its "caveats"
    Then a report that names one implementation cause without having seen the code is marked as overclaiming
