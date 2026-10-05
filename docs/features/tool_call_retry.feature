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
# A casting round that is mostly fine shouldn't end a run over one bad test. CI run
# 37297715890 died after $1.07 because one test of four named a control the map doesn't
# have, at every attempt (#288). So the last attempt can be salvaged.
#
# Code: engine/client.py (call_tool_with_retry, unstring_json_fields),
# engine/tools.py (salvage_casting), engine/loop.py (get_casting_round)

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

  Scenario: JSON text with raw line breaks inside its strings is fixed too, and text that won't parse says why
    # Strict JSON rejects a raw line break inside a string value. A web_gui casting round
    # sent its candidate_tests as text that wasn't fixed, and paid two retries (#244).
    Given the tool schema says "items" is an array
    When the model sends "items" as JSON text with a raw line break inside one of its strings
    Then the validator gets "items" as a real list
    When the model sends "items" as JSON text that doesn't parse
    Then the log shows "couldn't turn JSON text back into structure at items:" and the parser's error
    And the validator still gets the text, and reports it

  Scenario: The last casting attempt keeps its usable tests
    Given every casting reply has 3 tests and one of them fails validation
    When the engine casts with the default 3 attempts
    Then the first two attempts are sent back as usual
    And after the third the round goes on with the 2 tests that pass the validator on their own
    And the log shows "attempt 3 was not all usable: ... - keeping the usable part"
    And the checkpoint records the dropped test and its errors in "dropped_tests"
    And the report's "Tests this checkpoint (N, 1 dropped)" fold lists it, and the run summary says "1 cast test(s) dropped as unusable"

  Scenario Outline: A salvage only keeps a round that is mostly right
    Given the last casting attempt has <good> good tests of <total>
    Then the round is <result>

    Examples:
      | good | total | result                                |
      | 2    | 3     | kept with 2 tests                     |
      | 1    | 2     | kept with 1 test                      |
      | 1    | 3     | not kept, and the engine gives up     |
      | 2    | 2     | accepted as it is, nothing to salvage |
    # A fault in the round itself, like reasoning that isn't text, fails every test on its
    # own, so nothing is kept. What a salvage returns is validated again before it's used.

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
