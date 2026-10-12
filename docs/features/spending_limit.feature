# A hard spending limit for every run: it stops the run, whatever else goes wrong.
#
# Checkpoints, test budgets and the retry limit already bound a run, but each is a
# number someone can set high by mistake, and a bug in the loop could call the model
# again and again. So before every model call, retries included, the engine checks what
# the run has spent, and stops at TRAILHOUND_MAX_MODEL_CALLS calls or about
# TRAILHOUND_MAX_COST_USD dollars. The cost is estimated at list prices for a
# Sonnet-class model ($3, $15, $3.75 and $0.30 per million input, output, cache-write
# and cache-read tokens). The check runs before a call, so the last call can go over by its own cost.
# Asked for with the CI pipeline (#255), and on for every run on every machine.
#
# The bootstrap pipeline calls the model too. Its calls always went through the guard,
# but until #419 it never started one from the environment, so it kept the default
# limits whatever TRAILHOUND_MAX_* said, and counted on from any calls made before it.
#
# Code: trailhound/budget.py, trailhound/settings.py, trailhound/client.py (call_tool_with_retry),
# trailhound/runner.py, trailhound/cli.py, trailhound/run_summary.py, trailhound/bootstrap/cli.py.
# Tests: trailhound/tests/test_budget.py, trailhound/tests/test_bootstrap_budget.py

Feature: A run stops itself at a spending limit
  As someone paying for model calls
  I want every run to stop at a fixed number of calls or an estimated cost
  So that no setting and no bug can make a run spend without end

  Scenario Outline: The limits come from the environment, with safe defaults
    Given TRAILHOUND_MAX_COST_USD is "<cost>" and TRAILHOUND_MAX_MODEL_CALLS is "<calls>"
    When a run starts
    Then <result>

    Examples:
      | cost | calls | result                                                                            |
      |      |       | it prints "Spending limit: about $3.00 or 80 model calls, whichever comes first." |
      | 1.50 | 40    | the limit is about $1.50 or 40 model calls                                        |
      | 0    |       | it stops before any call: "can be raised, not switched off"                       |
      | lots |       | it stops before any call: "isn't a number"                                        |

  Scenario: The call limit stops the run before the next call
    Given the limit is 3 model calls and 3 calls have been made
    When the engine is about to call the model again
    Then it raises BudgetExceeded with "3 model calls made, the limit is 3"
    And the model is not called

  Scenario: The cost limit stops the run once the estimate reaches it
    Given the limit is $0.50 and each call costs about $0.30
    Then the second call is still made, at about $0.30 spent
    And the third is stopped with "about $0.60 spent, the limit is $0.50"

  Scenario: A stopped run keeps what it has and says why
    When the spending limit stops a run
    Then output.json and report.html are still written
    And stopped_reason is "budget_exceeded" and "error" says which limit was hit
    And the run summary starts with "The spending limit stopped the run:"
    And the run command exits with code 2 and doesn't feed the run into the context, even with --learn

  Scenario: The bootstrap pipeline keeps the same limits (#419)
    Given TRAILHOUND_MAX_MODEL_CALLS is "1"
    When "python -m trailhound.bootstrap.cli --name my_api --display-name \"My API\" --base-url http://127.0.0.1:8020" runs
    Then it prints "Spending limit: about $3.00 or 1 model calls, whichever comes first." before its first model call
    And it stops before its second call with "Stopped by the spending limit: 1 model calls made" and "Nothing was generated."
    And calls made earlier in the same process don't count against it
