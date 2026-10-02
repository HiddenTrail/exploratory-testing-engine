# The Skeptic's cold review of each checkpoint hypothesis.
#
# A second model call that never sees the raw test data, only the hypothesis and
# the engine's record of which inputs were sent. Its job is to poke holes. The main
# question per observation is whether the cited evidence would have come out
# differently if the rival were true, since evidence that fits the claim and its
# rival equally well doesn't support either.
#
# The verdict has to follow from the objections, and the validator enforces it, so
# the Skeptic can't stop or continue a run on a whim. Naming an untested corner is
# not an objection: that's what gaps without blocks_verdict are for.
#
# Known and accepted: the discriminates check doesn't allow for ordinary value
# rounding. The comment in SKEPTIC_TOOL records it on purpose and says not to fix
# it in passing.
#
# Code: engine/tools.py (SKEPTIC_TOOL, SKEPTIC_SYSTEM_PROMPT, validate_skeptic_response),
# engine/loop.py (get_skeptic_review)

Feature: A cold Skeptic reviews each checkpoint hypothesis
  As someone who doesn't want the engine to confirm itself
  I want a separate review that judges whether each claim's evidence tells it apart from its rival
  So that "there is evidence" is never treated as "the claim is shown"

  Scenario: The Skeptic sees the hypothesis, never the raw test data
    Given a checkpoint hypothesis and the casting log behind it
    When the loop asks for a Skeptic review
    Then the evidence holds the hypothesis's "summary", "behaviors", "observations", "untested" and "prior_gaps"
    And it holds "test_coverage", which lists the inputs the tests sent, not their results
    And it holds "your_own_prior_review" when there was an earlier checkpoint
    And the casting log is not in the evidence

  Scenario: Each observation gets exactly one check
    Given a hypothesis with observations "C2.O1" and "C2.O2"
    When the Skeptic's "observation_checks" are validated
    Then each check has "observation_id", "discriminates_from_rival", "rival_is_genuine", "kind" and "note"
    And a hypothesis observation with no check is rejected
    And two checks for the same observation are rejected
    And a check for an id that isn't in the hypothesis is rejected

  Scenario: The Skeptic judges per observation whether the evidence discriminates
    Given an observation whose evidence would look the same under its stated rival
    When the Skeptic checks it
    Then it sets "discriminates_from_rival" to false
    And that counts as an objection against the hypothesis

  Scenario Outline: A "weak" verdict needs at least one objection
    Given a Skeptic review with <objection>
    When the review is validated
    Then a "weak" verdict is accepted
    And a "strong_enough" verdict is rejected

    Examples:
      | objection                                                       |
      | an observation check with "discriminates_from_rival" false      |
      | "coverage.material" true                                        |
      | a gap with "blocks_verdict" true                                |
      | a prior gap check with "accepted" false                         |

  Scenario: A review with no objections can only be "strong_enough"
    Given a Skeptic review with no objection of the four kinds
    When the review has the verdict "weak"
    Then it is rejected with "verdict is 'weak' but no objection was raised"
    And the Skeptic is asked again with that error

  Scenario: The Skeptic is told to test the "input was never accepted" rival
    Given the Skeptic system prompt and the observation_checks description
    Then both tell it to check that the hypothesis showed the input was processed at all
    And a claim resting on several inputs that each seem to do nothing gets "discriminates_from_rival" false until a test tells the causes apart

  Scenario: Value rounding is an accepted blind spot of the discriminates check
    # Verified case from the code comment: a claim that 101 credits costing $1.82
    # instead of $1.818 proves "marginal pricing" is ordinary cent rounding of a
    # flat rate, but the Skeptic accepted it as discriminating evidence.
    Given a claim whose only evidence is a price that differs from a flat rate by cent rounding
    When the Skeptic checks it
    Then nothing in the schema or prompt tells it to treat rounding as a rival
    And this stays documented as known scope, not something to patch in passing
