# Casting: the Driver proposes a batch of real tests each checkpoint.
#
# Each SUT has its own test shape, so the casting tool schema, prompt and per-test
# checks live in the adapter. Three things are the same for every adapter and live
# in trailhound/tools.py so they can't drift apart (issue #96): what the Driver is told
# about the previous checkpoint's feedback (PRIOR_FEEDBACK_GUIDE), the 60-word
# limit on the round's reasoning, and the checks on the answer's envelope
# (give_up, reasoning, candidate_tests). A missing give_up used to be the most
# common casting retry after #41 (4 of 12 calls), so it may now be left out when
# the answer has tests.
#
# Code: trailhound/loop.py (get_casting_round, run_checkpoint_loop),
# trailhound/tools.py (casting_envelope_errors), each adapter's validate_casting_response

Feature: The Driver casts a batch of tests in the adapter's own schema
  As someone exploring a live system
  I want the Driver to propose a batch of tests that the adapter runs for real, each with a prediction
  So that claims rest on what the system actually did, and surprises stand out test by test

  Scenario: The casting call uses the adapter's schema, prompt and validator
    Given an adapter with its own casting tool schema and validate_casting_response
    When the loop asks the Driver for a casting round
    Then the model is called with the tool "submit_casting_round" in the adapter's schema
    And the system prompt comes from the adapter's casting_system_prompt for this budget and round
    And an answer that fails the adapter's validator is sent back with its errors and asked for again

  Scenario: Every cast test runs against the SUT and is logged with its prediction result
    # The prediction field itself is part of each adapter's schema. For complex_sut a
    # test without "predicted_outcome" or "predicted_correctness" is rejected.
    Given the Driver cast 3 tests with predictions
    When the loop runs them
    Then each test gets the next number from the run's test counter and goes to the adapter's execute_test
    And each casting log entry holds "checkpoint", "round_reasoning", "linked_hypothesis", "oracle_claim_id" and the result
    And the console line for each test ends in "prediction matched" or "prediction MISSED"

  Scenario Outline: A test is labelled by what it was cast for
    Given a cast test with linked_hypothesis "<linked_hypothesis>"
    When it is printed to the run log
    Then its label is "<label>"

    Examples:
      | linked_hypothesis                    | label                                        |
      | the limit is counted per client      | hypothesis: the limit is counted per client  |
      |                                      | edge case                                    |

  Scenario: The Driver can give up on a round
    Given the Driver answers with "give_up" true and an empty "candidate_tests"
    When the loop handles the casting round
    Then no test runs this checkpoint
    And the log says "Claude gave up casting:" followed by its reasoning
    And the Driver still forms a hypothesis and the Skeptic still reviews it

  Scenario: A skipped test is logged as not run and left out of coverage
    # A skipped test never ran, so there's no prediction to check, and not every
    # adapter sets prediction_matched on a skip.
    Given the adapter returns a result with "skipped" true for a test
    When the loop logs that result
    Then the console line ends in "not run" with no prediction verdict
    And the test still goes into the casting log
    And it is not counted in the checkpoint's "test_coverage"

  Scenario Outline: Every adapter's casting validator starts with the shared envelope checks
    Given a casting answer with <answer>
    When casting_envelope_errors checks it
    Then the result is <result>

    Examples:
      | answer                                                    | result                                                                |
      | tests, a reasoning and no "give_up" field                 | accepted                                                              |
      | no tests and no "give_up" field                           | rejected: "give_up" can only be left out when there are tests         |
      | an empty "candidate_tests" and "give_up" false            | rejected: "candidate_tests" must be non-empty unless give_up is true  |
      | an empty "candidate_tests" and "give_up" true             | accepted                                                              |
      | no "candidate_tests" field                                | rejected: missing required field "candidate_tests"                    |
      | tests and "give_up" set to the string "no"                | rejected: "give_up" must be a boolean                                 |
      | tests and no "reasoning" field                            | rejected: missing required field "reasoning"                          |
      | tests and a reasoning of 100 words                        | accepted                                                              |
      | tests and a reasoning of 121 words                        | rejected: "reasoning" is far too long, limit 60                       |

  Scenario: The round's reasoning is asked for in 60 words, naming the ids it targets
    Given an adapter's casting schema uses CASTING_REASONING_DESCRIPTION for "reasoning"
    Then the field description says "at most 60 words"
    And it asks the Driver to name the observation and gap ids the round targets

  Scenario: Later rounds tell the Driver how to read the prior feedback
    # Every adapter's casting prompt uses the same PRIOR_FEEDBACK_GUIDE text, so the
    # description of prior_checkpoint_feedback can't go stale in one adapter only.
    Given an adapter's casting prompt for a round after the first
    Then it includes PRIOR_FEEDBACK_GUIDE
    And the guide says to plan first from the next_test of every gap with blocks_verdict true
    And then from observations whose check says the evidence doesn't discriminate
    And the first round's prompt doesn't include it
