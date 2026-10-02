# web_gui settling: every read waits for a page that has rested.
#
# Three harness bugs in a row (#123, #130, #131) were reads taken before the page had
# rested. So before the page is read, the session waits until the DOM has not changed
# for 0.4 s and no request is in flight, polling every 100 ms, for at most 8 s
# (after Spoor's settling, #143). A page that doesn't rest in time is read anyway and
# flagged, rather than hanging the run or being trusted. DOM changes are counted by a
# MutationObserver added to every document the page loads. Websockets don't count as
# requests in flight, because Juice Shop keeps one open. An urgent live-region toast
# isn't waited out either: identity already leaves those controls out (#124), and
# Juice Shop's stays up for about 5 s on every load.
#
# Code: engine/adapters/web_gui/session.py (_rest, _REST_QUIET_MS, _REST_MAX_MS,
# _MUTATION_COUNTER_JS, Session.act)

Feature: Reads wait for a settled page
  As someone who doesn't want noisy results
  I want every read to wait for a quiet DOM and no request in flight, for at most 8 s, and to flag it otherwise
  So that a page still loading isn't mistaken for a different page

  Scenario: A page that stops changing rests
    Given the DOM mutation count changes, then stays the same
    And no request is in flight
    When the session waits for the page to rest
    Then it returns true once the count has held for 0.4 s

  Scenario: A page that never stops changing is flagged, not waited on forever
    Given the DOM mutation count changes on every poll
    When the session waits for the page to rest
    Then it returns false after 8 s

  Scenario: A request in flight keeps the page busy
    Given the DOM is quiet
    But a request has started and not finished or failed
    When the session waits for the page to rest
    Then it returns false after 8 s

  Scenario: An open websocket doesn't keep the page busy
    # Only page requests are tracked as in flight, and a websocket isn't one of them.
    Given the page keeps a websocket open, as Juice Shop does
    And the DOM is quiet
    When the session waits for the page to rest
    Then it returns true once the DOM has been quiet for 0.4 s

  Scenario: The two settled flags come from the rests around the click
    When a test runs
    Then "settled_before" is the result of the rest after the last replay step, or after the reboot when the path is empty
    And "settled_after" is the result of the rest right after the control was actuated
    And both flags are always in the result's "signals", even when nothing else changed

  Scenario: The click and the settle are timed apart
    # The click ladder's fallbacks can take seconds on their own. Counting them as
    # the page's settle time made the harness's retries look like a slow app (#122).
    When a test runs
    Then "click" is the seconds the actuation itself took, rounded to 2 places
    And "settle" is the seconds from the end of the click until the page rested or 8 s ran out

  Scenario: A read from an unsettled page is never trusted
    Given "settled_after" is false
    When the action's signals are worked out
    Then every signal except the two settled flags is in "signals_weak"
