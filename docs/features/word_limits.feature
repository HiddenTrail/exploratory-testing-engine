# Word limits on the short text fields of the hypothesis and the Skeptic review.
#
# Each short field has a word limit, and the limit is written into the field's
# description ("At most 25 words.") so the model sees it. The validator only
# rejects text that runs past twice the limit. A 32-word answer to a 30-word limit
# doesn't cost a retry, but a paragraph where a sentence was asked for does. The
# lists of behaviours, untested areas and gaps work the same way: at most 5 is
# asked for, and only more than 10 is rejected. A rejected answer goes back to the
# model with the error and is asked for again.
#
# The bug report fields and the casting reasoning use the same rule; see
# bug_reports.feature and casting.feature.
#
# Code: engine/tools.py (WORD_LIMITS, SKEPTIC_WORD_LIMITS, is_far_too_long, _check_text)

Feature: Short fields have word limits that only reject far-too-long answers
  As someone paying for runs
  I want each field's word limit shown to the model, and only answers past twice the limit rejected
  So that answers stay short without a retry for every word over

  Scenario: The limit is written into each field's description
    Given the hypothesis and Skeptic tool schemas
    Then the description of "summary" ends with "At most 30 words."
    And the description of a behaviour's "claim" is "At most 25 words."
    And the description of a gap's "next_test" ends with "At most 30 words."

  Scenario Outline: A field is rejected only above twice its limit
    Given a <tool> answer whose <field> has <words> words
    When the answer is validated
    Then it is <result>

    Examples:
      | tool       | field                      | words | result   |
      | hypothesis | summary                    | 32    | accepted |
      | hypothesis | summary                    | 60    | accepted |
      | hypothesis | summary                    | 61    | rejected |
      | hypothesis | behaviour claim            | 51    | rejected |
      | hypothesis | observation claim          | 60    | accepted |
      | hypothesis | observation claim          | 61    | rejected |
      | hypothesis | observation violates       | 51    | rejected |
      | hypothesis | observation mechanism      | 51    | rejected |
      | hypothesis | observation rival          | 51    | rejected |
      | hypothesis | observation why            | 51    | rejected |
      | hypothesis | untested area              | 30    | accepted |
      | hypothesis | untested area              | 31    | rejected |
      | hypothesis | prior gap reason           | 51    | rejected |
      | skeptic    | verdict_reason             | 61    | rejected |
      | skeptic    | observation check note     | 61    | rejected |
      | skeptic    | coverage untouched area    | 31    | rejected |
      | skeptic    | coverage note              | 61    | rejected |
      | skeptic    | gap                        | 40    | accepted |
      | skeptic    | gap                        | 41    | rejected |
      | skeptic    | gap next_test              | 61    | rejected |
      | skeptic    | prior gap check note       | 41    | rejected |

  Scenario: The rejection says how long the text was and what the limit is
    Given a hypothesis whose "summary" has 70 words
    When the answer is validated
    Then the error is "'summary' is far too long (70 words, limit 30)"

  Scenario: A required short field may not be empty
    Given an observation whose "rival" is an empty string
    When the answer is validated
    Then it is rejected with "observations[0].rival must not be empty"
    # "violates" is the exception: it is empty for a finding or an anomaly.

  Scenario Outline: List lengths are asked for at 5 and rejected above 10
    Given a <tool> answer with <count> entries in "<list>"
    When the answer is validated
    Then it is <result>

    Examples:
      | tool       | list      | count | result   |
      | hypothesis | behaviors | 5     | accepted |
      | hypothesis | behaviors | 10    | accepted |
      | hypothesis | behaviors | 11    | rejected |
      | hypothesis | untested  | 10    | accepted |
      | hypothesis | untested  | 11    | rejected |
      | skeptic    | gaps      | 10    | accepted |
      | skeptic    | gaps      | 11    | rejected |
