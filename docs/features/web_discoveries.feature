# web_gui discoveries: screens beyond the carried map are recorded and join the run's map.
#
# A crawler's map is never complete. When an action reaches a screen whose signature
# isn't in the carried map, the result records it as "discovered", in the shape of a
# map state: an id from its signature, the full path from the start, and its controls
# run through web-recon's safety gate (#157). It also joins this run's map (#158), so
# from the next round the Driver can act on its cleared controls by naming the
# screen's id as the state, and the harness reaches it by replaying the steps that
# found it. A screen more than 6 steps from the start doesn't join, so a chain of
# discoveries can't wander off. A discovery is judged against the map as carried in,
# so it is still recorded when it's reached again after joining. The full record
# stays in output.json, but the Driver sees its controls once and then just its id.
#
# Code: engine/adapters/web_gui/session.py (discovery, discovery_id, Session.act,
# _MAX_DISCOVERY_STEPS), engine/adapters/web_gui/reference.py (add_discovery),
# engine/adapters/web_gui/adapter.py (redact_history_for_model)

Feature: Screens beyond the map are recorded and join the run's map
  As someone testing more than the crawler found
  I want each screen the map didn't have recorded, and made a state the Driver can act on
  So that the run's own exploration isn't thrown away and it can go deeper than its starting map

  Scenario: A sent action that lands on an unmapped screen records it
    Given a test on "st01 :: button:A"
    When the action is sent and lands on a signature the carried map doesn't have
    Then the result has "discovered" with:
      | field            | value                                                       |
      | id               | "d" followed by 8 hex characters from the signature         |
      | signature        | the signature after the click                               |
      | url, title       | the page's URL and title                                    |
      | from_state, via  | "st01" and "button:A"                                       |
      | path             | the path to "st01" plus the step for "button:A"             |
      | elements         | every control on the screen, each with "committing"         |
      | controls_offered | how many controls the safety gate would let the crawl press |
      | in_run_map       | whether it joined this run's map                            |

  Scenario Outline: A discovered screen's controls go through the safety gate
    Given an unmapped screen with the button "<control>"
    When it is recorded as discovered
    Then that element has "committing": <committing>

    Examples:
      | control        | committing |
      | Show orders    | false      |
      | Delete account | true       |

  Scenario: A screen in the carried map is not a discovery
    When a sent action lands on a signature the carried map has
    Then the result has no "discovered"

  Scenario Outline: A discovery joins the run's map only if it is close enough to the start
    Given a discovered screen whose path from the start has <steps> steps
    When it is added to the run's map
    Then <joined>

    Examples:
      | steps | joined                                                         |
      | 2     | it becomes a state with its id, and "in_run_map" is true       |
      | 6     | it becomes a state with its id, and "in_run_map" is true       |
      | 7     | it is left out, and "in_run_map" is false                      |

  Scenario: A joined screen is acted on like any mapped state
    Given a discovered screen "d1a2b3c4" joined the run's map with "button:Go" (not committing) and "button:Buy" (committing)
    When the Driver casts the next round
    Then "d1a2b3c4 :: button:Go" is a pair the validator and execute_test accept
    And "d1a2b3c4 :: button:Buy" is not a pair
    And the plan for "d1a2b3c4 :: button:Go" replays the steps that found the screen
    And its signature now counts as known, so reaching it again is "known_screen"
    But it is still not in the carried signatures, so reaching it again is still recorded as "discovered"

  Scenario: Adding the same discovery twice is harmless
    Given "d1a2b3c4" already joined the run's map
    When it is added again
    Then the same state id comes back and nothing is duplicated

  Scenario: The Driver sees a discovery's controls once, then just its id
    # At most 30 controls are named; the rest are counted in "controls_more".
    Given two test entries in the history that both discovered "d1234abcd", which joined the run's map
    When the history is redacted for the Driver
    Then the first entry's "discovered" is the id and "controls": the named, non-committing control keys, sorted
    And the second entry's "discovered" is just the id
    And output.json still holds the full record with every element
