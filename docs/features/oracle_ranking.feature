# Layer 4 of the ontology stack: one ranked list of test ideas for a SUT.
#
# oracle_creator reads the heuristic library (layer 1), the SUT's domain claims in
# engine/adapters/<sut>/oracle_library.json (layer 2) and context_<sut>.json
# (layer 3: test results, jira entries, risk assessments). Domain claims come first,
# scored up or down by what context says about them. Heuristics fill in behind them.
#
# Results used to be matched to claims by exact claim text. The Driver paraphrases,
# so a real run's results never moved the ranking (the former "known gap" in
# docs/ontology-todo.md). Every claim now has a stable id built from its category
# and position, and results are matched on that id.
#
# It is flat files with no database or service, and no model calls.
#
# Code: engine/ontology/oracle_creator.py, engine/tests/test_ontology_claim_matching.py

Feature: Test ideas are ranked by what's already known about them
  As someone with a limited test budget
  I want domain claims scored by earlier results and tickets, with heuristics behind them, under stable ids
  So that the Driver gets the most useful ideas first and its results can be tied back to them

  Scenario: Domain claims get stable ids from their category and position
    Given engine/adapters/token_purchase/oracle_library.json lists claims under "modeled" by category
    When load_domain_claims runs for "token_purchase"
    Then it returns 58 claims
    And the first claim in category "data" has id "claim:data:01"
    And loading again gives the same ids in the same order
    And no id appears twice

  Scenario: Categories that don't apply, and SUTs with no library, give no claims
    Given a category in "modeled" with "applies" set to false
    When load_domain_claims runs
    Then none of that category's vectors become claims
    And a SUT with no oracle_library.json gets no domain claims at all

  Scenario Outline: A grounded claim's score depends on what context says about it
    Given a domain claim with id "claim:data:01"
    And the context holds <result>
    When score_grounded_claim scores it
    Then its status is "<status>"
    And its score is <score>

    Examples:
      | result                                                 | status    | score |
      | no test result for "claim:data:01"                     | untested  | 6.0   |
      | a result for "claim:data:02" only                      | untested  | 6.0   |
      | a result for "claim:data:01" with "verified" false     | refuted   | 9.0   |
      | a result for "claim:data:01" with "verified" true      | confirmed | 3.0   |

  Scenario: A jira entry that mentions the claim adds 3.0 and "+jira" to the status
    Given an untested claim whose text contains a word longer than 4 letters
    And a jira entry whose title or description contains that word, in any case
    When score_grounded_claim scores it
    Then its score is 9.0
    And its status is "untested+jira"
    # Words of 4 letters or fewer are ignored, and the match is a plain substring.

  Scenario: The result is matched by id even when the Driver paraphrased the claim
    Given a claim "claim:data:01" with the text "Original claim wording."
    And a test result for "claim:data:01" with "verified" false
    When score_grounded_claim scores it
    Then its status is "refuted"

  Scenario: Claims and heuristics are ranked together by score
    # Heuristics score 1 to 4.5 here, so they land behind every untested or refuted
    # claim. A confirmed claim (3.0) can fall below the best heuristics.
    When build_ranked_ideas runs for a SUT
    Then each domain claim becomes an idea with tier "grounded" and source "domain_oracle"
    And each selected heuristic becomes an idea with id "heuristic:<library id>", tier "generic", status "n/a" and source "heuristic_library"
    And a heuristic's "category" is its kind and its "rationale" starts with "Heuristic: <name>. Try:"
    And all ideas are sorted by score, highest first, and numbered from "rank" 1

  Scenario: The CLI writes the ranked list to a JSON file
    When I run "python -m engine.ontology.oracle_creator --sut token_purchase"
    Then it writes "runs/ontology/token_purchase/oracle_ranked.json"
    And the file has "sut", "generated_at" and "ranked_ideas"
    And it prints "Wrote 176 ranked ideas to" and the path
    # The CLI passes no surface or features, so all 118 heuristics are kept: 58 claims plus 118.
    And "--out" writes the file somewhere else instead

  Scenario: A SUT with no context file is ranked as if nothing were known
    Given there is no engine/ontology/context_<sut>.json
    When load_context runs
    Then it returns empty "test_results", "jira_entries" and "risk_assessments"
