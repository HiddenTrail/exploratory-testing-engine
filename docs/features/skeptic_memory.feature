# The Driver learns, between runs, what the Skeptic keeps objecting to (issue #258).
#
# The Driver answered objections one checkpoint late and never learned which ones keep
# coming. The Skeptic stays the critic: its gaps are questions about the testing, not a
# list of what nobody has tried. It tags each gap with a kind from a fixed list, the feedback
# step counts the kinds per system in the context layer, and the next run's Driver is
# told the most common ones before it casts a test. It's learned between runs, never
# within one, and the Skeptic doesn't see it, so its review stays cold. No extra model
# call: the kind is one more field on an answer the Skeptic already gives.
#
# Code: engine/tools.py (OBJECTION_KINDS, the Skeptic's gap schema and validator),
# engine/ontology/feedback.py (extract_objections, merge_objections, driver_history,
# learn), engine/ontology/oracle_creator.py (context_path), engine/loop.py
# (_base_evidence), engine/config.py, engine/cli.py.

Feature: The Driver is told what the Skeptic objected to most in earlier runs
  As someone who wants the Driver to answer objections before they're raised
  I want the Skeptic's objections counted by kind across runs, and the common ones shown to the Driver
  So that the Driver designs tests against the objections it usually gets

  Scenario Outline: Every gap the Skeptic raises has a kind
    # An untested area is a gap only if the Driver called it covered or it bears on a claim.
    When the Skeptic reviews a checkpoint
    Then each gap has "kind" set to one of the objection kinds
    And a gap with any other kind makes the review invalid, so it's retried

    Examples:
      | kind                 | means                                                                                                                                                           |
      | overclaimed          | the claim is stronger than the tests behind it                                                                                                                  |
      | coverage_overstated  | something is called covered or confirmed that the tests don't show                                                                                              |
      | method_in_doubt      | a test may not have done what was meant: it didn't reach its state, the input wasn't accepted, tests weren't independent, or the result came from the test tool |
      | rival_not_tested     | no test tells the claim from its rival explanation                                                                                                              |
      | not_reproduced       | it was seen once, or not repeated the same way                                                                                                                  |
      | not_worth_continuing | this line gives no new evidence; more of the same won't change anything                                                                                         |
      | other                | none of these                                                                                                                                                   |

  Scenario: Feedback counts the objections by kind
    When feedback learns from a run
    Then context "skeptic_objections" counts each kind: "times", "blocking", "runs" and the latest "example"
    And gaps from runs made before kinds existed, or with an unknown kind, are left out
    And it prints "The Skeptic's objections this run:" with each kind and how often

  Scenario: The next run's Driver is told the most common kinds
    Given the context counts earlier objections
    When a run starts
    Then the Driver's evidence has "skeptic_history" with a note and up to 4 kinds, those that blocked the verdict most first
    And each has what it means, how often it came up, how often it blocked the verdict, in how many runs, and an example
    And "other" is never shown, because it says nothing to design against
    And the note says they're kinds from past runs, not gaps to answer in prior_gaps
    And the run prints "The Driver is told what the Skeptic objected to most before:" with the kinds

  Scenario: The history is read from the same context file --learn writes
    When the run command runs with "--learn juice-shop"
    Then the history is read from context_juice-shop.json
    And without --learn, or with it bare, from the adapter's own context file
    And without any counted objections, the Driver's evidence has no "skeptic_history"

  Scenario: The Skeptic never sees the history
    Then "skeptic_history" is in the evidence for casting and for the hypothesis only

  Scenario: A benchmark can learn into a scratch folder
    # So a benchmark doesn't change a committed context file such as context_token_purchase.json.
    Given ENGINE_CONTEXT_DIR is set to a folder
    Then context files are read from and written to that folder instead of engine/ontology
