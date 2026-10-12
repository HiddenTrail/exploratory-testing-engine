# Feedback: a run's results go back into the context layer for the next ranking.
#
# After a Driver run, trailhound.ontology.feedback reads the run's output.json and writes
# each oracle idea a test cited, with the Driver's answer for it, into context_<sut>.json
# (or context_<product>.json for a product with a wiki).
#
# The answer is the Driver's latest "held", "broke" or "cannot_tell" for the idea (#312),
# the same one coverage uses (#328). Until #407 it was each test's "prediction_matched",
# which only says the screen came out as the Driver guessed: a guess that "this link is
# broken" that came true was stored as a confirmed idea and pushed down the next run's
# list. A skipped test never ran, so it doesn't count as citing an idea (#231).
#
# Only "oracle_claim_id" counts. "linked_hypothesis" is free text the Driver writes
# itself and can't be matched back to a claim. And the Driver makes ids up, for
# example from gap ids, when it has no oracle to cite (#107), so an id that isn't one
# of the SUT's ranked ideas is dropped and listed instead of recorded.
#
# Code: trailhound/ontology/feedback.py, trailhound/tests/test_ontology_claim_matching.py,
# trailhound/tests/test_seeded_oracle.py

Feature: A run's results feed back into the next ranking
  As someone running repeated sessions
  I want each oracle idea a test cited stored with how the Driver said it came out
  So that the next run's ranking reflects what this run learned

  Scenario: The CLI merges a run into the SUT's context file
    When I run "python -m trailhound.ontology.feedback --sut token_purchase --run runs/x/output.json"
    Then it reads the run's "casting_log"
    And it writes "trailhound/ontology/context_token_purchase.json"
    And it prints "Merged N test result(s) into" the path, with "(total now M)"
    And it writes what it printed into the run's own output.json as "learned" (#328)

  Scenario: With --product the context file is keyed by product
    When I run feedback with "--sut web_gui --product juice-shop"
    Then the known ids are the whole seeded oracle for "juice-shop"
    And the results go into "trailhound/ontology/context_juice-shop.json"

  Scenario: Only tests that cite an oracle id are kept
    Given a casting log with these tests:
      | linked_hypothesis   | oracle_claim_id | prediction_matched |
      | some theory         | claim:data:01   | true               |
      |                     |                 | true               |
      | an unlinked theory  |                 | false              |
    And the Driver answered "claim:data:01" with "held"
    When the results are extracted
    Then there is one result, for "claim:data:01"
    And it has "verdict" "held", "verified" true and today's date as "timestamp"

  Scenario Outline: The Driver's answer decides the result, not the test's prediction (#407)
    Given a test that cited "a" with "prediction_matched" <matched>
    And the Driver's latest answer for "a" is "<verdict>"
    When the results are extracted
    Then the result for "a" has "verdict" "<verdict>" and "verified" <verified>

    Examples:
      | matched | verdict     | verified |
      | true    | broke       | false    |
      | false   | held        | true     |
      | true    | cannot_tell | null     |

  Scenario: A skipped test doesn't count as citing an idea (#231)
    Given the only test that cited "a" has "skipped" true and "prediction_matched" false
    When the results are extracted
    Then there is no result for "a"

  Scenario: An idea the Driver never answered isn't learned
    Given a test that cited "a", and no hypothesis of the run answered "a"
    When the results are extracted
    Then there is no result for "a"
    And the CLI prints "Learned nothing about 1 idea(s) the tests cited but the Driver never answered: a"

  Scenario: An id that isn't a known idea is dropped and listed
    Given a casting log citing "claim:data:01", "claim:data:C1.G1" and "heuristic:boundary_edges"
    And the known ids are the ranked ideas for "token_purchase"
    When the results are extracted
    Then results are kept for "claim:data:01" and "heuristic:boundary_edges"
    And "claim:data:C1.G1" is dropped
    And the CLI prints "Dropped 1 made-up id(s) that aren't ranked ideas for token_purchase: claim:data:C1.G1"

  Scenario: A product's expectation ids are known ids
    Given the known ids for "web_gui" with product "juice-shop"
    Then "oracle:self_consistency:juice-shop.product-list.F2" is a known id
    And "heuristic:made_up" is not

  Scenario: The newest result for a claim wins
    Given the context has "claim:data:01" with "verified" false from "day1"
    When a new result for "claim:data:01" with "verified" true from "day2" is merged
    Then the context holds one result for "claim:data:01", with "verified" true and "timestamp" "day2"

  Scenario: A later "cannot_tell" doesn't erase an earlier answer (#407)
    Given the context has "claim:data:01" with "verdict" "broke" from "day1"
    When a new result for "claim:data:01" with "verdict" "cannot_tell" from "day2" is merged
    Then the context still holds the "broke" result from "day1"
    But a "cannot_tell" is stored when there's no earlier result, and a later "held" or "broke" replaces it

  Scenario: A merged result changes the claim's score on the next ranking
    Given the first token_purchase claim is "untested"
    When a run's test cites it, the Driver answers it with "broke", and the result is merged
    Then the claim's status becomes "refuted"
    And its score is higher than before
