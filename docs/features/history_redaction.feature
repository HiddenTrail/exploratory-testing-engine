# History redaction: what of the casting log the model gets to see again.
#
# Every casting and hypothesis call replays the tests run so far, and the bug
# report call gets all of them. That history goes through a redaction step first.
# By default it hides no content. It drops bookkeeping: the Driver's own round
# reasoning (so the model isn't fed its earlier reasoning word for word), the
# outcome envelope (a copy of the result in other words, meant for diagnostics,
# that would otherwise sit in every cached history segment for the rest of the run)
# and the test as cast (it repeats the request and is kept only for replaying bugs).
#
# An adapter can replace the default with its own redact_history_for_model.
# web_gui does, to cut a discovered screen down in the prompt while keeping the
# full record in output.json.
#
# Code: trailhound/redact.py, trailhound/loop.py (_redact), trailhound/adapters/web_gui/adapter.py

Feature: The test history shown to the model is redacted
  As someone maintaining the engine
  I want bookkeeping dropped from the history the model sees, with adapters able to cut more
  So that the model reads results, not its own reasoning or the engine's records

  Scenario: The default redaction drops three bookkeeping keys
    Given a casting log entry with "round_reasoning", "outcome", "cast_test", "checkpoint", "linked_hypothesis" and a result
    When the engine redacts the history for the model
    Then the entry has no "round_reasoning", "outcome" or "cast_test"
    And everything else, "checkpoint" included, is kept

  Scenario: Redaction never changes the saved log
    When the engine redacts the history for the model
    Then it works on a deep copy
    And output.json's "casting_log" still has every key, the outcome envelope included

  Scenario: The model sees diagnostics instead of envelopes
    # The envelopes go, but what the engine worked out from them goes in.
    When the Driver is asked for a hypothesis
    Then its history has no outcome envelopes
    And its fresh evidence has "run_diagnostics" when there are findings

  Scenario Outline: Redaction is applied wherever the model sees past tests
    When the engine sends past tests as <where>
    Then the adapter's redact_history_for_model is used if it has one, and the default if not

    Examples:
      | where                                                   |
      | a history fragment for the casting and hypothesis calls |
      | "all_tests_this_session" for the bug report call        |

  Scenario: An adapter can redact more
    # web_gui keeps the full discovered screen in output.json for feedback, but it
    # would bloat every later prompt.
    Given the "web_gui" adapter, whose redact_history_for_model starts from the default
    And a test result that discovered a new screen with its path and every element
    When the engine redacts the history for the model
    Then the first time a screen from the run's map appears in those entries, the model gets its id and up to 30 control names it may act on
    And "controls_more" counts any controls past 30
    And every later mention of that screen in those entries shows only its id
    # Each checkpoint's fragment is redacted on its own, so "first" is per fragment.
