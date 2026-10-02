# Three HTML views of the oracle.
#
# engine.ontology.report turns an oracle_ranked.json into one table, one row per idea.
# engine.ontology.website shows the four layers stacked on one page (heuristics,
# domain, context, ranking), each folded. It is a Phase 0 stacked view: it draws no
# links between layers, and it always uses the token_purchase style ranking
# (build_ranked_ideas), so it doesn't show a product's seeded oracle or the
# discoveries in a context file.
#
# The run report shows the oracle an adapter gave its Driver, folded in the
# onboarding section, because it is background and runs to thousands of words.
#
# Code: engine/ontology/report.py, engine/ontology/website.py,
# engine/report.py (render_oracle_ranked)

Feature: The ranked oracle and its layers can be viewed in HTML
  As someone checking the oracle
  I want an HTML table of the ranked ideas, a page with all four layers, and the oracle in the run report
  So that I can see what the Driver was given and why

  Scenario: ontology.report renders the ranked list as a table
    Given "runs/ontology/token_purchase/oracle_ranked.json" exists
    When I run "python -m engine.ontology.report --sut token_purchase"
    Then it writes "runs/ontology/token_purchase/oracle_ranked.html"
    And the table has the columns "Rank", "Id", "Score", "Tier", "Status", "Category", "Claim" and "Rationale"
    And each score is shown with one decimal
    And "--in" and "--out" choose other input and output paths

  Scenario Outline: Tier and status are shown as coloured badges
    Given an idea with <field> "<value>"
    When the table is rendered
    Then its badge is "<kind>"

    Examples:
      | field  | value         | kind    |
      | tier   | grounded      | good    |
      | tier   | generic       | neutral |
      | status | untested      | warn    |
      | status | refuted       | bad     |
      | status | confirmed     | neutral |
      | status | n/a           | neutral |
      | status | untested+jira | warn    |
    # The status badge is chosen by the part before "+".

  Scenario: ontology.website shows the four layers on one page
    When I run "python -m engine.ontology.website --sut token_purchase"
    Then it writes "runs/ontology/token_purchase/ontology_website.html"
    And the page has the layers "1. Heuristic library (generic ontology)", "2. Business / domain layer", "3. Context / source layer" and "4. Oracle (prioritized test ideas)"
    And each layer shows a count in its header and folds its content under "Show details"
    And "--out" writes the page somewhere else instead

  Scenario: What each layer of the website shows
    When the website is rendered for "token_purchase"
    Then layer 1 lists every heuristic in the library with its id, kind, description, tags and base weight
    And layer 2 shows domain_token_purchase.json: the endpoint, request and response fields, known decline reasons and business rules
    And layer 3 shows the context's test results, jira entries and risk assessments, or "none yet"
    And layer 4 shows the top 25 ranked ideas and counts grounded and generic ideas
    # Layer 4 has no rationale column, unlike ontology.report's table.

  Scenario: What the website doesn't show
    When the website is rendered
    Then no links are drawn between the layers
    And the context's "discoveries" are not shown
    And layer 4 is never a product's seeded oracle
    And a SUT with no domain_<sut>.json gets an empty domain layer

  Scenario: The run report folds the oracle given to the Driver
    Given an adapter put "oracle_ranked" in its onboarding evidence
    When the run report's onboarding section is rendered
    Then it has a folded section "Prioritized oracle given to the Driver (top N)"
    And each idea shows "#<rank> [<id>] (<tier>, score <score>, <status>)", its claim and its rationale

  Scenario: No oracle, no section
    Given the oracle was switched off, so there is no "oracle_ranked"
    When the run report's onboarding section is rendered
    Then there is no oracle section
