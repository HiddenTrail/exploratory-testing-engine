# Starting a test as a new tab: what a second tab of the logged-in browser gets.
#
# Tabs of one browser share cookies and localStorage, but each has its own
# sessionStorage. A logged-in Juice Shop user who opened the shop in a new tab got an
# empty basket and "TypeError: Cannot read properties of null (reading 'Products')",
# because the basket id lives in sessionStorage. A person found that; the engine
# couldn't, because since #228 every test starts as the tab the session was saved from.
# So a test may set start_as to "new_tab" (issue #249). The library's multiple_tabs
# heuristic is the idea behind it (in the oracle since #246).
#
# Code: trailhound/adapters/web_gui/session.py (START_AS, Session.act, has_session,
# Session._open_fresh_page), trailhound/adapters/web_gui/adapter.py (CASTING_TOOL,
# validate_casting_response, execute_test, outcome_for, describe_test_for_log,
# render_test_entry). Tests: trailhound/tests/test_web_gui_adapter.py

Feature: A web_gui test can start as a new tab of the logged-in browser
  As a tester of an app behind a login
  I want a test to start the way a user's second tab would
  So that state an app keeps per tab, like a basket, is tested where users lose it

  Scenario: A new tab gets the saved cookies and localStorage, but no sessionStorage
    Given WEB_GUI_SESSION points at a session file with the sessionStorage entry "bid"
    When a test with start_as "new_tab" reboots the browser
    Then its context is loaded from the session file
    And the script that puts sessionStorage back is not added
    And the next test without start_as gets the sessionStorage back

  Scenario: The result says the test started as a new tab
    When a test with start_as "new_tab" runs
    Then its request has "start_as": "new_tab" and its result has "started_as": "new_tab"
    And its outcome's action_id ends with "(as a new tab)", so it isn't the same action as from the same tab
    And the log and the report show the action with "(as a new tab)"
    And a test without start_as has neither field

  Scenario: A new-tab test learns its own idle background and adds no screens to the map
    When a test with start_as "new_tab" reaches its state for the first time this run
    Then the idle noise is learned under "<state>@new_tab", apart from the same tab's
    # Its path would only replay from a new tab, and the run's map replays from the same tab.
    And a screen it reaches that the map doesn't have is not recorded as discovered

  Scenario Outline: start_as is checked when the tests are cast
    Given the run <session>
    When the Driver casts a test with start_as "<start_as>"
    Then the answer is <verdict>

    Examples:
      | session                     | start_as  | verdict                                                  |
      | starts from a saved session | new_tab   | accepted                                                 |
      | starts from a saved session | same_tab  | accepted                                                 |
      | starts from a saved session | incognito | rejected: "start_as must be one of: same_tab, new_tab"   |
      | has no saved session        | new_tab   | rejected: it says a new tab is the same as any test here |

  Scenario: The same basket test differs between the same tab and a new tab
    # Ran live on the local Juice Shop, no model calls (#249).
    Given a saved logged-in Juice Shop session
    When "st01 :: button:Show the shopping cart" runs as the same tab, then as a new tab
    Then the same tab has no console errors
    And the new tab's console_errors has "TypeError: Cannot read properties of null (reading 'Products')"
    And compare_replay of the two says they are not the same
