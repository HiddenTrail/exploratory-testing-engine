# The product layer: what the product wiki says about one product, read from frontmatter.
#
# For a product with a wiki, the oracle is grounded in documented facts instead of a
# hand-written claim list (#138). A product is named by a slug ("juice-shop"). Its
# Product Overview page carries "product" and "surfaces", and each Entity page about
# it carries "product", "features" and "facts". Each fact has a page-local id, a kind,
# its text and the id of one of the page's sources.
#
# product_errors checks those fields against the vocabulary and the page's own
# sources, so a bad page is caught before an oracle is built from it. No model calls.
#
# Code: engine/ontology/product.py, engine/ontology/heuristics/vocabulary.json,
# engine/tests/test_seeded_oracle.py

Feature: A product's surfaces, features and facts are read from its wiki
  As someone onboarding a product
  I want the product read from its wiki pages' frontmatter, with bad tags, kinds, sources and ids reported
  So that the oracle is built only from documented, checkable facts

  Scenario: The overview and entity pages make up the product
    Given the wiki has a page with "type" "Product Overview" and "product" "juice-shop"
    When load_product runs for "juice-shop"
    Then its "surfaces" are ["gui"]
    And its entities are every page under wiki/ with "type" "Entity" and "product" "juice-shop"
    And a product with no overview page gives nothing

  Scenario: An entity's slug is its file name without the product prefix
    Given the entity page "wiki/entities/juice-shop-login-page.md"
    When load_product runs for "juice-shop"
    Then the entity's "slug" is "login-page"
    And its "page" is "wiki/entities/juice-shop-login-page.md"
    And its "features" include "login"
    And its "title" is the page's "title", or the slug when there is none

  Scenario: A fact gets a global id and its source resolved to a file
    Given the login page has a fact with id "F1" citing the source id "screens"
    And the page's "screens" source has resource "docs/product-sources/juice-shop-screens-2026-09-30/S21.png"
    When load_product runs for "juice-shop"
    Then the fact's "id" is "juice-shop.login-page.F1"
    And its "local_id" is "F1"
    And its "source" is that resource path

  Scenario: Juice Shop's pages are a valid product layer
    When product_errors runs for "juice-shop"
    Then it returns no errors

  Scenario Outline: A bad product page is reported
    Given a product "demo" whose page "demo-home.md" has <problem>
    When product_errors runs for "demo"
    Then an error names the page and contains "<error>"

    Examples:
      | problem                                          | error                                                   |
      | the feature "teleport"                           | feature 'teleport' isn't in the vocabulary              |
      | fact F1 with kind "rumour"                       | demo.home.F1 has kind 'rumour', not one of              |
      | fact F2 citing source "nowhere"                  | demo.home.F2 cites a source the page doesn't list       |
      | a fact with no id                                | fact has no id                                          |
      | fact F1 with empty text                          | demo.home.F1 has no text                                |
      | fact F1 twice                                    | demo.home.F1 is used twice                              |

  Scenario: Surfaces and features are checked against the vocabulary
    Given the overview lists a surface that isn't "api" or "gui"
    When product_errors runs
    Then it reports "surface '<name>' isn't in the vocabulary"
    And an entity's "features" may use feature tags and surface tags, nothing else
    And a fact's "kind" must be one of "claimed", "shown", "rule" and "standard"

  Scenario: A product with no overview is one error
    When product_errors runs for "nothing"
    Then it returns only "no Product Overview page with product: nothing"
