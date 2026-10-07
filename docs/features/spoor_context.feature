# Spoor feeds the product's context, and the oracle is built from it (issue #311).
#
# Spoor's job is to tell the engine about the product. Until #311 the oracle only knew
# four hand-written wiki pages, so its top ideas were about places no test reached, and
# the Driver cited at most one of 15 ideas a run. Now a converted Spoor map becomes the
# product's screens, in the shape of the wiki's entities (features and facts, AGENTS.md's
# product layer), written into the product's context. The seeder builds ideas from them
# next to the wiki's pages, and ideas on a screen the engine can reach rank higher and
# say where it is.
#
# The screens go into the context, not the wiki: the wiki is the curated layer, a page a
# person wrote is never overwritten, and CI can't commit generated pages.
#
# Code: trailhound/adapters/web_gui/to_context.py (screens_from_map, features_of, write),
# from_spoor.py (changes_data), trailhound/ontology/product.py (context_screens),
# seeder.py (build_oracle), oracle_creator.py (build_product_ideas, REACHABLE_BONUS).
# Tests: trailhound/tests/test_spoor_context.py

Feature: A Spoor map becomes the product's screens, and the oracle builds on them
  As someone testing a product Spoor has mapped
  I want the oracle's ideas to cover the screens and forms Spoor found, and say where they are
  So that the Driver's ideas are about places it can reach

  Scenario: The map's states become screens
    When python -m trailhound.adapters.web_gui.to_context --map <converted map> --product <product> runs
    Then states on one route whose controls mostly overlap (80%, numbers in names ignored) are one screen
    And Juice Shop's twelve product dialogs are one screen, "juice-shop apple juice (1000ml) and 11 more like it"
    And each screen has a slug, a title, its route, the path to reach it, and its headings as examples
    And the entry screen is called "start page"; a screen with no heading is named after the step that reaches it

  Scenario: A screen's features come from what is on it
    Then features are vocabulary tags matched from its controls and headings: a field gives "text-field", a password "login", Add to Basket "cart", paging controls "list-paging"
    And one field with a submit-like button ("Send the review", "Log in") gives "form"
    And the toolbar's controls, on 80% or more of the states, count only for the start screen

  Scenario: Facts say only what the map saw
    Then each screen gets "shown" facts with ids G1, G2...: its fields, the controls that change data, where its controls lead, and the screens shown like it
    And "changes data" comes from the gate's reason (a data-changing name or a submit), not from a dropdown or a disabled button
    And names lose emails and generated ids and are cut to 40 characters

  Scenario: The screens go into the product's context, beside what's already there
    Then they replace the context's "screens", and its results, discoveries and objections stay
    And the context file is gitignored, except token_purchase's committed example

  Scenario: The oracle builds on the screens
    Then the seeder reads the wiki's entities and the context's screens together, a screen fact's id being "<product>.<slug>.<id>"
    And a fact generated from the map scores 2 lower than one a person wrote, so it doesn't outrank the heuristics aimed at the screen
    And a product with no wiki pages but with screens still gets an oracle
    And an idea on a screen with a route scores 1.5 higher and carries "where": the route to start from

  Scenario: CI feeds every run's map into the context
    When the exploratory-run workflow has converted Spoor's map
    Then it runs to_context before the engine, so the run's oracle starts from the map's screens
    And the Driver's product_areas include the screens' titles
