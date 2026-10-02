# web_gui report and log: what each click did, at a glance.
#
# The web_gui adapter renders its own test entries and onboarding section in the
# HTML report, and its own lines in the console log. Each test shows the pair it
# acted on, the predicted and actual screen class as badges, whether the prediction
# matched, whether the path drifted, and whether recovery got back to the start. The
# signals sit in a folded section, with the trusted ones and the weak ones apart, so
# a reader sees the same split the Driver is told about (#143). A list cut at 5
# shows how many more there were, or the report looks complete when it isn't
# (Copilot on #152).
#
# Code: engine/adapters/web_gui/adapter.py (render_test_entry, _screen_badge,
# _signals_html, render_onboarding_section, describe_test_for_log, describe_result_for_log)

Feature: The web report and log show each move and its signals
  As someone reading a web run
  I want each test shown with badges for the screen class, prediction, path drift and recovery, and its signals folded away
  So that I can see what each click did at a glance

  Scenario Outline: Each screen class has its own badge
    Given a test whose screen class is "<screen_was>"
    When the report renders it
    Then the screen badge reads "<label>" in the "<kind>" style

    Examples:
      | screen_was   | label       | kind    |
      | new_screen   | new state   | warn    |
      | known_screen | known state | good    |
      | same_screen  | no change   | neutral |

  Scenario: A sent test shows its prediction, outcome and timings
    Given a sent test that reached its state
    When the report renders it
    Then it shows "Test #3", the pair "st01 :: button:A", and the hypothesis or "Probe"
    And the predicted outcome with the predicted screen badge
    And "reached" with the actual screen badge and "prediction" with "matched" or "missed"
    And "click took Xs, settled in Ys"
    And ", clicked through dialog 'cookieconsent' on top of it" when that is the "covered_by"

  Scenario Outline: Drift, recovery, a skip and a failed click get their own badges
    Given <case>
    When the report renders it
    Then it shows <shown>

    Examples:
      | case                                       | shown                                      |
      | a test whose replay didn't reach its state | the badge "path drifted"                   |
      | a test that recovered to the start         | "recovered" with the badge "to start"      |
      | a test that recovered somewhere else       | "recovered" with the badge "elsewhere"     |
      | a skipped test                             | the badge "skipped" and its skip_reason    |
      | a test whose control wasn't actuated       | the badge "control could not be actuated"  |

  Scenario: Signals are folded, trusted and weak apart
    Given a test with trusted and weak signals
    When the report renders it
    Then a folded "Signals" section holds "Signals (trusted)" and "Weak signals" marked "hints only, not evidence"
    And each list shows "and N more" when it was cut
    And a read from an unsettled page gets the badge "read from an unsettled page"
    And a test with only the settled flags, both true, has no signals section

  Scenario: A failed click's weak signals are still in the report
    Given a test with verdict "not_actuated" and the weak console error "boom"
    When the report renders it
    Then "boom" is in its entry

  Scenario: The onboarding section shows what the Driver was told
    When the report renders the onboarding section
    Then it shows "What the Driver was told", "Carried map (the action space)", "Where the run started" (the last two when check_ready filled them) and "Happy-day example"
    And the ranked oracle ideas when the evidence has them

  Scenario Outline: The log has one line for the test and one for its result
    Given <case>
    When the loop logs it
    Then the line reads like "<line>"

    Examples:
      | case                                     | line                                                                                       |
      | a test cast on "st01 :: button:A"        | st01 :: button:A -> predicting known_screen                                                |
      | a sent test                              | known_screen (click 1.2s, settled 0.4s)                                                    |
      | a test clicked through a cover           | ..., clicked through dialog 'cookieconsent' on top of it                                   |
      | a test with errors and an unsettled read | ..., 2 console error(s), 1 failed request(s), storage changed, UNSETTLED, 1 weak signal(s) |
      | a test whose path drifted                | [path drifted before the control] ...                                                      |
      | a test that recovered                    | ..., recovered ok (or recovered ELSEWHERE)                                                 |
      | a test whose control wasn't actuated     | NOT ACTUATED - the control could not be clicked                                            |
      | a skipped test                           | SKIPPED - the skip reason                                                                  |
