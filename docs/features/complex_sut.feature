# complex_sut: a rate-limited submission API with a planted race condition.
#
# A reference SUT with a known, real bug. POST /submit allows 5 requests per
# client_id per 600-second window, but the quota check and the quota write have a
# 50 ms sleep between them and no lock. FastAPI runs sync handlers in a thread pool
# and the sleep releases the GIL, so concurrent requests for one client_id really do
# interleave and more than 5 get accepted. Sequential requests always respect the
# limit. The window is 600 seconds because at 10 seconds it expired mid-run, which
# looked like a counter that didn't count. Unlike token_purchase, one test can be a
# burst of requests whose responses are added up into one result.
#
# Start it with: uvicorn engine.adapters.complex_sut.sut:app --port 8000
#
# Code: engine/adapters/complex_sut/sut.py, engine/adapters/complex_sut/adapter.py

Feature: A rate-limited API with a planted race to test against
  As someone developing the engine
  I want a mock API whose per-client quota a concurrent burst can overrun, and an adapter that sends bursts
  So that the engine can be checked against a known, real concurrency bug

  Background:
    Given the complex_sut mock SUT is running
    And a fresh client_id

  Scenario: Sequential requests never get past the limit
    When I send 8 requests for the client_id one after another
    Then the first 5 come back with status "accepted" and "used" 1 to 5
    And the other 3 come back with status "rate_limited", "used" 5 and "limit" 5

  Scenario: A concurrent burst gets more accepted than the limit
    When I send 20 requests for the client_id at the same moment
    Then more than 5 of them come back "accepted"

  Scenario: A test can be one request, a sequential run or a concurrent burst
    Given a cast test with "request_count" 6
    When "concurrent" is true
    Then the adapter fires all 6 requests at once, one thread each
    But when "concurrent" is false it sends them one at a time, each after the last response
    And the result keeps every response, "accepted_count" and the "limit" read from the responses

  Scenario Outline: The burst is judged by how many were accepted against the limit
    Given a burst whose responses <responses>
    When the adapter adds them up
    Then actual_correctness is "<correctness>"
    And prediction_matched is true only if the test predicted "<correctness>"

    Examples:
      | responses                                          | correctness |
      | accepted 7 with "limit" 5                          | overcounted |
      | accepted 5 with "limit" 5                          | correct     |
      | accepted 1 with "limit" 5                          | correct     |
      | all lack the "limit" field                         | unknown     |

  Scenario: A burst over the cap is refused before anything is sent
    # A burst that large would tie up resources and give an unreadable result, for no
    # more information.
    Given a cast test with "request_count" 25
    When the adapter runs it
    Then no request is sent
    And the result is marked skipped with a skip_reason naming the ceiling of 20 requests
    And prediction_matched is false
    And the outcome is not accepted and its effect is "unknown"

  Scenario: The outcome describes the burst shape and the quota state
    Given a concurrent burst of 6 whose first response was accepted and whose last was rate limited
    When the outcome is built
    Then its action_id is "POST /submit x6 concurrent"
    And it is accepted, with effect "transition"
    And state_before is "quota_has_headroom" and state_after is "quota_at_limit"
    # The tokens are not keyed by client_id: two fresh client_ids are the same state.

  Scenario: The adapter's defaults fit burst testing
    When a complex_sut run starts with no budget flags
    Then it runs up to 4 checkpoints with 10 tests in the first round and 6 after
    And a cast test predicts "correct" or "overcounted" and sets "client_id", "payload", "priority", "request_count" and "concurrent"
