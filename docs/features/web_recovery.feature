# web_gui recovery: after a move to a new screen, check the app gets back to its start.
#
# Every test already starts with a reboot (a fresh browser context and the base URL),
# so the next test never inherits where the last one landed. On top of that, an
# action classified new_screen is followed straight away by one more reboot, and the
# start page it lands on is recorded. That way a control you can't get back from
# shows up in the result (recovered_ok false) as a finding, and a stray navigation
# never compounds. The start page is compared with the entry signature the baseline
# recorded when the run began, and is retaken up to twice if it doesn't match yet.
#
# Code: engine/adapters/web_gui/session.py (Session.act, Session.recover, Session.baseline),
# engine/adapters/web_gui/adapter.py (outcome_for, describe_result_for_log, render_test_entry)

Feature: The browser recovers after reaching a new screen
  As someone who needs independent tests
  I want a reboot after a new_screen result, recording whether the app got back to its start
  So that a control you can't get back from is noticed and doesn't break later tests

  Scenario Outline: Only a new_screen result triggers the recovery
    Given a sent action classified as "<screen_was>"
    When the result is worked out
    Then "recovered_to" is <present>

    Examples:
      | screen_was   | present                           |
      | new_screen   | the signature after the reboot    |
      | known_screen | not in the result                 |
      | same_screen  | not in the result                 |

  Scenario Outline: recovered_ok says whether the reboot landed on the start state
    Given a sent action classified as "new_screen"
    And the entry signature recorded at the baseline is "sig-start"
    When the reboot after it reads "<recovered_to>"
    Then "recovered_ok" is <ok>
    And the log line ends with "<log>"
    And the report shows "recovered" with the badge "<badge>"

    Examples:
      | recovered_to | ok    | log                 | badge     |
      | sig-start    | true  | recovered ok        | to start  |
      | sig-other    | false | recovered ELSEWHERE | elsewhere |

  Scenario: The outcome records the reset
    Given a result with "recovered_to" and "recovered_ok" true
    When outcome_for reads it
    Then reset_attempted is true and reset_ok is true

  Scenario: Without a recovery the outcome says no reset was tried
    Given a result with no "recovered_to"
    When outcome_for reads it
    Then reset_attempted is false and reset_ok is None
