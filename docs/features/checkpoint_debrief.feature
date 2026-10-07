# The checkpoint debrief: a short conversation the Driver has to win with evidence (issue #266).
#
# The Skeptic's value isn't a slap on the fingers and "test more". It's "convince me, with
# argument and evidence". Before this, the Driver could only answer the Skeptic a checkpoint
# later, with new tests, so a dispute cost a whole round. Now, when the Skeptic's review is
# "weak", the Driver answers each question right away, the way a tester answers a test lead
# in a session debrief, and the Skeptic reconsiders. The engine attaches what the cited tests
# recorded, so the Skeptic judges facts, not wording. Everything is recorded: it's the proof
# of process behind every verdict. Part of epic #262. Accepted cost: two more model calls on
# a checkpoint with questions.
#
# Code: trailhound/tools.py (DEBRIEF_ANSWER_TOOL, RECONSIDER_TOOL, their prompts,
# validate_debrief_answers, validate_reconsideration, merge_debrief, open_part),
# trailhound/loop.py (get_debrief_answers, cited_evidence, get_reconsideration,
# run_checkpoint_loop), trailhound/client.py (rejected attempts), trailhound/interplay.py,
# trailhound/report.py (_debrief_html, _verdict_change, _still_open).
# Tests: trailhound/tests/test_debrief.py

Feature: Each checkpoint ends with a debrief the Driver has to win with evidence
  As someone who wants findings that survived questioning
  I want the Driver to answer the Skeptic's questions with argument and evidence, and the Skeptic to reconsider
  So that a dispute is settled by evidence in the same checkpoint, and the exchange is on record

  Scenario: The debrief runs only when there's something to debrief
    When the Skeptic's first review of a checkpoint is "weak" and has questions (gaps)
    Then the Driver answers them, and the Skeptic reconsiders
    And a "strong_enough" review, or one with no questions, has no debrief

  Scenario Outline: The Driver answers each question once, with a stance
    When the Driver answers question "C1.G1" with stance "<stance>"
    Then <rule>

    Examples:
      | stance          | rule                                                                              |
      | defend          | it argues and cites the tests that show it, at most 8, or the answer is retried   |
      | concede         | it says exactly what it withdraws or lowers                                       |
      | change_approach | it says what it will test differently next round, and why that gives new evidence |

  Scenario: The Skeptic judges against what the tests recorded
    Given the Driver cites tests 3 and 5
    Then the engine attaches tests 3 and 5 as the Driver saw them (the adapter's redacted view)
    And the Skeptic judges each answer "yes", "partly" or "no" convinced, with why
    And it can revise the check of an observation whose evidence the answers changed

  Scenario: Being argued at is not being convinced
    Given a question blocked the verdict and the Skeptic was not convinced by its answer
    When the Skeptic answers "strong_enough"
    Then the reconsideration is rejected and retried
    And the same holds for a blocking question the Driver answered with a new approach or a concession, even if the Skeptic said "yes": a promised approach proves nothing yet
    And the same holds for an observation check that still says its evidence doesn't discriminate

  Scenario Outline: Each question ends with an outcome
    Given the Driver's stance was "<stance>" and the Skeptic was "<convinced>" convinced
    Then the question's outcome is "<outcome>"

    Examples:
      | stance          | convinced | outcome      |
      | defend          | yes       | settled      |
      | defend          | no        | open         |
      | concede         | partly    | conceded     |
      | change_approach | no        | new_approach |
      | change_approach | yes       | new_approach |

  Scenario: Settled questions stop blocking; settled and conceded ones need no further answer
    Then a settled question that blocked the verdict no longer does, and is marked "blocked_before_debrief"
    And a conceded question's observation stays unproven
    And the next checkpoint answers only the questions still open or awaiting a new approach
    And the checkpoint's verdict is the Skeptic's verdict after the debrief, with the first one kept as "first_verdict"
    And a "strong_enough" verdict after the debrief ends the run as "skeptic_satisfied"

  Scenario: The debrief is recorded and shown
    Then each checkpoint in output.json has "debrief": per question its kind, wording, the Driver's answer, the evidence attached, the Skeptic's judgement and the outcome
    And the report shows a folded "Debrief" per checkpoint, and the verdict before the debrief when it changed
    And "Where it stands" lists the questions still open at the end
    And the measures count questions, defended, conceded and changed approach, convinced and partly, and what's still open
    And a malformed attempt's errors are kept in the usage log under "rejected"
