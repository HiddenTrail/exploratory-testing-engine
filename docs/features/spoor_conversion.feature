# Spoor conversion: a Spoor map becomes the ontology.json web_gui reads.
#
# web_gui recognises where it is by web-recon's live page signature, and Spoor's saved
# map can't produce that signature: it has no URL, no headings and no DOM control list,
# and it names controls from the accessibility tree. So from_spoor is live (issue
# #113): it replays Spoor's paths in a fresh browser, captures each page the way
# web-recon does, and writes web-recon's shape ("web-recon/1") from what it saw. No
# model call. Safety fails closed: Spoor's own skipped list isn't trusted as a
# destructive filter, because Spoor treats 127.0.0.1 as a sandbox and fires
# destructive actions there. A modal hides the page behind it from Spoor, but the DOM
# still lists those controls, and offering them meant clicks landed on the backdrop
# and only closed the dialog (issue #121).
#
# Code: engine/adapters/web_gui/from_spoor.py. Tests: engine/tests/test_from_spoor.py

Feature: A Spoor map is converted into web_gui's site map by replaying it live
  As someone onboarding a web app
  I want from_spoor to replay Spoor's paths in a real browser and keep only what is stable and safe
  So that the default crawler can feed the engine without letting a destructive step into the map

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

  Scenario Outline: A Spoor step is only followed if the gate lets the crawl click its live element
    # Names can differ: Juice Shop's "Help getting started" is "school Help getting
    # started" to web-recon, the "school" being an icon's ligature text. An exact
    # match (after normalising) is tried first, then the one element of that role
    # whose name contains Spoor's.
    Given on the live page Spoor's step is "button" named "<spoor name>"
    And the live page has <live elements>
    When the map is converted
    Then the step is <result>

    Examples:
      | spoor name           | live elements                            | result                                    |
      | Help getting started | one button "school Help getting started" | followed, clicking that button's locator  |
      | Juice                | buttons "Juice A" and "Juice B"          | refused as "button:Juice" (ambiguous)     |
      | Checkout             | no button containing "Checkout"          | refused as "button:Checkout" (no match)   |
      | Delete account       | one button "Delete account"              | refused as "button:Delete account" (gate) |

  Scenario: A control is offered only if web-recon's gate clears it as captured live
    Given a live page with a button "Delete account" and a button "Close Banner" that Spoor found
    When the map is converted
    Then "Delete account" is written with "committing" true
    And "Close Banner" is written with "committing" false

  Scenario Outline: A control the gate cleared is still left out if Spoor couldn't use it there
    # Checked across every Spoor state merged into the page.
    Given a live button "<name>" that web-recon's gate would let the crawl click
    And on that page Spoor <spoor saw>
    When the map is converted
    Then "<name>" is written with "committing" true
    And it counts towards "hidden_controls"

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
    Then it prints one line with the Spoor states, the states and transitions written, the number dropped as unstable, the steps refused by the safety gate and the controls left out because Spoor couldn't reach them
    And a second line "  refused:" lists each refused step as "role:name"
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
