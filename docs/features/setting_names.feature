# The engine's settings are named TRAILHOUND_ since the project became Trailhound (#335).
# The old ENGINE_ names still work for now, so a .env, a shell or a benchmark script
# written before the rename keeps working. Above all, a spending limit set under its old
# name must still limit the run, not be silently ignored.
#
# Code: trailhound/settings.py, read by trailhound/budget.py, trailhound/client.py (use_bedrock) and
# trailhound/ontology/oracle_creator.py (context_path). Tests: trailhound/tests/test_settings.py

Feature: Settings are named TRAILHOUND_, and the old ENGINE_ names still work
  As someone with settings written before the rename
  I want the old names to keep working, and to be told to rename them
  So that no setting, least of all a spending limit, is silently dropped

  Scenario Outline: Each setting has a new name and an old one
    Then the engine reads "<new>", and "<old>" when the new one isn't set

    Examples:
      | new                        | old                    |
      | TRAILHOUND_MAX_COST_USD    | ENGINE_MAX_COST_USD    |
      | TRAILHOUND_MAX_MODEL_CALLS | ENGINE_MAX_MODEL_CALLS |
      | TRAILHOUND_USE_BEDROCK     | ENGINE_USE_BEDROCK     |
      | TRAILHOUND_CONTEXT_DIR     | ENGINE_CONTEXT_DIR     |

  Scenario: An old name still works, and says so once
    Given ENGINE_MAX_COST_USD is "0.75" and TRAILHOUND_MAX_COST_USD isn't set
    When a run starts
    Then the limit is about $0.75
    And it prints "ENGINE_MAX_COST_USD is the old name of TRAILHOUND_MAX_COST_USD. It still works for now, but rename it." once

  Scenario: The new name wins when both are set, and the run says the old one is ignored
    Given TRAILHOUND_MAX_COST_USD is "2.5" and ENGINE_MAX_COST_USD is "0.5"
    When a run starts
    Then the limit is about $2.50
    And it prints "ENGINE_MAX_COST_USD is set too, and ignored: TRAILHOUND_MAX_COST_USD (2.5) counts, not ENGINE_MAX_COST_USD (0.5)."
    But when both hold the same value, it prints nothing

  Scenario: A stop names the variable the limit came from
    Given ENGINE_MAX_MODEL_CALLS is "1" and TRAILHOUND_MAX_MODEL_CALLS isn't set
    When the run has made 1 model call
    Then it stops with "Stopped by the spending limit: 1 model calls made, the limit is 1 (ENGINE_MAX_MODEL_CALLS)."

  Scenario: An error names the variable that was set
    Given ENGINE_MAX_COST_USD is "0" and TRAILHOUND_MAX_COST_USD isn't set
    When a run starts
    Then it stops before any call: "ENGINE_MAX_COST_USD must be above 0; the limit can be raised, not switched off."
