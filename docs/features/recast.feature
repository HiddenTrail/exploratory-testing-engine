# A saved casting round can be asked again, to measure a change to the steering (#371).
#
# A change to the steering (blocking questions first #340, debrief promises #352, the
# follow-up and free caps, the oracle ranking) acts on what the Driver casts. Measured
# through whole runs it drowns, because after the first round every run goes its own way
# (#369). Asked again from the same saved checkpoint, the round shows what the change does
# to it, one call a repetition, with nothing run.
#
# Code: trailhound/recast.py, trailhound/runner.py (the "settings" it records),
# trailhound/rejudge.py (reads them). Tests: trailhound/tests/test_recast.py

Feature: A saved casting round can be asked again
  As someone changing how the Driver is steered
  I want to ask the same casting round again several times
  So that I can see what the change does to the round, without the noise of whole runs

  Scenario: The call is the one the loop made
    Given a saved run in runs/<run>
    When "python -m trailhound.recast runs/<run> --adapter web_gui --checkpoint 2 --times 5 --out <dir>" runs
    Then checkpoint 2's casting call is rebuilt from the saved run as the loop built it: the test history so far, the previous review without parked claims, the debrief's promises, the questions that come first, parked claims, run diagnostics, the follow-up ids and the oracle's progress
    And the "video" the runner adds to cited tests after the loop is taken off the history, since the loop never sent it
    And with the same code it is byte for byte the call the loop made, at every checkpoint
    And the round after the run's last checkpoint can be asked too, with "never cast" in the saved row; one further is refused
    And the current code asks it 5 times, and nothing is run

  Scenario: Each round is counted after the loop's limits
    Then each answer goes through the loop's limits (the follow-up and free caps, parked claims)
    And a table has a row for the saved round and one per repetition: tests cast, run and dropped, follow-ups, questions answered first of those needed, promises answered, oracle tests and how many ideas, free tests, start points, retries and cost
    And tests cast and dropped count what the last-attempt salvage took out too, in both rows alike
    And start points are "-" for an adapter whose tests have no start
    And every answer, its counts and its usage are written to <dir>/rounds.json after each repetition
    And all repetitions share one spending limit, and stop when it's reached; a repetition that fails is counted as empty and the next one goes on

  Scenario: A run records its settings
    Then since #371 output.json has "settings": the model, the number of checkpoints, both test budgets and the objections history the Driver was given
    And recast and rejudge take the budgets, the model and the objections history from there
    But for a run saved before, recast needs --first-round-budget and --default-budget, uses the default model unless --model says otherwise, and leaves the objections history out
