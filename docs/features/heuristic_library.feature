# The heuristic library: generic testing heuristics, one JSON file per source.
#
# The oracle needs ideas that don't depend on any one product: boundaries, attacks,
# usability and accessibility checks. They used to sit in one file
# (engine/ontology/heuristics.json). Issue #128 split them into a library with one
# file per source and a fixed tag vocabulary, so the Oracle can pick the ones that
# fit a SUT by tag instead of sending all of them.
#
# The loader reads every file except vocabulary.json and copies the file's "source"
# onto each heuristic. The tests check every entry against the vocabulary.
#
# Code: trailhound/ontology/oracle_creator.py (load_heuristics, load_vocabulary),
# trailhound/ontology/heuristics/*.json, trailhound/tests/test_heuristic_library.py

Feature: A tagged library of testing heuristics, one file per source
  As someone deciding what to test
  I want generic heuristics from known sources, each tagged from a fixed vocabulary
  So that the Oracle can pick the ones that fit a SUT and say where each came from

  Scenario Outline: Each source file holds the heuristics from one source
    When the library is loaded
    Then "<file>" contributes <count> heuristics

    Examples:
      | file             | count |
      | core.json        | 9     |
      | hendrickson.json | 20    |
      | htsm.json        | 26    |
      | nielsen.json     | 10    |
      | techniques.json  | 9     |
      | wcag.json        | 13    |
      | web.json         | 18    |
      | whittaker.json   | 13    |

  Scenario: The loader reads the files in name order and skips the vocabulary
    When load_heuristics runs
    Then it returns 118 heuristics
    And it reads the files in sorted file-name order, keeping each file's order
    And "vocabulary.json" is not read as a source of heuristics

  Scenario: The loader adds the file's source to every heuristic
    Given "htsm.json" has a top-level "source" naming the Heuristic Test Strategy Model
    When load_heuristics runs
    Then every heuristic from "htsm.json" has that text as its "source"
    And the heuristic entries in the file itself carry no "source" field

  Scenario: Every heuristic has the same fields
    When the library is loaded
    Then every heuristic has "id", "name", "kind", "description", "apply", "tags", "base_weight" and "source"
    And "id" is lowercase letters, digits and underscores, starting with a letter
    And "name", "description", "apply" and "source" are non-empty strings
    And "base_weight" is 1, 2 or 3
    And "tags" is a non-empty list

  Scenario: Kinds and tags come from vocabulary.json
    Given vocabulary.json defines the kinds "technique", "attack", "oracle", "quality_criterion" and "product_model"
    And it defines tag facets "surface", "feature" and "quality"
    And the surface tags are "api" and "gui"
    When test_heuristic_library runs
    Then every heuristic's "kind" is one of those kinds
    And every one of its tags appears in one of the three facets
    # A heuristic with no surface tag applies to every surface.

  Scenario: Ids are unique across all source files
    When test_heuristic_library runs
    Then no heuristic id appears twice, even in different files

  Scenario: The original ids are kept so old runs and context still match
    When the library is loaded
    Then it still has "goldilocks", "boundary_edges", "zero_and_negative", "alphabet_soup", "monetary_precision", "empty_and_null", "duplicate_replay", "ordering_race" and "sensitive_data_exposure"
    And "self_consistency" is not in the library
    # It is an oracle principle, so it moved to the FEW HICCUPPS seeds with its id (#138).
    And "self_consistency" is a seed id in trailhound/ontology/seeds/

  Scenario: The library text has no long dashes
    When test_heuristic_library runs
    Then no "name", "description", "apply" or "source" contains an em dash or an en dash
