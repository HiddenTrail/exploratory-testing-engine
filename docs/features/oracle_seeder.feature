# The oracle seeder: a product's oracle built from its wiki and the heuristic library.
#
# For a product with a wiki the oracle is built, not written by hand (#138). The
# seeder runs the heuristic library and the product's facts through oracle seeds.
# The first seed set is FEW HICCUPPS (by Michael Bolton and James Bach), 11 seeds in
# seeds/fewhiccupps.json. They used to be in the heuristic library and moved here
# with their ids.
#
# Each expectation has a stable id, its seed, a tier, the screen it is about, a claim,
# how to check it and its sources. The output is plain JSON, so it can become what a
# separate Oracle service hands the Driver. No model calls, so it's free to rebuild.
#
# Facts outrank heuristics, so a plain top 15 would be all self-consistency checks.
# That is why a capped pick takes turns across seeds.
#
# Code: engine/ontology/seeder.py, engine/ontology/seeds/fewhiccupps.json,
# engine/ontology/oracle_creator.py (build_product_ideas), engine/tests/test_seeded_oracle.py

Feature: A product's oracle is built from its wiki through the FEW HICCUPPS seeds
  As someone onboarding a product
  I want the wiki's facts and the heuristic library combined through oracle seeds, with sources on every expectation
  So that the oracle isn't hand-written and every idea says where it came from

  Background:
    Given the seeds in engine/ontology/seeds/fewhiccupps.json
    And the product "juice-shop" in the wiki

  Scenario: There are 11 FEW HICCUPPS seeds
    When load_seeds runs
    Then the seed ids are "claims_oracle", "self_consistency", "comparable_products", "user_expectations", "standards", "world", "purpose", "familiarity", "image", "history" and "explainability"
    And every seed carries the file's "source"
    And every heuristic id a seed names is in the heuristic library

  Scenario Outline: A fact becomes a "fact" tier expectation under the seed for its kind
    Given a product fact of kind "<kind>"
    When build_oracle runs
    Then it becomes an expectation under seed "<seed>"
    And its id is "oracle:<seed>:<fact id>"
    And its sources are the fact id, the fact's source file and the entity page
    And its score is 5.0

    Examples:
      | kind     | seed             |
      | claimed  | claims_oracle    |
      | shown    | self_consistency |
      | rule     | purpose          |
      | standard | standards        |
    # For example "oracle:self_consistency:juice-shop.product-list.F2" claims the 1.99
    # price, and its sources start with "juice-shop.product-list.F2" and a file ending "S7.png".

  Scenario: A heuristic goes under one seed and on the screens that share its features
    When build_oracle runs
    Then every "monetary_precision" expectation is under seed "world"
    # World names it by id. self_consistency matches its "consistency" tag, but a seed that
    # names a heuristic by id gets it first.
    And it is on "product-list" and "product-details-dialog", the two screens with money
    And each id has the form "oracle:world:<screen>:monetary_precision"
    And its sources are "heuristic:monetary_precision" and the screen's page

  Scenario: A heuristic with no feature tag goes on the product, and each is scored by weight and bonuses
    Given a heuristic that fits the product's surfaces and has no feature tag
    When build_oracle runs
    Then its expectation is on entity "product", with id "oracle:<seed>:product:<heuristic id>"
    And its only source is "heuristic:<heuristic id>"
    And a placed heuristic's score is its "base_weight"
    And it gets 0.5 more when it is tagged with one of the product's surfaces
    And 1.0 more when it has feature tags
    And heuristics for a surface the product doesn't have are left out

  Scenario: Every oracle and attack heuristic has a seed, and the rest are listed
    # console_and_network_errors once matched no seed, so no product's oracle had it,
    # and a run called a real console TypeError a mere finding (issue #246).
    When build_oracle runs
    Then every heuristic of kind "oracle" or "attack" is drawn on by a seed
    And "console_and_network_errors" is under "familiarity" as "oracle:familiarity:product:console_and_network_errors"
    And "multiple_tabs" is under "comparable_products", on the screens with the "session" feature
    And the oracle's "not_drawn_on" lists the heuristics no seed draws on, such as "goldilocks"
    And the seeder CLI prints how many there are and names them

  Scenario: Security quality heuristics go under Standards
    # #278: the Standards seed draws on the "security" tag as well as accessibility and privacy.
    Then client_storage_secrets, third_party_requests, own_resources_refused, browser_security_policy and console_reveals_internals are under "standards"

  Scenario: History and Explainability are standing expectations
    When build_oracle runs
    Then there is "oracle:history:product" and "oracle:explainability:product" with tier "standing"
    And each is on entity "product" with source "seed:<seed id>" and score 5.0

  Scenario: The built oracle has unique ids and every seed contributes
    When build_oracle runs
    Then no expectation id appears twice
    And every seed has at least one expectation
    And the oracle can be written as plain JSON
    And an invalid product layer raises an error starting "invalid product layer:"
    And the product's screens from its context (Spoor's map, see spoor_context.feature) are read with the wiki's entities, so a product with screens but no overview still gets an oracle
    And "python -m engine.ontology.seeder --product juice-shop" prints the number of expectations and the count per seed
    And with "--out <file>" it also writes the oracle there as JSON

  Scenario: A capped pick takes turns across seeds
    When build_product_ideas runs for "juice-shop" with limit 11
    Then every one of the 11 seeds has an idea in the pick
    # Seeds take turns in order of their best score. Inside a seed, equal scores
    # alternate between screens: otherwise a seed's first picks all came from the
    # alphabetically first page.
    And the picked ideas are sorted by score and numbered from "rank" 1
    And each idea's "category" is its seed, its "source" is "seeded_oracle" and its "rationale" is "<seed name>. Check: <check>"

  Scenario: Earlier results move an expectation up or down
    Given context_juice-shop.json has a result for "oracle:self_consistency:juice-shop.product-list.F2" with "verified" false
    When build_product_ideas runs for "juice-shop"
    Then that idea's status is "refuted" and its score is 9.0
