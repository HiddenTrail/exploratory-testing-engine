# The Driver tests from the oracle, and every idea and every error gets an answer (#312).
#
# The oracle exists to guide the testing. In the four lean runs on 2026-10-06 the Driver
# cited at most one of 15 ideas a run, and every run saw 4 or 5 of Juice Shop's 5 known
# problems in its tests' recorded signals but reported 0 to 2. A run also found a 400
# from the basket's own API in two tests and called it a bug, and the Skeptic lowered
# it because the Driver's own rival explanation wasn't ruled out. These rules are held
# in code, not left to the prompt.
#
# Code: trailhound/ledger.py, trailhound/steering.py (free_cap, oracle_id_errors,
# oracle_progress), trailhound/loop.py, trailhound/tools.py (HYPOTHESIS_TOOL "ideas" and
# "dismissed_errors", validate_hypothesis_response, reconcile_kinds), trailhound/outcome.py
# ("problems"), trailhound/adapters/web_gui/adapter.py (problems_of), trailhound/report.py,
# trailhound/run_summary.py. Tests: trailhound/tests/test_oracle_ledger.py,
# trailhound/tests/test_hypothesis_salvage.py (#363)

Feature: The Driver tests from the oracle and answers for every idea and every error
  As someone relying on the engine to find problems
  I want most tests to check the oracle's ideas, and every recorded error to be answered
  So that what the harness sees is reported, and the oracle's ideas aren't ignored

  Scenario: A test's trusted errors are tokens on its outcome
    Then the web adapter puts each trusted console error and each failed request on the product's own site on the outcome's "problems"
    And a token is the first line, without the site's origin, a query string or an id in a path: "request: PUT /api/BasketItems/# -> 400"
    And hints (signals_weak), a test whose action wasn't sent, and a test stopped leaving the site have none

  Scenario: Most of a round follows the oracle
    Given the run has oracle ideas ("oracle_ranked")
    Then the casting prompt says most tests should check an idea, with its "where" as the place to start
    And at most a third of the round's budget (at least 1) may check no idea and follow up nothing; more are dropped without running, with "over the limit of N test(s) a round that check no oracle idea"
    And an oracle_claim_id that isn't an idea in oracle_ranked is sent back
    And from the second round, "oracle_progress" lists the ideas no test has checked yet and the latest answer for each one that was

  Scenario: Every idea a checkpoint's tests checked gets an answer
    Given this checkpoint's tests cited the idea "oracle:a" in tests 1 and 2
    Then the hypothesis evidence has "ideas_to_answer" with its id, claim and tests
    And the hypothesis must answer it in "ideas" with a verdict "held", "broke" or "cannot_tell" and the tests
    And a missing answer, a verdict outside those three, or an id this checkpoint didn't check is sent back

  Scenario: Every trusted error gets an answer, once
    Given tests recorded "request: PUT /api/BasketItems/# -> 400" and no earlier checkpoint answered it
    Then the hypothesis evidence has "errors_to_account_for" with the error and the tests that showed it
    And the hypothesis must answer it: an observation citing a test that shows it, or a line in "dismissed_errors" with a reason
    And an unanswered one is sent back, listed with its tests
    And once answered it stays answered for the rest of the run

  Scenario: A test with an error isn't normal behaviour
    When a behaviour cites a test that recorded a trusted error
    Then it is sent back: "behaviors[i] cites test N, which recorded ...: a test with an error isn't normal behaviour"
    But if the last attempt's only fault is such a behaviour, the behaviour is dropped and the run goes on (#363)
    And the hypothesis keeps it in "dropped_behaviors" with why, "cites test 13, which recorded ...", the log says "dropped a behaviour that was still wrong at the last try: ...", and the report lists it under "Dropped from behaviour, still wrong at the last try"
    And the error itself still has to be answered, and any other fault still fails the attempt

  Scenario: A bug on a reproduced error stays a bug
    Given the Driver calls an observation a "bug", and more than one of its tests recorded the same trusted error
    When the Skeptic would call it more cautiously
    Then it stays a bug, with "kept_as_bug_because" "it rests on a trusted error that more than one test recorded"
    And the Skeptic is told to question its cause or impact instead, and to ask for the test that shows the impact
    But a bug resting on an error only one test recorded is lowered as before

  Scenario: The report and the summary say what came of it
    Then the report's "The oracle's ideas" table has "The Driver's answer": held, broke or cannot tell
    And the run summary says "The oracle: X of N ideas checked: a held, b broke, c couldn't tell."
    And "Errors the tests recorded: M, every one answered (k dismissed with a reason)." or how many have no answer
