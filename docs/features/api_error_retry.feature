# Transient API errors are retried with backoff; permanent ones are raised at once.
#
# The Anthropic SDK already retries some errors on its own before it raises, so an
# error that reaches the engine has used up that budget too. A checkpoint call is
# expensive to restart, so the engine tries again with backoff, sharing the same
# attempt budget as validation retries. There is nothing to correct, so nothing is
# sent back to the model.
#
# A 529 OverloadedError has to be named on its own. It is not a subclass of
# InternalServerError, and the SDK checks for 529 before its ">= 500" branch, so a
# 529 used to propagate on the first attempt with no backoff at all, and it is the
# most common transient error there is. A bad key or a malformed request is
# permanent, and retrying it only burns time.
#
# Code: engine/client.py (_RETRYABLE_API_ERRORS, call_tool_with_retry)

Feature: Transient API errors are retried with backoff, permanent ones fail at once
  As someone running a session
  I want a busy or flaky API to be retried, and a bad key to fail straight away
  So that a short outage doesn't end a run, and a broken setup doesn't waste time

  Scenario Outline: A transient error is retried and the next attempt can succeed
    Given the first call raises <error>
    And the second call returns a valid answer
    When the engine calls the model
    Then the answer is returned
    And the log shows "attempt 1 hit transient API error (<error>): ... - retrying"

    Examples:
      | error               |
      | APIConnectionError  |
      | APITimeoutError     |
      | RateLimitError      |
      | InternalServerError |
      | OverloadedError     |

  Scenario: Backoff doubles each attempt and is capped at 30 seconds
    Given every call raises RateLimitError
    When the engine calls the model with 3 attempts
    Then it waits 1 second after attempt 1 and 2 seconds after attempt 2
    And it does not wait after the last attempt
    And the log shows "attempt 3 hit transient API error (RateLimitError): ... - giving up"
    And a RuntimeError is raised starting with "Gave up after 3 attempts"

  Scenario Outline: A permanent error is raised on the first attempt without retrying
    Given the first call raises <error>
    When the engine calls the model
    Then <error> is raised to the caller
    And the model was called once
    And the engine did not wait

    Examples:
      | error                 |
      | AuthenticationError   |
      | PermissionDeniedError |
      | BadRequestError       |
      | NotFoundError         |

  Scenario: A permanent error during a run ends it with the saved checkpoints kept
    Given a run whose checkpoint 2 hypothesis call raises AuthenticationError
    When the run handles the error
    Then output.json has stopped_reason "error" and the error text under "error"
    And checkpoint 1 is still in output.json
