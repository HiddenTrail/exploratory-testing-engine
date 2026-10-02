# Readiness and the happy-day example: two checks before any model call.
#
# Before it spends anything, a run asks whether the SUT is there, then makes one
# real, ordinary call to it. That call is the first thing the Driver reads, so it
# is fetched live rather than written into the adapter, where it could go stale
# without anyone noticing.
#
# Both used to be written inline in runner.py and loop.py, which meant a run could
# only begin against a web service. Now they are the defaults behind two adapter
# hooks, check_sut_ready and fetch_happy_day_example. An HTTP adapter gets them
# for free; a SUT with no URL (a browser, a game client) supplies both.
#
# Code: engine/runner.py (run), engine/http.py, engine/loop.py (get_happy_day_example)

Feature: The engine checks the SUT is up and fetches one real example before spending anything
  As someone paying for runs
  I want a forgotten server to stop the run before the first model call
  So that a run never pays to find out the SUT isn't there

  Scenario: The readiness probe runs before any model call
    When a run starts
    Then the adapter is validated, then the client is built, then the SUT's readiness is checked
    And only after that is the happy-day example fetched and the first casting round asked for
    # Building the client makes no network call.

  Scenario: The HTTP probe treats only a transport error as "down"
    # Plenty of real services have no /docs. A 404 or 500 is a SUT that answered.
    Given an HTTP adapter "complex_sut" with base_url "http://127.0.0.1:8000" and docs_path "/docs"
    When the docs page answers with status 404
    Then the run goes on
    When instead nothing is listening on port 8000
    Then the run exits with "complex_sut's SUT isn't running at http://127.0.0.1:8000 - start it first."

  Scenario: The HTTP probe waits up to sut_ready_timeout
    Given an HTTP adapter with the default sut_ready_timeout of 5.0 seconds
    When the engine checks readiness
    Then it sends GET to base_url plus docs_path with a timeout of 5.0 seconds

  Scenario: The HTTP happy-day example is one live POST
    Given the "token_purchase" adapter, with test_endpoint_path "/purchase" and a happy_day_request
    When the engine fetches the happy-day example
    Then it POSTs the happy_day_request as JSON to base_url plus "/purchase"
    And the example is {"request": {"method": "POST", "path": "/purchase", "body": ...}, "response": {"status": ..., "body": ...}}
    And a response that isn't JSON comes back as body {"error": "non-JSON response from SUT", "raw_text": ...}

  Scenario: An adapter without HTTP uses its own two hooks
    Given an adapter with no base_url that supplies check_sut_ready and fetch_happy_day_example
    When a run starts
    Then the engine calls the adapter's hooks and never touches httpx
    And the happy-day example is whatever the adapter's fetch returned

  Scenario: A readiness hook that refuses stops the run before anything is cast
    # The hook raises SystemExit with a message, it doesn't return a flag.
    Given an adapter whose check_sut_ready raises SystemExit "the emulator isn't running - start it first."
    When a run starts
    Then the run exits with that message
    And no casting round is asked for
    And the run is not turned into a stopped_reason or a report

  Scenario: The happy-day example is shown on the console and to the Driver
    When the engine has fetched the happy-day example
    Then the console shows "Fetching the one happy-day example from the live SUT..."
    And a line with the request and the response, showing each half's "body" if it has one and the whole half if not
    And the example is stored in output.json under "happy_day_example"
    And it is part of the static evidence every casting and hypothesis call starts with
