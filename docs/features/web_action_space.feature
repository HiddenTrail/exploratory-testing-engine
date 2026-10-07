# web_gui tests: a start and steps on the live page; the map is a guide, not a limit.
#
# Until #310 the map was the whole action space: the Driver could only name a (state,
# control) pair the recon had reached and the read-only gate had cleared, so a webshop's
# basket, checkout, login and forms were out of reach, and the oracle's top ideas with
# them. That was a design error. Spoor feeds the context; it never decides what the
# Driver may do. Now a test starts from a route on the site or a screen the map knows,
# then runs up to 6 steps on whatever is on the page. Safety lives in the engine: the
# browser never leaves the site (#308), careful tags (#299, see web_careful.feature), the
# spending limits.
#
# The map still gives the screens a test can start from by id (their paths), and the
# sweep its pairs.
#
# Code: trailhound/adapters/web_gui/adapter.py (CASTING_TOOL, validate_casting_response,
# execute_test, API_SCHEMA_DOC, SAFETY_NOTE), session.py (act_steps, _do_step, _find_live,
# _reach, STEP_KINDS, MAX_STEPS), reference.py (Reference, driver_briefing)

Feature: A web test is a start and a few steps on the live page
  As someone testing a web product
  I want the Driver to act on whatever is on the page, the way a person would
  So that the product's forms, basket and flows can be tested, not only what a recon reached

  Background:
    Given a map with states "st01" (first_seen 0) and "st02"
    And a "navigate" transition from "st01" to "st02" by clicking "button:A"
    And "st01" has controls "button:A" and "button:Dead" with "committing": false
    And "st02" has "button:Back" with "committing": false and "button:Buy" with "committing": true

  Scenario: A test has a start and up to 6 steps
    Then a cast test has "start": a route on the site like "/#/basket", or a screen id like "st02"
    And "steps": 1 to 6 of "click", "fill", "select" (each with "role" and "name"), "goto" (a route as "value") and "back"
    And "fill" and "select" have the "value" to type or choose, and a step can have "nth" (from 1)

  Scenario: The validator checks the shape, never the map
    When the Driver casts a test on a control the map doesn't have, or from a route it doesn't have
    Then validate_casting_response returns no errors
    But a step without what its kind needs is sent back, for example "steps[1] (click) needs a 'name'"
    And a "goto" that isn't a route on the site is sent back

  Scenario Outline: Each step is judged on the page when it runs
    Given the test reached its start
    When a step <does>
    Then the step's status is "<status>", and the steps after a step that isn't done don't run

    Examples:
      | does                                                           | status    |
      | clicks an element that is on the page                          | done      |
      | clicks an element nothing on the page has the role and name of | not_found |
      | clicks "Checkout" on a part tagged careful (see web_careful)    | refused   |
      | fills a search box with the Driver's value                     | done      |
      | fills any field with the Driver's value, testing fully         | done      |
      | goes to "/logout" (refused everywhere, see web_careful)        | refused   |
      | goes back                                                      | done      |

  Scenario: An element is found by role and name on the live page
    Then the exact name is tried first, then the same name in any case, then a name that contains it if only one does
    And an empty name is a name too ("link:" for a product image), and "nth" picks among several in page order
    And a step whose "nth" is past the last match is "not_found"
    And when the page capture has no element by that name, the browser's accessibility tree is asked, where Spoor's names come from: a Juice Shop product card is "button:Apple Juice (1000ml)" there and an unnamed button in the capture

  Scenario: What a test's result tells the Driver
    Then the result has "steps", each with its status and why: a failed one too (see step_reasons.feature)
    And "page_controls": what's on the page after the last step as "role:name", with a count like "button: (x13)" when several share it, at most 40, with "page_controls_more" past that
    And a control with no name that the capture gave a hint is listed on its own with its nth, like "textbox: nth 1 (in the toolbar, ...)" (#325)
    And "action" reads like "st02 :: button:Back" or "/ :: button:Open Sidenav > goto /#/contact"
    And the log line of a test where nothing ran says why, like "NOT RUN - button:Checkout: refused"

  Scenario: A start the run doesn't know is a result, not a retry
    When a test starts from "basket", which is neither a route nor a screen this run knows
    Then nothing runs, and the result has "skipped": true and a skip_reason saying to start from a route or a screen id

  Scenario: A screen a test reaches is reached again the same way
    When a test reaches a screen the map doesn't have
    Then its discovery's path is the start (a route, or the screen's own path) and the steps that ran, with what was typed
    And a later test can start from its id

  Scenario: The map is a guide with routes
    When the map's Driver briefing is written
    Then each reachable screen gets a line with its id, a short label, "route <route>" and how far it is from the start
    And under it the controls the recon found, one per line as "role:name"

  Scenario: The map still gives the sweep its pairs and each screen its path
    When the map is loaded
    Then the entry state is "st01", the state seen first
    And the pairs are "st01 :: button:A", "st01 :: button:Dead" and "st02 :: button:Back", and not "st02 :: button:Buy"
    And "st02" is reached by its shortest path of navigate edges: one step, role "button", name "A", locator "#a"

  Scenario: A test cast before #310 still runs
    When a test with "state_id" and "control_key" runs, as an older run's replay does
    Then it runs as a start at that screen and one click, or a fill for a text box
