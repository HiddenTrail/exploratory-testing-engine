# Test coverage for the Skeptic: what the tests actually sent, worked out from the log.
#
# The Skeptic never sees test data, so it used to guess coverage from the Driver's
# prose, and it guessed wrong. In a complex_sut run it listed "malformed/missing
# client_id" and "priority=high" as untouched after tests had sent an empty
# client_id and priority high (#65). Now the engine gives it the facts: for each
# input field in the adapter's casting schema, the values tried so far, and for a
# field with fixed choices (an enum or a boolean), the ones never tried.
#
# It reads the adapter's own casting schema, so no adapter code is needed. It sums
# up inputs only, never results, so the Skeptic stays cold.
#
# Code: trailhound/coverage.py, trailhound/loop.py (get_skeptic_review)

Feature: The Skeptic gets the values each input field has been sent
  As someone who wants a fair review
  I want the engine to work out from the log which values each input field was sent
  So that the Skeptic judges coverage from facts, not from the Driver's description

  Scenario: Only fields sent to the SUT are summarised
    # linked_hypothesis, oracle_claim_id and every predicted_* field are the
    # Driver's bookkeeping, not inputs.
    Given the "complex_sut" casting schema
    When the engine summarises the tests that ran
    Then the summary has rows for "client_id", "payload", "priority", "request_count" and "concurrent"
    And there is no row for "linked_hypothesis", "oracle_claim_id" or any field starting with "predicted_"
    And "tests_run" is the number of tests that ran

  Scenario: Values tried are listed once each, numbers in order
    Given the "complex_sut" casting schema
    And tests that sent "request_count" 20, 10 and 1, and "client_id" "race-test-1" and ""
    When the engine summarises the tests that ran
    Then "request_count" has "values_tried" [1, 10, 20]
    And "client_id" has "" among its "values_tried"

  Scenario Outline: A field with fixed choices lists the ones never tried
    Given the "complex_sut" casting schema
    And every test sent "<field>" as <sent>
    When the engine summarises the tests that ran
    Then "<field>" has "never_tried" <never>

    Examples:
      | field      | sent     | never    |
      | priority   | "normal" | ["high"] |
      | concurrent | false    | [true]   |

  Scenario: A long list of values is capped at 10
    Given the "complex_sut" casting schema
    And 15 tests that sent "request_count" 0 to 14
    When the engine summarises the tests that ran
    Then "request_count" shows 10 values in "values_tried" and "more_values" 5

  Scenario: A long value is cut short, and free text has no never_tried list
    Given the "token_purchase" casting schema
    And a test that sent an "auth_token" of 50 characters
    When the engine summarises the tests that ran
    Then that "auth_token" is shown as its first 30 characters followed by "..."
    And the "cvv" row has no "never_tried"

  Scenario: The Skeptic gets the summary, and the checkpoint keeps it
    Given checkpoint 2 has run, with some tests skipped
    When the engine asks the Skeptic for its review
    Then the Skeptic's evidence has "test_coverage" built from every non-skipped test of checkpoints 1 and 2
    And checkpoint 2's record stores the same "test_coverage"
    And the report shows it as a "Field / Values tried / Never tried" table in the checkpoint's details
