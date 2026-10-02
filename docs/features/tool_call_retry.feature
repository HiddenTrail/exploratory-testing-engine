# Forced tool calls, checked and retried with the errors sent back.
#
# Every model call in a run (casting, hypothesis, Skeptic, bug reports) forces one
# named tool and checks the answer with a validator. A retry is not a blind repeat:
# the model's own bad answer goes back with the concrete errors, so a systematic
# mistake can correct itself instead of coming back the same every time.
#
# Some failures need a different correction. A reply cut off at max_tokens looks
# like a model ignoring the schema, and "fix it" just gets the same long answer cut
# off again, so it is asked to be shorter. A reply split over several tool calls
# crashed a paid run until every call got its own result (#134). A list sent as
# JSON text cost a retry on about half the hypothesis calls (#91), so that is
# repaired before validation. The raw rejected answer goes into the log (#95).
#
# Code: engine/client.py (call_tool_with_retry, unstring_json_fields)

Feature: Every model call is a forced tool call, checked and retried with feedback
  As someone paying for runs
  I want each malformed answer sent back with what was wrong, in a way that fits how it went wrong
  So that most bad answers are fixed on the next try instead of failing the run

  Scenario: The call forces the named tool
    When the engine calls the model for "submit_checkpoint_hypothesis"
    Then the request has tool_choice type "tool" with name "submit_checkpoint_hypothesis"

  Scenario: A rejected answer is sent back with the validator's errors
    Given the validator rejects the first answer with "missing required field 'observations'"
    And accepts the second
    When the engine calls the model
    Then the model is called twice
    And the second request ends with a tool_result for the first call, marked "is_error"
    And that result starts with "Invalid: missing required field 'observations'"
    And the log shows "attempt 1 raw answer (stop_reason=..." followed by the raw answer, cut at 1500 characters
    And the log shows "attempt 1 produced malformed output"

  Scenario: A reply with no tool call is asked again
    Given the first reply has no tool_use block
    When the engine calls the model
    Then the next request adds the user message "You must call the tool. Try again."

  Scenario: A reply cut off at max_tokens is asked to be shorter
    Given the first reply has stop_reason "max_tokens" and fails validation
    When the engine calls the model
    Then the tool_result says the reply hit the token limit and was cut off
    And asks to keep every free-text field to one short sentence
    And it does not start with "Invalid:"

  Scenario: Every tool call in a split reply gets its own result
    # Answering only the first call made the API refuse the retry outright (#134).
    Given the first reply has two tool_use blocks and the first fails validation
    When the engine calls the model
    Then the retry carries one error tool_result per tool_use id
    And the extra call's result says "Ignored: answer with exactly one call to <tool name>."

  Scenario: A list or object sent as JSON text is turned back into structure
    # This used to cost a retry on about half the hypothesis calls (#91).
    Given the tool schema says "items" is an array
    And the model sends "items" as the text '[{"tags": ["a"]}]'
    When the engine calls the model
    Then the validator gets "items" as a real list
    And no retry is made
    And the log shows "turned JSON text back into structure at: items"
    # Text that doesn't parse, or parses to the wrong type, is left for the validator.

  Scenario Outline: The engine gives up after the attempt budget is spent
    Given every reply <failure>
    When the engine calls the model with the default 3 attempts
    Then the model is called 3 times
    And a RuntimeError is raised starting with "Gave up after 3 attempts, last errors:"
    And the last errors <detail>

    Examples:
      | failure                                       | detail                                        |
      | fails validation                              | are the validator's errors                    |
      | is cut off at max_tokens and fails validation | start with "reply was cut off at max_tokens=" |
      | has no tool call                              | say "no tool_use block in response"           |
