# Feedback: a run's results go back into the context layer for the next ranking.
#
# After a Driver run, trailhound.ontology.feedback reads the run's output.json and writes
# each test that cited an oracle id, with whether its prediction held, into
# context_<sut>.json (or context_<product>.json for a product with a wiki).
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
  I want each test that cited an oracle id stored with whether its prediction held
  So that the next run's ranking reflects what this run learned

  Scenario: The CLI merges a run into the SUT's context file
    When I run "python -m trailhound.ontology.feedback --sut token_purchase --run runs/x/output.json"
    Then it reads the run's "casting_log"
    And it writes "trailhound/ontology/context_token_purchase.json"
    And it prints "Merged N test result(s) into" the path, with "(total now M)"

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
    When the results are extracted
    Then there is one result, for "claim:data:01"
    And it has "verified" true and today's date as "timestamp"

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

  Scenario: A merged result changes the claim's score on the next ranking
    Given the first token_purchase claim is "untested"
    When a run's test cites it with "prediction_matched" false and the result is merged
    Then the claim's status becomes "refuted"
    And its score is higher than before
