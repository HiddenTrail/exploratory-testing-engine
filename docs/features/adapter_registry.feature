# The adapter registry: a name-to-module map, loaded lazily, edited by a person.
#
# trailhound/ code never imports from trailhound/adapters/. The registry is the one place
# that crosses over, and it does so at run time through importlib, not at import
# time. Loading an adapter starts nothing: the game client's window and the web
# browser are only attached to or launched by check_sut_ready, which is also where
# their safety checks run.
#
# Adding an adapter means a person adds a line to the map. The bootstrap pipeline
# prints that line for a generated adapter and never registers or runs one by
# itself, so nothing half-finished runs by accident.
#
# Code: trailhound/adapters/registry.py, trailhound/cli.py

Feature: Adapters are registered by a person and loaded by name, lazily
  As someone responsible for what runs against a SUT
  I want adapters loaded by name from a list a person keeps
  So that no generated or half-finished adapter runs by accident

  Scenario: The registry lists the adapters a person has added
    When the engine lists the available adapters
    Then it gets "clash_royale", "complex_sut", "token_purchase" and "web_gui", sorted by name
    And the CLI offers exactly those as choices for "--adapter"

  Scenario: An adapter is imported only when it is loaded
    Given the engine has started and no adapter module is imported yet
    When the engine loads "complex_sut"
    Then it imports "trailhound.adapters.complex_sut.adapter" with importlib
    And returns that module's ADAPTER

  Scenario: Loading an adapter starts nothing
    # Safe for the live game client and the browser: they are only attached to or
    # launched by check_sut_ready when a run begins.
    When the engine loads "web_gui"
    Then no browser is launched until the run calls check_sut_ready

  Scenario: An unknown name is refused with the list of known ones
    When the engine loads "nosuch"
    Then it exits with "Unknown adapter 'nosuch'. Available: clash_royale, complex_sut, token_purchase, web_gui"

  Scenario: A generated adapter is not registered by the code
    Given the bootstrap pipeline has drafted a new adapter
    Then the pipeline prints the line to add to registry.py
    And the new adapter is not in the available adapters until a person adds that line
