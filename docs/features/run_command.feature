# The run command: python -m engine.cli --adapter <name> [options].
#
# The CLI is generic wiring only: it fixes the console encoding, reads the flags,
# loads the adapter from the registry, builds a RunConfig and calls
# engine.runner.run(). Settings are layered: the engine's fallback, then the
# adapter's suggested defaults, then the flags. RunConfig refuses a value below 1,
# because max_checkpoints 0 would leave the run with no checkpoints and crash on
# checkpoints[-1] instead of failing with a clear message.
#
# Model text can hold characters the default Windows console codec can't encode,
# which crashed a plain print(), so stdout is switched to UTF-8 first.
#
# Code: engine/cli.py, engine/config.py

Feature: One command runs a session against an adapter
  As someone exploring a system
  I want one command with a few flags and sensible defaults
  So that starting a run is quick and its settings fit the SUT

  Scenario Outline: Each flag sets one run setting
    When I run "python -m engine.cli --adapter complex_sut <flag> <value>"
    Then the run's "<setting>" is <value>

    Examples:
      | flag                 | value                   | setting                 |
      | --model              | claude-opus-5           | model                   |
      | --max-checkpoints    | 3                       | max_checkpoints         |
      | --first-round-budget | 10                      | first_round_test_budget |
      | --default-budget     | 6                       | default_test_budget     |
      | --out-dir            | runs/try1/complex_sut_1 | out_dir                 |

  Scenario: The adapter must be one that is registered
    When I run "python -m engine.cli --adapter nosuch"
    Then argparse refuses it, listing the choices "clash_royale", "complex_sut", "token_purchase" and "web_gui"
    And running with no "--adapter" at all is refused too

  Scenario: Unset flags fall back to the adapter's suggested defaults
    # complex_sut suggests 4 checkpoints, a first-round budget of 10 and a default budget of 6.
    When I run "python -m engine.cli --adapter complex_sut --default-budget 8"
    Then max_checkpoints is 4, first_round_test_budget is 10 and default_test_budget is 8
    And the model is the provider's default model
    And max_attempts is 3
    And out_dir is "runs/complex_sut"

  Scenario: The engine's own fallbacks apply when no adapter suggests anything
    When a RunConfig is created directly with no arguments
    Then max_checkpoints is 4, first_round_test_budget is 12, default_test_budget is 8 and max_attempts is 3
    And out_dir is "runs/default"

  Scenario Outline: A value below 1 is refused before the run starts
    When a RunConfig is created with <field> <value>
    Then it raises ValueError "RunConfig.<field> must be >= 1, got <value>"

    Examples:
      | field                   | value |
      | max_checkpoints         | 0     |
      | max_attempts            | -1    |
      | first_round_test_budget | 0     |
      | default_test_budget     | -2    |

  Scenario: A 0 on the command line means "not given"
    # for_adapter uses "flag or adapter default", so 0 never reaches the value check.
    When I run "python -m engine.cli --adapter complex_sut --max-checkpoints 0"
    Then max_checkpoints is 4, the complex_sut default

  Scenario: The console prints model text as UTF-8
    Given model reasoning that contains characters the Windows console codec can't encode
    When the run prints it
    Then stdout writes it as UTF-8, replacing anything it still can't encode, and the run goes on
