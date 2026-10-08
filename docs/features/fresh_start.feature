# A web_gui test can start with no saved session, and the model reads each step's
# requests (#381).
#
# Two things the Skeptic kept asking for that no test could give (#379, runs/exp379):
# "clear all cookies and storage, load the page fresh" (7 of 114 blocking questions in 17
# runs), and "how many requests did the double click send". The request log (#326) was
# recorded per step but left out of what the model reads, to keep prompts short.
#
# Code: trailhound/adapters/web_gui/session.py (START_AS, _open_fresh_page),
# trailhound/adapters/web_gui/adapter.py (redact_history_for_model, _requests_by_step,
# _START_LABEL, API_SCHEMA_DOC, TEST_CAPABILITIES, validate_casting_response).
# Tests: trailhound/tests/test_fresh_start_and_requests.py

Feature: A test can start fresh, and each step shows its requests
  As a Driver answering what a first-time visitor sees, or how many requests an action sent
  I want a start with no saved session, and each step's requests in my history
  So that those questions can be settled by a test instead of staying open

  Scenario: A fresh start has no saved session
    Given the run has a saved session
    When a test has start_as "fresh"
    Then its browser context gets no saved cookies or storage, and no saved sessionStorage
    And its result has "started_as": "fresh", its label ends "(fresh, no saved session)", and its action counts apart from the same test as the saved tab
    And a step that needs a login has to log in, as a first-time visitor would
    But a run without a saved session refuses "fresh" when the tests are cast, as it does "new_tab"

  Scenario: A fresh start checked live
    # On the local Juice Shop, no model calls.
    When "goto /profile" runs as the saved tab, then fresh
    Then the saved tab's step shows "GET /profile -> 200" and the fresh one "GET /profile -> 500", since a first-time visitor isn't logged in

  Scenario: Each step's requests in the history the model reads
    Then each step in the history gets "requests": its own-site requests, as "POST /profile -> 302"
    And a request with no answer yet reads "-> no answer yet"
    And at most 8 per step, then "and N more"; static files that loaded fine aren't in the log
    And the full "request_log" stays in output.json and the report, not in the history
    And on the local Juice Shop a double-clicked save shows "POST /profile -> 302" and "GET /profile -> 200" on each click's step

  Scenario: The Skeptic is told
    Then what_a_test_can_do (#379) says a test can start fresh, and lists the requests each step sent among what a result shows
