# web_gui action space: the Driver can only name (state, control) pairs from the map.
#
# The carried map is a web-recon ontology.json: states, the controls on each, and the
# transitions the recon saw. Its read-only safety gate marks each control committing
# or not. The adapter turns that into the whole action space. There is no free CSS
# selector and no coordinate, so the Driver can't name anything that submits, deletes,
# buys or sends. The check fails closed: a control is only offered when it says
# "committing": false outright, so a hand-edited or foreign map with a missing flag
# offers less, never more. A pair outside the map is refused by the casting validator,
# and refused again in execute_test in case one slips through.
#
# Code: engine/adapters/web_gui/reference.py (Reference), engine/adapters/web_gui/adapter.py
# (validate_casting_response, execute_test), engine/adapters/web_gui/session.py (valid_pairs)

Feature: The Driver can only act on controls the map cleared as safe
  As someone testing a real environment
  I want the action space to be the map's cleared (state, control) pairs and nothing else
  So that nothing the Driver can name changes data in the app

  Background:
    Given a map with states "st01" (first_seen 0) and "st02"
    And a "navigate" transition from "st01" to "st02" by clicking "button:A"
    And "st01" has controls "button:A" and "button:Dead" with "committing": false
    And "st02" has "button:Back" with "committing": false and "button:Buy" with "committing": true

  Scenario: The action space is the named, non-committing controls on reachable states
    When the map is loaded
    Then the entry state is "st01", the state seen first
    And the pairs are "st01 :: button:A", "st01 :: button:Dead" and "st02 :: button:Back"
    And "st02 :: button:Buy" is not a pair

  Scenario Outline: A control is left out unless every rule lets it in
    Given "st01" also has a control <case>
    When the map is loaded
    Then that control is not a pair

    Examples:
      | case                                     |
      | with no "committing" key at all          |
      | with "committing": true                  |
      | with an empty name                       |
      | on a state no navigate edge reaches      |

  Scenario: Each state is reached by its shortest path of navigate edges from the entry
    # Breadth-first over "navigate" edges only. Edges back to the same state, to
    # "external", or to a state not in the map don't count.
    When the map is loaded
    Then the plan for "st01 :: button:A" has an empty path
    And the plan for "st02 :: button:Back" has the path of one step: role "button", name "A", locator "#a"
    And its target is role "button", name "Back", locator "#back"

  Scenario: The Driver is briefed with exactly the action space
    When the map's Driver briefing is written
    Then each reachable state gets a line with its id, a short label and "the start screen" or "N navigation(s) from the start"
    And under it one line per pair, written "st01 :: button:A"
    And a state with no pairs shows "(no safe controls found here)"
    And "button:Buy" does not appear anywhere in the briefing

  Scenario: The casting validator refuses a pair outside the map once the session is live
    Given the session is ready
    When the Driver casts a test on "st01 :: button:Ghost"
    Then validate_casting_response returns an error saying it "is not a (state, control) pair in the carried map"
    And the round is sent back to the Driver instead of run

  Scenario: Before the session is ready the validator only checks the shape
    # valid_pairs() is empty until check_ready has run, so validation degrades to
    # shape checks rather than raising.
    Given no session is ready
    When the Driver casts a well-formed test on "st01 :: button:Ghost"
    Then validate_casting_response returns no errors

  Scenario: execute_test refuses a pair outside the map again
    Given a test on "st01 :: button:Ghost" reaches execute_test
    When it runs
    Then nothing is clicked
    And the result has "skipped": true and "prediction_matched": false
    And its "skip_reason" says "st01 :: button:Ghost is not a pair in this run's map (carried or discovered)."
    And its outcome has effect "unknown" and accepted false
