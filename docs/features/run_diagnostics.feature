# Run diagnostics: facts about the run itself, worked out from the outcome envelopes.
#
# The Driver reasons about the SUT, but nothing was checking the run. A live run
# against the game client got stuck behind a modal after test 5: three of five
# actions did nothing, the return-to-baseline action was one of them, and the run
# spent eight more tests and two more checkpoints there. Every fact needed to see
# it was already in the log.
#
# So after every batch the engine runs a few detectors over the whole log so far.
# They are pure arithmetic: no model call, no I/O, and nothing that knows what a
# modal or an HTTP status is. A "stop" finding ends the run after the checkpoint.
#
# Code: engine/diagnostics.py, engine/loop.py (run_checkpoint_loop)

Feature: The engine checks the run's own mechanics after every batch
  As someone paying for runs
  I want the engine to notice when the tests it ran couldn't have shown anything
  So that a stuck or contaminated run is flagged, and stopped when it can't recover

  Scenario Outline: Each detector fires on the shape of the log it looks for
    Given a casting log with outcome envelopes where <situation>
    When the engine diagnoses the log
    Then there is a finding with code "<code>" and severity "<severity>"

    Examples:
      | situation                                                              | code                    | severity |
      | 2 of the 3 distinct actions tried from state "home" had effect "none"  | degenerate_state        | warn     |
      | checkpoint 1's tests, none naming a start, began in states "a" and "b" | batch_not_independent   | warn     |
      | a test with start_intended "cart" had state_before "home"              | batch_not_independent   | warn     |
      | 1 of 3 reset attempts failed                                           | reset_failing           | warn     |
      | 2 reset attempts in a row failed                                       | reset_failing           | stop     |
      | 5 observations were compared with the prior and none matched           | prior_yield             | warn     |
      | 5 observations were compared with the prior and 2 matched              | prior_yield             | info     |
      | 3 inputs in a row had accepted false                                   | inputs_rejected         | warn     |
      | 2 of 5 inputs had accepted false, never 3 in a row                     | inputs_rejected         | info     |
      | tests ran but none carried an envelope                                 | diagnostics_unavailable | info     |

  Scenario Outline: A detector stays quiet when the evidence is too thin
    Given a casting log with outcome envelopes where <situation>
    When the engine diagnoses the log
    Then there is no finding with code "<code>"

    Examples:
      | situation                                            | code             |
      | only 2 distinct actions were tried from state "home" | degenerate_state |
      | every row from state "home" had effect "unknown"     | degenerate_state |
      | every row had state_before ""                        | degenerate_state |
      | only 4 observations were compared with the prior     | prior_yield      |
      | no row says whether its input was accepted           | inputs_rejected  |
      | no test tried to reset                               | reset_failing    |

  Scenario: Reset failures count consecutive attempts, not consecutive tests
    # A test that didn't try to reset did nothing to fix a failed one, so it
    # doesn't break the run of failures.
    Given test 1's reset failed, test 2 didn't try to reset, and test 3's reset failed
    When the engine diagnoses the log
    Then the "reset_failing" finding has severity "stop"

  Scenario: An empty log gives no findings at all
    Given a casting log with no entries
    When the engine diagnoses the log
    Then there are no findings

  Scenario: Findings come most serious first
    Given a log that produces "info", "stop" and "warn" findings
    When the engine diagnoses the log
    Then the findings are ordered "stop", then "warn", then "info"
    And findings of the same severity are ordered by code

  Scenario: The Driver gets the findings as "run_diagnostics", with their own explanation
    # The explanation travels with the payload so a new adapter's casting prompt
    # doesn't have to remember to describe it.
    Given checkpoint 1's batch produced at least one finding
    When the engine asks the Driver for checkpoint 1's hypothesis
    Then the call's fresh evidence has a "run_diagnostics" object with "what_this_is" and "findings"
    And checkpoint 2's casting call gets the same "run_diagnostics"
    And the Skeptic's review call gets no "run_diagnostics"
    And with no findings there is no "run_diagnostics" key at all

  Scenario: Each checkpoint stores the findings for the whole log so far
    Given a run that has finished checkpoint 2
    Then checkpoint 2's record has a "diagnostics" list worked out from the tests of checkpoints 1 and 2
    And the findings are also printed as lines like "[WARN] <headline> (tests 4, 5)"

  Scenario: A "stop" finding ends the run once the checkpoint is complete
    # The batch was already run and paid for, and its hypothesis and review are the
    # best account of what went wrong, so the checkpoint finishes first.
    Given checkpoint 2's diagnostics include a "reset_failing" finding with severity "stop"
    And the Skeptic's verdict on checkpoint 2 is "weak"
    When checkpoint 2 completes
    Then the run stops with stopped_reason "diagnostics_reset_failing"
    And no checkpoint 3 is cast
