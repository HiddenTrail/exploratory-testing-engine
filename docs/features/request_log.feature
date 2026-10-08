# Signals per step, a request log, and what the server said (#326).
#
# The harness read the console and the network during every test, but it compared only
# the page before the first step with the page after the last, and kept only failures.
# Since #310 a test has up to 6 steps, so an error couldn't be tied to the step that
# caused it, and nobody could read why a request failed. Juice Shop's basket 400, reported
# as a bug in several runs, is the server saying "You can order only up to 5 items of this
# product." Now each step says what it set off, and a failed request on the product's own
# site comes with what the server said. Request bodies, cookies and headers are never
# recorded: they hold passwords and tokens. A review found paths with an email or a token
# in them, and error bodies holding SQL and stack traces, so both are redacted and the
# message is taken by an allowlist.
#
# Code: trailhound/adapters/web_gui/session.py (step_signals, request_log, server_message,
# log_path, _safe_path, _failed_line, _error_signals, _on_response, _on_request_finished,
# _read_messages, _act), trailhound/adapters/web_gui/adapter.py (redact_history_for_model,
# _request_log_html, _step_signals_html, API_SCHEMA_DOC). Tests: trailhound/tests/test_request_log.py

Feature: Each step says what it set off, and the run keeps a request log
  As a Driver deciding what an error means
  I want each error tied to the step that caused it, with what the server said
  So that I can tell a real failure from the product refusing on purpose

  Scenario: Each step carries what it set off
    Given a test with several steps
    Then each step's record has the console errors and failed requests that started during it, as "signals" and "signals_weak"
    And a step's errors are trusted only if the test's would be, the step was done, and the page had rested before and after it
    And a test with one step leaves them out, since they would repeat the test's own "signals"
    And a long list is cut at 5 with a "_more" count
    And the test's own "signals" are worked out as before

  Scenario: What the server said, and slow requests, on a trusted step
    Given a trusted step whose request to the product's own site failed and wasn't seen while the page sat idle
    Then the step has "server_said", like "PUT /api/BasketItems/35 -> 400: You can order only up to 5 items of this product."
    And a trusted step's own-site request of 2 s or more is in "slow", like "GET /rest/slow took 3.2 s"
    But an untrusted step has neither

  Scenario: What the server said is taken by an allowlist and redacted
    Then from a JSON body only the text under "error", "message", "detail" or "title" is kept, so an echoed query or a stack trace isn't
    And from an HTML body only its title, from plain text its first line, and from anything else nothing
    And it is read right after the step, only once the response finished, only for a text type and a body under 200000 bytes
    And it is one line, at most 200 characters, with emails, generated ids, tokens and numbers of 6 or more digits taken out

  Scenario: The request log
    Then a test with requests has "request_log": "own_site", each request with its step, method, path, status, milliseconds and the server's message when it failed, at most 40, with "own_site_more" past that
    And static files that loaded fine (scripts, styles, images, fonts) are counted in "static_files", and other sites' requests in "third_party"
    And a path is redacted (emails, ids, tokens, ";jsessionid=..." out) and keeps its query's names, hiding their values: "/rest/products/search?q=<v>", "/api/Users/<email>"
    And failed requests in "signals" use the same redacted path
    And no request body, cookie or header is ever recorded

  Scenario: The Driver gets the short form, the report the whole log
    Then the history the model reads keeps each step's signals, "server_said" and "slow", but not "request_log"
    And each step gets its own-site requests from the log as "requests", like "POST /profile -> 302", at most 8 then "and N more" (#381, fresh_start.feature)
    And the report's test entry has a folded "Requests" table, and its step lines say what each step set off

  Scenario: Console warnings are hints
    Then a console "warning" goes to "signals_weak" as "console_warnings", never to "signals"
