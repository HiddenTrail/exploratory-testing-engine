# Bug replay: run a bug's tests again before it is reported (#177, merged in #230).
#
# Its tests are in engine/tests/test_verify.py.
#
# Why: the #160 milestone run reported a corroborated, high-severity bug (/profile
# returns 500) that came from an expired saved session, and nothing ran the tests
# again. So after the last checkpoint, every test a bug cites runs again
# exactly as cast, and the adapter says whether each came out the same. No model call
# is made. Replay is opt-in through SUTAdapter.compare_replay, because only the adapter
# knows whether its tests can run twice. Today only web_gui supplies it.
#
# Code: engine/verify.py, runner.py, adapter.py, loop.py, redact.py,
# report.py, adapters/web_gui/adapter.py and session.py

Feature: A bug's tests are replayed before it is reported
  As someone who doesn't want false bugs in a report
  I want every test a bug cites run again, and the adapter to say whether each came out the same
  So that a bug that doesn't reproduce is lowered to an anomaly before a bug report is written

  Background:
    Given a run whose final observations include the bug "C2.O1" citing tests 1 and 2
    And the casting log kept each test exactly as cast under "cast_test"

  Scenario Outline: The replay verdict decides whether the bug stays a bug
    Given <situation>
    When the bug's tests are replayed after the last checkpoint
    Then the bug's "replay" is "<verdict>"
    And its kind is "<kind>"

    Examples:
      | situation                                                                 | verdict         | kind    |
      | the adapter has no compare_replay                                         | not available   | bug     |
      | both replays come out the same                                            | reproduced      | bug     |
      | one replay comes out different                                            | not reproduced  | anomaly |
      | the adapter's before_replay says replays can't be trusted right now       | couldn't replay | anomaly |
      | the bug cites a test that isn't in the casting log, or was skipped        | couldn't replay | anomaly |
      | a replay raises an exception and the other comes out the same             | couldn't replay | anomaly |
      | the adapter can't tell either way for one test and the other is the same  | couldn't replay | anomaly |

  Scenario: A lowered bug keeps what the Driver said and why it was lowered
    Given test 2's replay came out different, with the detail "got 200"
    When the bug is lowered
    Then its kind is "anomaly" and its "driver_kind" is "bug"
    And "lowered_because" starts "its tests didn't come out the same on a fresh replay" and holds "got 200"
    And no bug report is written for it
    And the run still has "anomaly_found" true

  Scenario: A cited test whose original showed nothing doesn't count either way
    # The milestone bug cited tests 7 and 8, which never reached their state, next to test 13.
    Given compare_replay says test 1's original "original_ran" false
    And test 2's replay comes out the same
    When the replay verdict is worked out
    Then the verdict is "reproduced"
    But if test 1 were the only cited test, the verdict would be "couldn't replay" because none of its tests showed anything

  Scenario: Replays take the next test numbers and are kept in the output
    Given the run's last test was number 2
    When the bug's tests 1 and 2 are replayed
    Then the replays run as tests 3 and 4
    And "output.json" has a "replays" record per bug with its verdict, detail and per-test results
    And "replay_log" holds each replay's result with "replay_of" and "for" set
    And the run prints "  replayed C2.O1: reproduced"

  Scenario: Only bugs are replayed
    Given the final observations also hold a finding and an anomaly
    When replay runs
    Then neither of them is replayed or gets a "replay" verdict

  Scenario: The test as cast is kept for replay but never shown to the model
    When the casting log is redacted for the model's history
    Then "cast_test" is dropped from every entry, as "round_reasoning" already is

  Scenario: web_gui refuses to replay from a session the server no longer accepts
    Given a web_gui run that started from a saved session
    When the saved session has gone stale, or the "WEB_GUI_SESSION_CHECK" path now answers 400 or more, or nothing
    Then before_replay returns the reason
    And every bug is marked "couldn't replay" with that reason, and no test is replayed

  Scenario Outline: The report shows each observation's replay verdict as a badge
    Given an observation with replay verdict "<verdict>"
    When the report's conclusion section is rendered
    Then it shows the badge "replay: <verdict>" in the "<kind>" style

    Examples:
      | verdict         | kind |
      | reproduced      | good |
      | not reproduced  | bad  |
      | couldn't replay | warn |
      | not available   | warn |
    # A run from before #177 has no verdict, so it shows no badge.
