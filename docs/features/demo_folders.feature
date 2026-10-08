# The wiki and the heuristic library can live in another folder (#384). A demo on a product
# the engine has never seen keeps all its layers in one scratch folder, so nothing touches
# the committed wiki/ or trailhound/ontology/heuristics/. The context folder could already be
# moved with TRAILHOUND_CONTEXT_DIR. A demo's library also carries its own vocabulary.json,
# because a new product may need feature tags the shared one doesn't have.
#
# Code: trailhound/ontology/product.py (wiki_folder), trailhound/ontology/oracle_creator.py
# (heuristics_dir). Tests: trailhound/tests/test_seeded_oracle.py

Feature: The wiki and the heuristic library can be read from another folder
  As someone demoing a product the engine has never seen
  I want to point it at my own wiki and library folders
  So that the committed wiki and library stay as they are

  Scenario: Nothing is set
    Given TRAILHOUND_WIKI_DIR and TRAILHOUND_HEURISTICS_DIR are not set
    Then the wiki is read from wiki/ and the heuristics from trailhound/ontology/heuristics/

  Scenario: Both are set
    Given TRAILHOUND_WIKI_DIR is a folder with a product's pages
    And TRAILHOUND_HEURISTICS_DIR is a copy of the library with one more feature tag in vocabulary.json
    When the oracle is built for that product
    Then the pages are read from the first folder
    And the heuristics and the vocabulary are read from the second
    And a page that uses the extra tag has no vocabulary error

  Scenario: A wiki folder is passed in code
    Given a caller passes wiki_dir to load_product, product_errors or build_oracle
    Then that folder is used, whatever TRAILHOUND_WIKI_DIR says
