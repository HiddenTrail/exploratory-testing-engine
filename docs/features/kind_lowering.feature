# Lowering an observation's kind when the evidence doesn't support it.
#
# A bug has to name the known fact it violates and reproduce consistently. A
# "bug" that doesn't is, by those same rules, an anomaly. The validator used to
# reject the whole answer for it, which cost a retry, so now the engine lowers it
# instead (issue #99). After the Skeptic's review, the more cautious of the
# Driver's and the Skeptic's kinds is kept: the Skeptic can lower a kind but never
# raise it, so a bug needs both to agree. Either way the Driver's original kind is
# kept as "driver_kind" and the reason as "lowered_because".
#
# Code: engine/tools.py (lower_unsupported_bugs, reconcile_kinds),
# engine/loop.py (run_checkpoint_loop)

Feature: The engine lowers a kind the evidence doesn't support
  As someone triaging results
  I want a bug that names no violated fact or doesn't reproduce consistently to become an anomaly, and the more cautious kind to win
  So that the bug label always means the same thing and the Skeptic can only lower a claim

  Scenario Outline: An unsupported bug is lowered to an anomaly without a retry
    Given the Driver reports a "bug" with violates "<violates>" and reproduced "<reproduced>"
    When the engine runs lower_unsupported_bugs on the hypothesis
    Then the observation's kind is "<kind>"
    And its "lowered_because" is "<lowered_because>"
    # In the first row the bug is supported, so "lowered_because" isn't set at all.

    Examples:
      | violates                         | reproduced   | kind    | lowered_because                                                                     |
      | the docs say the limit is 5      | consistent   | bug     |                                                                                     |
      |                                  | consistent   | anomaly | it names no violated fact                                                           |
      | the docs say the limit is 5      | once         | anomaly | it reproduced 'once', not consistently                                              |
      |                                  | inconsistent | anomaly | it names no violated fact and it reproduced 'inconsistent', not consistently        |

  Scenario: A lowered bug keeps the Driver's kind
    Given the Driver reports a "bug" with an empty "violates"
    When the engine lowers it
    Then the observation has "driver_kind" "bug"
    And the hypothesis is accepted as it is, with no retry of the model call

  Scenario: Findings and anomalies are never touched by lower_unsupported_bugs
    Given the Driver reports an "anomaly" with an empty "violates" and reproduced "once"
    When the engine runs lower_unsupported_bugs
    Then its kind stays "anomaly" and it has no "driver_kind"

  Scenario Outline: The more cautious of the two kinds wins
    Given the Driver's kind for "C1.O1" is "<driver>"
    And the Skeptic's check of "C1.O1" has kind "<skeptic>"
    When the engine runs reconcile_kinds
    Then the observation's kind is "<kept>"
    And it <lowered>

    Examples:
      | driver  | skeptic | kept    | lowered                                                                          |
      | bug     | anomaly | anomaly | has "driver_kind" "bug" and "lowered_because" "the Skeptic judged it more cautiously" |
      | bug     | finding | finding | has "driver_kind" "bug" and "lowered_because" "the Skeptic judged it more cautiously" |
      | anomaly | finding | finding | has "driver_kind" "anomaly"                                                      |
      | finding | bug     | finding | has no "driver_kind"                                                             |
      | anomaly | bug     | anomaly | has no "driver_kind"                                                             |
      | bug     | bug     | bug     | has no "driver_kind"                                                             |

  Scenario: A bug on an error more than one test recorded isn't lowered
    # #312: the error happened whatever caused it (see oracle_and_errors.feature).
    Given the Driver's "bug" "C1.O1" cites tests 17 and 19, which both recorded "request: PUT /api/BasketItems/# -> 400"
    And the Skeptic's check of "C1.O1" has kind "anomaly"
    When the engine runs reconcile_kinds with the tests' problems
    Then the kind stays "bug", with "kept_as_bug_because"

  Scenario: A bug lowered twice keeps the Driver's original kind
    Given the engine lowered a Driver "bug" to "anomaly" because it names no violated fact
    And the Skeptic's check gives it kind "finding"
    When the engine runs reconcile_kinds
    Then the kind is "finding"
    And "driver_kind" is still "bug"
    And "lowered_because" is "the Skeptic judged it more cautiously"
