# Token usage: every raw model response is logged, and summed per call type.
#
# Each model response adds one record to the run's usage_log, including the ones a
# retry threw away, because those cost real tokens too. A record carries a wall
# clock time, so a cache_read of 0 can be explained afterwards: a gap of more than
# the 5-minute cache window since the last call of the same name is plain expiry,
# and a short gap points at the prompt's prefix having changed.
#
# The raw rows are kept in output.json next to the summary on purpose. A summary
# showing cache_read=0 can't say which call missed or how far apart they were.
# The engine records token counts only. It does not work out a price.
#
# Code: trailhound/client.py (_record_usage, summarize_usage), trailhound/runner.py

Feature: Every model response's token use is logged and summed per call type
  As someone paying for runs
  I want each response's input, output and cache token counts kept, retries included
  So that I can see where a run's tokens went and why a cache missed

  Scenario: Each raw response adds one record to the usage log
    When the engine calls "submit_casting_round" and the response reports its usage
    Then the usage log gets a record with "call" "submit_casting_round" and an "at" timestamp in UTC
    And the record has "input_tokens", "output_tokens", "cache_creation_input_tokens" and "cache_read_input_tokens"
    And the console shows "[submit_casting_round] tokens: input=... (cache_read=..., cache_creation=...) output=..."

  Scenario: A response that failed validation is still logged
    Given the first answer fails validation and the second passes
    When the engine calls the model
    Then the usage log has 2 records for that call

  Scenario: A response without usage data adds nothing
    # Stubbed messages in tests have no usage attribute.
    Given a response with no usage attribute
    When the engine calls the model
    Then the usage log is unchanged

  Scenario: The summary has one totals row per call type
    Given a usage log with 2 "submit_casting_round" records and 1 "submit_skeptic_review" record
    When the engine summarises the usage
    Then "submit_casting_round" has "calls" 2 and the sum of each token count
    And "submit_skeptic_review" has "calls" 1
    And an empty usage log gives an empty summary

  Scenario: output.json keeps both the raw log and the summary, mid-run too
    When a run saves its progress after a checkpoint
    Then output.json has "usage_log" with every record so far
    And "usage_summary" totals those same records
    And at the end of the run the console prints "Token usage by call type:" with one line per call type

  Scenario: No dollar cost is worked out
    When a run finishes
    Then "usage_summary" holds call counts and token counts only
    And no field in output.json gives a price
