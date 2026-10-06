# Spoor conversion: a Spoor map becomes the ontology.json web_gui reads.
#
# web_gui recognises where it is by web-recon's live page signature, and Spoor's saved
# map can't produce that signature: it has no URL, no headings and no DOM control list,
# and it names controls from the accessibility tree. So from_spoor is live (issue
# #113): it replays Spoor's paths in a fresh browser, captures each page the way
# web-recon does, and writes web-recon's shape ("web-recon/1") from what it saw. No
# model call. Spoor feeds the context (#310), so the map keeps everything Spoor
# reached: testing fully (#299), every step whose control is found live is followed,
# Add to Basket and Checkout included, so the screens behind them reach the map. Only
# logging out is refused, and on a part tagged careful, anything the read-only gate
# wouldn't click. The gate's verdict stays on each control as "committing" (it changes
# data). A modal hides the page behind it from Spoor, but the DOM still lists those
# controls, and clicking them landed on the backdrop (issue #121): they're kept and
# marked "spoor_reached": false.
#
# Code: engine/adapters/web_gui/from_spoor.py. Tests: engine/tests/test_from_spoor.py

Feature: A Spoor map is converted into web_gui's site map by replaying it live
  As someone onboarding a web app
  I want from_spoor to replay Spoor's paths in a real browser and keep everything stable it reaches
  So that what Spoor found feeds the engine, the screens behind data-changing steps included

  Background:
    Given a Spoor saved map for "http://127.0.0.1:3000"

  Scenario: Paths are replayed and pages with one signature are merged
    Given Spoor states "S1" and "S2" both show the same page once replayed
    And Spoor has a transition from "S0" back to "S0"
    When I run "python -m engine.adapters.web_gui.from_spoor --map <map> --url http://127.0.0.1:3000 --out <ontology.json>"
    Then "S1" and "S2" become one state, and states are numbered "st01", "st02" in the order they were first reached
    And the self-loop on "S0" is not written as a transition
    And each written transition has effect "navigate" and a "click" action on the live element's locator
    And the ontology has schema "web-recon/1" and target url "http://127.0.0.1:3000"

  Scenario: Every page is replayed twice, and an unstable one is dropped
    # live_observer reboots to a fresh browser context before each replay.
    Given a Spoor state whose path fails to replay, or reaches a different signature the second time
    When the map is converted
    Then that Spoor state is listed in "dropped_unstable"
    And no state is written for it, and its onward paths are not followed

  Scenario Outline: A Spoor step is followed when its live element is found
    # Names can differ: Juice Shop's "Help getting started" is "school Help getting
    # started" to web-recon, the "school" being an icon's ligature text. An exact
    # match (after normalising) is tried first, then the one element of that role
    # whose name contains Spoor's.
    Given on the live page Spoor's step is "button" named "<spoor name>"
    And the live page has <live elements>
    When the map is converted
    Then the step is <result>

    Examples:
      | spoor name           | live elements                                                       | result                                                                                              |
      | Help getting started | one button "school Help getting started"                            | followed, clicking that button's locator                                                            |
      | Delete account       | one button "Delete account"                                         | followed: testing fully, a step that changes data is followed too                                   |
      | Juice                | buttons "Juice A" and "Juice B"                                     | refused as "button:Juice (more than one on the live page)"                                          |
      | Apple Juice (1000ml) | one unnamed button, whose accessible name is "Apple Juice (1000ml)" | followed by its accessible name, with no locator: the replay finds it with Playwright's role lookup |
      | Logout               | one button "Logout"                                                 | refused as "button:Logout (it logs out)"                                                            |

  Scenario: On a part tagged careful, the read-only gate decides
    # A step found only by its accessible name isn't in the page capture, so the gate
    # can't judge it: on a careful part it isn't followed.
    Given the target's careful tags (from --product, or WEB_GUI_PRODUCT) cover the page "/"
    When Spoor's step there is "Delete account"
    Then it is refused as "button:Delete account (tagged careful, and the read-only gate wouldn't click it)"

  Scenario: Each control keeps the gate's verdict as information
    Given a live page with a button "Delete account" and a button "Close Banner" that Spoor found
    When the map is converted
    Then "Delete account" is written with "committing" true, and "Close Banner" with "committing" false
    And the Driver's guide shows "button:Delete account (changes data)", and the sweep leaves it out

  Scenario Outline: A control Spoor couldn't use there is kept and marked
    # Checked across every Spoor state merged into the page.
    Given a live button "<name>"
    And on that page Spoor <spoor saw>
    When the map is converted
    Then "<name>" is written with "spoor_reached" false, and counts towards "hidden_controls"
    And the sweep leaves it out, and the Driver's guide shows it with "(behind a dialog, or not reached by the recon)"

    Examples:
      | name         | spoor saw                                                         |
      | Open Sidenav | did not list it as an action (it was behind a modal dialog)       |
      | Next page    | listed it, but also skipped it ("blocked by an unresolved layer") |

  Scenario: A map can be made behind a login with --session
    Given a session saved as ".sessions/juice-shop/logged-in.json"
    When I run from_spoor with "--session .sessions/juice-shop/logged-in.json"
    Then every replay starts from a fresh context loaded from that session
    And the written ontology has session.session_name "logged-in"
    # A run started from a different session then warns (see saved_session.feature).

  Scenario: The summary says what was converted and names the refused steps
    When a conversion finishes
    Then it prints one line with the Spoor states, the states and transitions written, the number dropped as unstable, the steps not followed and the controls Spoor couldn't reach (kept, marked)
    And a second line "  refused:" lists each step not followed as "role:name (why)"
    And a character the console can't encode (an icon font's private-use character, issue #150) is printed as "?"

  Scenario Outline: A map not in the format the converter reads is refused before a browser starts
    # map_errors is the contract with Spoor's saved map format (issue #144).
    Given the map's exploration block <problem>
    When I run from_spoor
    Then it stops with "this Spoor map isn't in the format the converter reads (#144):" followed by "<error>"

    Examples:
      | problem                                          | error                                                 |
      | has no "skipped" list                            | exploration.skipped is missing or not a list          |
      | has a transition with "source" instead of "from" | transitions[0] isn't {from, to, action: {role, name}} |
      | has a state with no string "id"                  | states[0] has no string id                            |
