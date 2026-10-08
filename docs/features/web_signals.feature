# web_gui signals: what each action did beyond the screen it landed on.
#
# A failed request, a console error or a changed cookie can matter even when the
# screen looks the same. So each act compares the page before and after the click
# and lists what changed (#143): console errors, failed requests, storage and cookie
# keys added, removed or changed, and controls added or removed. Storage and cookie
# values may be tokens or personal data, so only key names are kept. Values are
# compared by a short hash and never reach the Driver or a report. Each list is cut
# at 5 items, and a "<key>_more" count says how many were left out, so a cut list
# doesn't look complete. Which of these count as trusted is in web_signal_trust.feature.
# Each step also says what it set off, and a request log is kept: request_log.feature (#326).
# Each step also says what the page told the user: page_says.feature (#351).
#
# Code: trailhound/adapters/web_gui/session.py (_signal_diff, _STORAGE_JS, Session._storage,
# _request_key, _MAX_SIGNAL_ITEMS)

Feature: Each action records what changed around it
  As someone looking for hidden failures
  I want each action to record console errors, failed requests, storage and cookie keys changed, and controls added or removed
  So that problems that don't change the screen are still caught, without leaking any value

  Scenario Outline: Each kind of change is listed under its own key
    # The same keys are used in "signals" and "signals_weak"; which tier an item goes
    # to is the trust check's job.
    Given an action after which <change>
    When its signals are worked out
    Then the signal "<key>" lists <item>

    Examples:
      | change                                                 | key              | item                             |
      | the console logged an "error" or a "pageerror"         | console_errors   | the message                      |
      | a request started after the click answered 500         | failed_requests  | "POST http://x/api/b -> 500"     |
      | a request got no response at all                       | failed_requests  | it with status 0 or its failure  |
      | the cookie "c" appeared                                | storage_added    | "cookie:c"                       |
      | the localStorage key "token" went away                 | storage_removed  | "local:token"                    |
      | the sessionStorage key "b" got a new value             | storage_changed  | "session:b"                      |
      | a "Menu" button appeared                               | controls_added   | "button:menu"                    |
      | a "Close" button went away                             | controls_removed | "button:close"                   |

  Scenario: Requests that didn't fail, or haven't finished, are not signals
    Given an action after which one request answered 200 and one is still pending
    When its signals are worked out
    Then neither request is listed

  Scenario: A request is named without its query or fragment
    Given a request to "http://x/api/poll?t=99#secret" answered 503
    When its signals are worked out
    Then it is listed as "GET http://x/api/poll -> 503"

  Scenario: Storage and cookies are compared by hash and reported by name only
    Given the cookie "token" had one value before the click and another after
    When its signals are worked out
    Then "storage_changed" lists "cookie:token"
    And neither value appears in the result, the Driver's evidence or the report

  Scenario: A repeated item counts once
    Given the same broken request was made twice after the click
    When its signals are worked out
    Then it is listed once

  Scenario: A long list is cut at 5 and says how many more there were
    Given 8 console errors after the click
    When its signals are worked out
    Then "console_errors" lists the first 5
    And "console_errors_more" is 3
    And the report shows "and 3 more" next to the list

  Scenario: A quiet action has only the settled flags
    Given an action after which nothing changed
    When its signals are worked out
    Then "signals" is just "settled_before" and "settled_after"
    And there is no "signals_weak"
