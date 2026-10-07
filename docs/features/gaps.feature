# Gaps: what the Skeptic says is missing, and how the Driver answers it.
#
# Each gap the Skeptic raises comes with the test that would close it, a flag for
# whether it's a reason for "weak", and the observations it's about. The next
# checkpoint plans from those gaps, and its hypothesis has to answer every one of
# them by id, exactly once, with a status. Then the Skeptic judges each answer.
# This stops gaps from being quietly dropped between checkpoints, and it means
# "tested" has to cite a real test.
#
# Code: trailhound/tools.py (SKEPTIC_TOOL "gaps" and "prior_gaps_check",
# HYPOTHESIS_TOOL "prior_gaps", _prior_gaps_errors, validate_skeptic_response)

Feature: Gaps carry a next test and must be answered at the next checkpoint
  As someone running a session
  I want each gap to name the test that closes it, and the Driver to answer every open gap by id
  So that the next checkpoint knows what to try and no gap disappears without an answer

  Scenario: A gap names its next test, whether it blocks the verdict, and what it's about
    Given the Skeptic raises a gap
    Then it has "gap", "next_test", "blocks_verdict" and "about"
    And "blocks_verdict" must be a boolean
    And "about" lists observation ids from this hypothesis, or is empty for coverage in general
    And an "about" that names an id not in the hypothesis is rejected

  Scenario Outline: The Driver answers each prior gap with one of four statuses
    Given the prior Skeptic review raised gap "C1.G1"
    When the next hypothesis answers it with status "<status>", tests <tests> and reason "<reason>"
    Then the answer is <result>

    Examples:
      | status        | tests | reason                            | result                                              |
      | tested        | [7]   |                                   | accepted                                            |
      | tested        | []    |                                   | rejected: tested must cite the test numbers         |
      | untestable    | []    | no known account has two cards    | accepted                                            |
      | untestable    | []    |                                   | rejected: reason must not be empty                  |
      | resolved      | [3]   | test 3 already shows the limit    | accepted                                            |
      | not_attempted | []    | the budget went to C1.G2          | accepted                                            |
      | skipped       | []    | ran out of time                   | rejected: status must be one of the four            |

  Scenario: Every open gap is answered exactly once
    # Except the questions only about a parked claim (#305): they drop out (see new_ground_and_parking.feature).
    Given the prior Skeptic review raised gaps "C1.G1" and "C1.G2"
    When the next hypothesis's "prior_gaps" answers only "C1.G1"
    Then it is rejected with "'prior_gaps' doesn't answer C1.G2"
    And answering "C1.G1" twice is rejected as answered more than once
    And answering "C1.G9" is rejected as not a gap from the prior review

  Scenario: On the first checkpoint there are no gaps to answer
    Given checkpoint 1 has no prior Skeptic review
    When its hypothesis has an entry in "prior_gaps"
    Then it is rejected, because no gap from a prior review exists yet

  Scenario Outline: The Skeptic accepts or rejects each answer to its own earlier gaps
    Given the Skeptic's prior review raised gap "C1.G1"
    And the Driver answered it in "prior_gaps"
    When the Skeptic's "prior_gaps_check" for "C1.G1" has "accepted" <accepted>
    Then it <counts>

    Examples:
      | accepted | counts                                                 |
      | true     | raises no objection                                    |
      | false    | counts as an objection, so the verdict must be "weak"  |

  Scenario: The Skeptic checks each of its earlier gaps exactly once
    Given the Skeptic's prior review raised gaps "C1.G1" and "C1.G2"
    When its "prior_gaps_check" has an entry for "C1.G1" only
    Then the review is rejected for having no entry for "C1.G2"
    And an entry for a gap it never raised is rejected
