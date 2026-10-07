# Picking heuristics for a SUT: select_heuristics.
#
# The library is far bigger than any prompt should carry, so only the heuristics
# that fit the SUT's surface are kept, and those matching its features rank higher.
# A heuristic with no surface tag fits every surface.
#
# The surface bonus exists because, without it, a GUI run's top slice was all
# field-level checks, and ones like overlay_blocking never made the cut. Both
# bonuses are small on purpose: base weights are 1 to 3, so a heuristic always
# stays below a grounded claim's base score of 5.0.
#
# Code: trailhound/ontology/oracle_creator.py (select_heuristics, SURFACE_MATCH_BONUS,
# FEATURE_MATCH_BONUS), trailhound/tests/test_heuristic_library.py

Feature: Heuristics are picked by surface and feature
  As someone testing a particular kind of system
  I want heuristics for another surface left out, and ones matching the SUT's surface and features scored up
  So that a web app gets GUI heuristics, an API gets API ones, and the best fit comes first

  Scenario Outline: A heuristic for another surface is left out
    Given a heuristic tagged "<tags>"
    When select_heuristics runs with surfaces <surfaces>
    Then the heuristic is <kept>

    Examples:
      | tags           | surfaces  | kept     |
      | gui, usability | ("api",)  | left out |
      | gui, usability | ("gui",)  | kept     |
      | boundary       | ("api",)  | kept     |
      | gui, usability | None      | kept     |

  Scenario Outline: The score is the base weight plus the bonuses that apply
    Given a heuristic with "base_weight" 2 tagged "<tags>"
    When select_heuristics runs with surfaces ("gui",) and features ("login",)
    Then its score is <score>

    Examples:
      | tags     | score |
      | boundary | 2.0   |
      | gui      | 2.5   |
      | login    | 3.0   |

  Scenario: With surfaces None nothing gets the surface bonus
    Given a heuristic with "base_weight" 2 tagged "gui"
    When select_heuristics runs with surfaces None
    Then its score is 2.0

  Scenario: The best fit comes first
    Given heuristics "plain" tagged "boundary", "gui" tagged "gui" and "login" tagged "login", each with "base_weight" 2
    When select_heuristics runs with surfaces ("gui",) and features ("login",)
    Then the order is "login", "gui", "plain"

  Scenario: Equal scores keep the library's order
    Given two heuristics with the same score
    When select_heuristics sorts them
    Then the one earlier in the library comes first

  Scenario: The limit is applied after sorting
    Given heuristics "plain" tagged "boundary", "gui" tagged "gui" and "login" tagged "login", each with "base_weight" 2
    When select_heuristics runs with surfaces ("gui",) and limit 1
    Then only "gui" is returned
    And without a limit every fitting heuristic is returned

  Scenario: No heuristic reaches a grounded claim's score
    When select_heuristics runs over the whole library with surfaces ("gui",) and every feature tag in the vocabulary
    Then the best score is below GROUNDED_BASE_SCORE 5.0
