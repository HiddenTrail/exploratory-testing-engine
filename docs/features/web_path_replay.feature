# web_gui path replay: every test starts clean and walks the mapped path to its state.
#
# Tests must not depend on each other, so each act starts a new browser context and
# opens the base URL, then replays the shortest known path to the state the test
# names. A new context means no cookies, storage or cache carry over (or only those
# of the saved session, when one is set). Before that fix, Juice Shop remembered a
# dismissed welcome banner in a cookie and every later restart landed on a different
# start screen (#117). A replay that doesn't arrive is reported as
# reached_target_state false, and the control is then not clicked at all. A capture
# that doesn't match the state it should be is taken again up to twice, because a
# page still loading reads as another state: Juice Shop's paginator renders after the
# product list, so an early capture was missing two controls (#131).
#
# Code: trailhound/adapters/web_gui/session.py (Session.act, _reboot, _open_fresh_page,
# _replay, _capture_expecting)

Feature: Each test reaches its state by replaying the mapped path
  As someone who needs independent tests
  I want each test to start in a fresh browser, replay the shortest known path to its state, and say whether it got there
  So that tests don't depend on each other, and a drifted path is visible

  Scenario: Every restart opens a new browser context and closes the old one
    Given a session whose first context is open
    When the session reboots twice
    Then 3 contexts have been created
    And the first two are closed
    And the page in use belongs to the third, which has opened only the base URL

  Scenario Outline: A fresh context starts empty or from the saved session
    Given WEB_GUI_SESSION is <session>
    When a fresh context is opened
    Then its storage_state is <storage_state>
    And its viewport is 1280 by 900

    Examples:
      | session                      | storage_state         |
      | unset                        | empty                 |
      | ".sessions/x/logged-in.json" | loaded from that file |

  Scenario: A test replays its state's path step by step, resting after each
    Given a test on "st02 :: button:Back", where "st02" is one click on "button:A" from the start
    When the test runs
    Then the session reboots to the base URL
    And "button:A" is actuated, then the page is left to rest
    And the page is captured, expecting the signature the map has for "st02"

  Scenario Outline: reached_target_state says whether the replay really arrived
    Given a test on a state whose path <replay>
    When the test runs
    Then "reached_target_state" is <reached>
    And "verdict" is "<verdict>"

    Examples:
      | replay                                                    | reached | verdict      |
      | replays and lands on the state's signature                | true    | sent         |
      | replays but lands on a different signature                | false   | not_actuated |
      | stops at a step that can't be actuated                    | false   | not_actuated |

  Scenario: A capture that doesn't match the expected state is taken again up to twice
    Given the expected signature is "ready"
    And the page reads as "loading", then "loading", then "ready"
    When the session captures the page expecting "ready"
    Then it waits 700 ms before each of 2 more captures
    And the capture it returns is "ready"

  # The same retake is used for the start page at the baseline, for the state a test
  # targets, and for the start page after a recovery. The capture after the click is
  # taken once.
  Scenario: A state that still differs after the retries is reported as it is
    Given the page reads as "elsewhere" every time
    When the session captures the page expecting "ready"
    Then the capture it returns is "elsewhere"

  Scenario: The result says which state the test meant to start from
    When a test on "st02 :: button:Back" runs
    Then "intended_before" is the map's signature for "st02"
    And "screen_before" is the signature actually read before the click
