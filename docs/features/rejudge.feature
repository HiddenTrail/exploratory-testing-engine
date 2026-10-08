# A saved run's tests can be judged again, to measure a change to the judging (#370).
#
# Runs with the same code and settings differ more than any change we had measured: one
# found 0 known problems, its twin 3 (#369). Most of that is the tests themselves, which
# differ from run to run. A change to the hypothesis, the Skeptic or the debrief only acts
# on the judging, so it's measured on the same tests: the saved run's tests and results
# are handed back, and only the judging is done again. The loop's own code does it, so the
# evidence can't drift from what a live run sends.
#
# Code: trailhound/rejudge.py, trailhound/loop.py (run_checkpoint_loop's replay, _cast),
# trailhound/runner.py (run's replay). Tests: trailhound/tests/test_rejudge.py

Feature: A saved run's tests can be judged again
  As someone changing how the Driver or the Skeptic judges
  I want to judge the same tests again, several times, cheaply
  So that I can tell the change from the randomness of which tests a run happened to run

  Scenario: Only the judging is done again
    Given a saved run in runs/<run> with "cast_test" on every casting-log entry
    When "python -m trailhound.rejudge runs/<run> --adapter web_gui --times 3 --out <dir>" runs
    Then each checkpoint runs the saved round's tests exactly: no casting call, and the follow-up, blocking and free limits aren't applied again
    And the adapter hands back each test's saved result, by its saved test number, so nothing touches the system under test
    And the hypothesis, the testing story, the Skeptic and the debrief are called by the same code as a live run
    And the evidence they're sent is exactly what the live run sent them, given the same answers before it
    And the "video" the runner adds to cited tests after a live run is taken off, since it would show which tests the saved judging relied on

  Scenario: A re-judgement can come out differently
    Then a checkpoint's judging builds on the re-judged checkpoint before it, not the saved one
    And a re-judgement the Skeptic is satisfied with sooner stops sooner
    And one that goes on past the saved run's last checkpoint stops with "replay_ended", when the saved run stopped before its cap; one that used up its checkpoints has as many again
    And "--first-round-budget" and "--default-budget" give the saved run's budgets, which only the records use (the "needed" count of blocking questions); the adapter's defaults otherwise

  Scenario: What it leaves out and how it's written
    Then a lean run is re-judged lean, with the same parts switched on, and "--with" switches more on
    And no SUT check, bug replays, videos or bug reports, which need the live system ("replays" is empty)
    And a repetition uses the model and the history of earlier runs' objections the saved run recorded in "settings" (#371); a run saved before has neither, so it gets the default model and no history
    And each repetition is written to <dir>/r<N> as output.json and report.html, with "rejudged_from" naming the saved run
    And all repetitions share one spending limit, TRAILHOUND_MAX_COST_USD, and stop when it's reached
    And at the end a table has one row for the saved run and one per repetition: how it stopped, checkpoints, claims holding up, summaries judging the product, objections and how many blocked, objections by kind, retries and cost
    But a run saved before cast tests were kept (#177) is refused: "... was saved before cast tests were kept (#177), so its tests can't be replayed."
