# Signals per step, a request log, and what the server said (#326).
#
# The harness read the console and the network during every test, but it compared only
# the page before the first step with the page after the last, and kept only failures.
# Since #310 a test has up to 6 steps, so an error couldn't be tied to the step that
# caused it, and nobody could read why a request failed. Juice Shop's basket 400, reported
# as a bug in several runs, is the server saying "You can order only up to 5 items of this
# product." Now each step says what it set off, and a failed request on the product's own
# site comes with the start of the server's answer. Request bodies, cookies and headers
# are never read: they hold passwords and tokens.
#
# Code: trailhound/adapters/web_gui/session.py (step_signals, request_log, server_message,
# log_path, _error_signals, _on_response, _on_request_finished, _read_messages, _act),
# trailhound/adapters/web_gui/adapter.py (redact_history_for_model, _request_log_html,
# _step_signals_html, API_SCHEMA_DOC). Tests: trailhound/tests/test_request_log.py

Feature: Each step says what it set off, and the run keeps a request log
  As a Driver deciding what an error means
  I want each error tied to the step that caused it, with what the server said
  So that I can tell a real failure from the product refusing on purpose

  Scenario: Each step carries what it set off
    Given a test with several steps
    Then each step's record has the console errors and failed requests that started during it, as "signals" and "signals_weak", with the same trust checks as the test
    And "server_said" for a failed request on the product's own site, like 'PUT http://127.0.0.1:3000/api/BasketItems/35 -> 400: {"error":"You can order only up to 5 items of this product."}'
    And "slow" for a request of 2 s or more, like "GET /rest/slow took 3.2 s"
    And a quiet step adds nothing, and the test's own "signals" stay the union, as before

  Scenario: What the server said is redacted
    Then it is the start of the response body, one line, at most 200 characters
    And emails, generated ids and tokens (a JWT, or 32 or more key-like characters) are taken out
    And it is read after the step, and only for a failed request on the product's own site

  Scenario: The request log
    Then a test's result has "request_log": "own_site", each request with its step, method, path, status, milliseconds and the server's message when it failed, and "third_party", a count
    And a path keeps its query's names and hides their values: "/rest/products/search?q=<v>"
    And no request body, cookie or header is ever recorded

  Scenario: The Driver gets the short form, the report the whole log
    Then the history the model reads keeps each step's signals, "server_said" and "slow", but not "request_log"
    And the report's test entry has a folded "Requests" table, and its step lines say what each step set off

  Scenario: Console warnings are hints
    Then a console "warning" goes to "signals_weak" as "console_warnings", never to "signals"
