# The product wiki under wiki/: a model of the product under test.
#
# The wiki describes the product being tested, not this engine. It is built the way
# a new tester is onboarded: from specs, tickets, screenshots and maps of the
# product. Engine code, oracle config and run results are out of scope; a test
# result belongs in context_<sut>.json.
#
# AGENTS.md is the schema. wiki/ is an Open Knowledge Format (OKF) v0.2 bundle, and
# a product's pages carry the frontmatter the oracle reads (#138). The first
# product is OWASP Juice Shop. wiki/index.md is generated and never edited by hand.
#
# Code: AGENTS.md, wiki/, .wiki-source/scripts/rebuild-index.mjs, qpf.config.yml

Feature: A product wiki describes the product under test
  As someone grounding the oracle in product knowledge
  I want wiki pages with a written schema, sources on every claim and a generated index
  So that the oracle can be built from documented facts and the wiki stays readable

  Scenario: The wiki is laid out by page type
    Given the wiki follows AGENTS.md
    Then the Product Overview is "wiki/overview.md"
    And Source Summaries are in "wiki/summaries/", one per raw source
    And Entities are in "wiki/entities/", with their kind in "entity_kind"
    And Quality Concepts are in "wiki/concepts/"
    And Log Entries are in "wiki/log/<date>.md"
    And pages for a product start with its slug, like "juice-shop-login-page.md"

  Scenario: Today the wiki covers Juice Shop
    When I look in wiki/
    Then "overview.md" has "product" "juice-shop" and "surfaces" [gui]
    And "entities/" has the screens "juice-shop-start-page", "juice-shop-product-list", "juice-shop-product-details-dialog" and "juice-shop-login-page"
    And "summaries/" has the Spoor maps of 2026-09-29 and 2026-09-30
    And there are no Quality Concepts yet

  Scenario: Every page has OKF frontmatter
    Given a page under wiki/ other than index.md
    Then it has a YAML frontmatter block with a non-empty "type"
    And each entry in "sources" has an "id" and a "resource" pointing at a repo path
    And claims in the body cite a footnote keyed to a source id, like "[^screens]"
    And timestamps are full ISO 8601 datetimes with a UTC offset, like "2026-08-25T09:00:00Z"
    And actors are prefixed, like "human:<id>" or "<producer>/<version>"

  Scenario: Sources that can't be committed as they are get a trimmed export
    Given Spoor's map lives in the gitignored ".spoor-cache/", which holds raw captures with secrets
    Then the page cites a trimmed export in "docs/product-sources/"
    And a few screenshots of a local test target may be copied there too

  Scenario: Entity pages carry the fields the oracle reads
    Given an Entity page about "juice-shop"
    Then it has "product" "juice-shop"
    And "features" with tags from trailhound/ontology/heuristics/vocabulary.json
    And "facts", each with an "id" unique on the page, a "kind", its "text" and a "source" from the page's "sources"
    And trailhound/tests/test_seeded_oracle.py checks those fields

  Scenario: The index is generated from the pages
    When I run "node .wiki-source/scripts/rebuild-index.mjs --dir ."
    Then it rewrites "wiki/index.md"
    And the index's only frontmatter is "okf_version" "0.2"
    And it carries a comment saying it is derived and not to be hand-edited
    And it has the sections "Overview", "Summaries", "Entities" and "Concepts"
    And each entry is "* [<title>](<path>) - <description>", sorted by title
    And an entity's entry starts its description with its kind, like "(screen)"
    And a section with no pages shows "_none yet_"
    # Log Entries are not listed in the index.

  Scenario: The script needs qpf.config.yml at the root
    Given "--dir ." points at the repo root
    When rebuild-index.mjs runs without a "qpf.config.yml" there
    Then it prints that the file was not found and exits with code 1
    And with no "guidelines/guidelines.yml" it warns and skips the guidelines step
