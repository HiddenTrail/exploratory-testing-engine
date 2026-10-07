# How each adapter picks the oracle it gives the Driver.
#
# The same oracle layer serves an HTTP API and a web GUI. token_purchase uses its
# ranked domain claims plus API heuristics. web_gui uses a product's seeded oracle
# when WEB_GUI_PRODUCT names a product in the wiki, and GUI heuristics ranked by
# WEB_GUI_FEATURES otherwise. Either can be switched off, so a run can be compared
# with and without the oracle (#42, #111: with it, the Driver found what it lists
# sooner).
#
# The Driver ties a test back to an idea by copying its id into "oracle_claim_id".
# The loop keeps that field in the casting log, which is what feedback reads.
# The environment is read when the adapter module is imported.
#
# Code: trailhound/adapters/token_purchase/adapter.py, trailhound/adapters/web_gui/adapter.py,
# trailhound/loop.py, trailhound/tests/test_oracle_switch.py

Feature: Each adapter chooses its oracle, and either can turn it off
  As someone running a session
  I want token_purchase and web_gui to pick their oracle from the shared layer, with a switch to leave it out
  So that one oracle layer serves different systems and can be measured on and off

  Scenario: token_purchase gives the Driver its top 15 ranked ideas
    Given "TOKEN_PURCHASE_ORACLE" is not set
    When the token_purchase adapter is loaded
    Then it ranks ideas for "token_purchase" with surfaces ("api",) and features "payment", "money", "numeric-field" and "date-time"
    And the top 15 go into the onboarding evidence as "oracle_ranked"
    And the full unranked library is not sent alongside them
    # It was mostly the same information and doubled the evidence.

  Scenario Outline: An oracle switch set to "off" leaves the oracle out
    Given "<variable>" is set to "<value>"
    When the <adapter> adapter is loaded
    Then the onboarding evidence has no "oracle_ranked"
    And it still has "<kept>"

    Examples:
      | variable              | value | adapter        | kept           |
      | TOKEN_PURCHASE_ORACLE | off   | token_purchase | known_accounts |
      | TOKEN_PURCHASE_ORACLE | OFF   | token_purchase | known_accounts |
      | WEB_GUI_ORACLE        | off   | web_gui        | safety_note    |

  Scenario: Any other value keeps the oracle
    Given "TOKEN_PURCHASE_ORACLE" is set to "on"
    When the token_purchase adapter is loaded
    Then the onboarding evidence has "oracle_ranked"

  Scenario: web_gui with WEB_GUI_PRODUCT uses the product's seeded oracle
    Given "WEB_GUI_PRODUCT" is "juice-shop"
    When the web_gui adapter is loaded
    Then "oracle_ranked" is build_product_ideas for "juice-shop" with limit 15
    # The 15 are picked by taking turns across the FEW HICCUPPS seeds.

  Scenario: A run focus gets up to a third of the product's ideas
    # Without it, the Standards seed's two or so slots went to accessibility, and no
    # security heuristic reached the Driver (#278).
    Given "WEB_GUI_PRODUCT" is "juice-shop" and "WEB_GUI_FEATURES" is "security"
    When the web_gui adapter is loaded
    Then up to 5 of the 15 ideas are from heuristics tagged "security", best first, each with "focus": ["security"] and "(this run's focus: security)" in its rationale
    And the other 10 still take turns across the seeds
    And the CI workflow's "focus" input sets it, and refuses anything but lowercase tags

  Scenario: web_gui without a product uses GUI heuristics ranked by WEB_GUI_FEATURES
    Given "WEB_GUI_PRODUCT" is not set
    And "WEB_GUI_FEATURES" is "login,search"
    When the web_gui adapter is loaded
    Then "oracle_ranked" is the ranked ideas for "web_gui" with surfaces ("gui",) and features ("login", "search")
    And at most 15 heuristics are taken
    And web_gui has no oracle_library.json, so there are no domain claims

  Scenario Outline: Each casting tool asks for an "oracle_claim_id" on every test
    When the Driver casts tests through the <adapter> adapter
    Then every test must have "oracle_claim_id" as a string
    And it is an idea's id copied exactly from the evidence, like "<example>", or an empty string

    Examples:
      | adapter        | example                  |
      | token_purchase | claim:data:03            |
      | web_gui        | heuristic:boundary_edges |

  Scenario: The loop keeps the cited id in the casting log
    Given the Driver cast a test with "oracle_claim_id" "heuristic:boundary_edges"
    When the loop runs the test
    Then its casting log entry has "oracle_claim_id" "heuristic:boundary_edges"
    And a test cast without the field gets an empty string
