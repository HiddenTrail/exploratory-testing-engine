# The checkpoint hypothesis: the Driver's one structured claim per checkpoint.
#
# After each batch the Driver answers through HYPOTHESIS_TOOL with short fields,
# test numbers as evidence and no ids of its own (issue #41). Every observation is
# a finding, an anomaly or a bug, and it has to name a genuine rival explanation
# and say whether the evidence rules it out. That gives the Skeptic something
# concrete to attack. The rival that is easiest to skip, "the input was never
# accepted", is written into both the schema and the prompt, because several
# inputs that each seem to do nothing are better explained by one cause (nothing
# was being accepted) than by several broken controls.
#
# The schema is shared and adapters can't override it.
#
# Code: trailhound/tools.py (HYPOTHESIS_TOOL, HYPOTHESIS_SYSTEM_PROMPT,
# validate_hypothesis_response), trailhound/loop.py (get_checkpoint_hypothesis)

Feature: The Driver forms one structured hypothesis per checkpoint
  As someone reading a run
  I want each checkpoint to end in one claim with confirmed behaviours, falsifiable observations and what's untested
  So that every claim names its evidence and a rival, and can be traced from checkpoint to checkpoint

  Scenario: A hypothesis has five required parts
    Given the Driver calls "submit_checkpoint_hypothesis"
    When validate_hypothesis_response checks the answer
    Then it must have "summary", "behaviors", "observations", "untested" and "prior_gaps"
    And each behaviour has a "claim" and the "tests" it rests on
    And each untested entry has an "area"
    And "observations" may be an empty list, because the system may have no problems at all
    And it may have "ideas" (an answer per oracle idea its tests checked) and "dismissed_errors", which must cover what the evidence asks (see oracle_and_errors.feature)

  Scenario: Every observation cites tests, a mechanism and a rival explanation
    Given an observation in the hypothesis
    Then it has "kind", "continues", "claim", "tests", "violates", "reproduced", "mechanism", "rival", "rival_ruled_out", "why" and "severity"
    And "tests" must be a non-empty list of test numbers
    And "rival_ruled_out" must be a boolean
    And "reproduced" is one of "consistent", "inconsistent" or "once"
    And "severity" is one of "low", "medium" or "high"

  Scenario Outline: Observations come in three kinds
    Given an observation of kind "<kind>"
    Then the schema describes it as "<meaning>"
    # The bug row shortens the list of known facts: the spec, the docs, an oracle
    # claim, a value the system itself disclosed.

    Examples:
      | kind    | meaning                                                                                                   |
      | finding | something iffy worth a look, no problem shown yet                                                         |
      | anomaly | a real problem, but it doesn't clearly contradict a known fact, or it doesn't reproduce consistently      |
      | bug     | contradicts a known fact (...) or breaks or blocks something, and reproduces consistently                 |

  Scenario: A kind outside the three is rejected
    Given an observation of kind "defect"
    When validate_hypothesis_response checks the answer
    Then it is rejected with "kind must be one of finding, anomaly, bug"

  Scenario: The "input was never accepted" rival is always put in front of the Driver
    Given the observations field description and the hypothesis system prompt
    Then both say the rival "the input was never accepted" is always available
    And the Driver is told to rule it out or say why it doesn't apply
    And the prompt says several inputs that each seem to do nothing point to one cause until a test tells them apart

  Scenario: The Driver sees earlier observations as id, kind and claim only
    Given checkpoint 1 produced observations "C1.O1" and "C1.O2"
    When checkpoint 2 asks for a hypothesis
    Then the fresh evidence has "earlier_observations" with only "id", "kind" and "claim" for each
    And the prior Skeptic review is passed as "prior_skeptic_review"

  Scenario Outline: "continues" may only name an earlier checkpoint's observation
    Given the earlier observation ids are "<known>"
    When an observation has "continues" set to "<continues>"
    Then the answer is <result>

    Examples:
      | known        | continues | result                                                          |
      | C1.O1, C1.O2 |           | accepted, it's a new observation                                |
      | C1.O1, C1.O2 | C1.O2     | accepted                                                        |
      | C1.O1, C1.O2 | C1.O3     | rejected: "C1.O3" isn't an earlier observation id               |
      |              | C1.O1     | rejected, there are none yet on the first checkpoint            |
