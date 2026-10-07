# Ids for observations and gaps, stamped by the engine.
#
# The engine gives every observation an id like "C2.O1" and every Skeptic gap an
# id like "C2.G3" right after the call that produced it (issue #41). The model
# never picks them, so they are unique and stable across the run. Later calls
# then refer to an item by id instead of quoting it back: the Skeptic checks
# observations by id, the Driver answers gaps by id, a new observation can
# "continues" an earlier one, and a bug report names the observation it's for.
#
# Code: trailhound/tools.py (stamp_observation_ids, stamp_gap_ids),
# trailhound/loop.py (run_checkpoint_loop)

Feature: The engine stamps ids on observations and gaps
  As someone following a run across checkpoints
  I want every observation and gap to get an id from the engine
  So that claims and gaps can be traced from checkpoint to checkpoint

  Scenario Outline: Observations are numbered per checkpoint, in order
    Given checkpoint <checkpoint> produced a hypothesis with 3 observations
    When the engine stamps observation ids
    Then the observations get the ids "<ids>"

    Examples:
      | checkpoint | ids                  |
      | 1          | C1.O1, C1.O2, C1.O3  |
      | 3          | C3.O1, C3.O2, C3.O3  |

  Scenario: Gaps are numbered per checkpoint, in order
    Given the Skeptic's review at checkpoint 2 raised 2 gaps
    When the engine stamps gap ids
    Then the gaps get the ids "C2.G1" and "C2.G2"

  Scenario: Observation ids go on before the Skeptic sees the hypothesis
    Given the Driver's hypothesis has just come back
    When the loop prepares the Skeptic call
    Then the observations already have their ids
    And the Skeptic's "observation_checks" and gap "about" lists can name them

  Scenario: The model is told its own observations have no ids yet
    Given the hypothesis system prompt and the "continues" field description
    Then they say the observations in this answer don't have ids yet
    And "continues" may only name an id from "earlier_observations"
    # An id the model put on its own answer would be overwritten by the stamp anyway.

  Scenario: Every observation from earlier checkpoints stays citable
    Given checkpoint 1 stamped "C1.O1" and checkpoint 2 stamped "C2.O1"
    When checkpoint 3 asks the Driver for a hypothesis
    Then "earlier_observations" lists both "C1.O1" and "C2.O1"
    And a new observation may set "continues" to either of them
