# The outcome envelope: a small typed record an adapter puts on each test result.
#
# Adapters used to report everything as prose. "recovered to unknown-5, NOT the
# main screen" is an accurate reset failure that no generic code can read, and a
# live run went on for two more checkpoints after it had lost its baseline because
# the only thing that knew was a sentence in a string field.
#
# So an adapter fills a few typed fields under the reserved key "outcome", and
# engine/diagnostics.py only compares and counts them. Three rules keep it honest:
# "unknown" is never counted as "none", an empty state token means "not observed",
# and "accepted" may be null when the adapter can't tell.
#
# Code: engine/outcome.py

Feature: Adapters describe each test result in a typed outcome envelope
  As someone maintaining the engine
  I want each result to carry typed fields for effect, acceptance, state, reset, latency and prior match
  So that generic code can count and compare results without parsing an adapter's prose

  Scenario: An empty Outcome commits to nothing
    When an adapter builds an Outcome without setting any field
    Then "effect" is "unknown"
    And "action_id", "state_before", "state_after" and "start_intended" are ""
    And "accepted", "reset_ok", "latency" and "matched_prior" are null
    And "reset_attempted" is false
    And "problems" is an empty list (#312: the trusted problems a test recorded, as tokens the engine only compares)

  Scenario: An envelope is attached to and read back from a result under the key "outcome"
    Given a result dict from execute_test
    When the adapter calls attach with an Outcome
    Then the result has the Outcome's fields as a dict under the key "outcome"
    And read on that result returns the same dict
    And read on a result with no "outcome" dict returns nothing

  Scenario: rows drops log entries without an envelope instead of filling in defaults
    # Dropping, not defaulting, is what lets diagnostics tell "no adapter support"
    # apart from "nothing detected".
    Given a casting log where test 1 has an envelope and test 2 has none
    When the engine collects the envelope rows
    Then there is one row
    And that row carries "test_number" 1 and its "checkpoint" next to the envelope fields

  Scenario Outline: validate_outcome reports what is wrong with an envelope
    Given an envelope where <problem>
    When an adapter's own test calls validate_outcome on it
    Then the errors include "<error>"

    Examples:
      | problem                                   | error                                                      |
      | "effect" is "changed"                     | 'effect' must be one of none, variant, transition, unknown |
      | "state_before" is the number 3            | 'state_before' must be a string ('' where unobserved)      |
      | "accepted" is the string "yes"            | 'accepted' must be true, false, or null                    |
      | "reset_attempted" is null                 | 'reset_attempted' must be a boolean                        |
      | "latency" is the string "fast"            | 'latency' must be a number or null                         |
      | "reset_ok" is true but no reset was tried | 'reset_ok' is set but 'reset_attempted' is false           |

  Scenario: The loop never calls validate_outcome
    # A malformed envelope should fail the adapter's test suite, not a live run
    # halfway through. Every detector skips rows with missing keys anyway.
    Given an adapter whose envelopes would fail validate_outcome
    When a run executes its tests
    Then the run is not stopped because of the envelopes
