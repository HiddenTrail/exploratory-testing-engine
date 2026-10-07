# Adapter bootstrap: point a command at a live HTTP API and get a draft adapter.
#
# Writing a SUTAdapter by hand is the cost of testing a new API. The bootstrap
# chains four phases: OpenAPI/Swagger discovery, a free-text fallback, live
# probing, and writing the adapter file. It covers one endpoint with one request in
# and one response out. Anything like complex_sut's bursts stays hand-written.
# The CLI prints three steps because the free-text fallback runs inside step 1.
#
# The output is a draft for a person to review. The CLI never edits
# trailhound/adapters/registry.py: registering a generated adapter is the last human
# gate before it runs.
#
# Code: trailhound/bootstrap/cli.py, trailhound/bootstrap/schema.py.
# Worked example: docs/examples/bootstrap_demo/

Feature: A draft adapter is bootstrapped from a live HTTP API
  As an engineer adding a new HTTP API to test
  I want one command to discover, probe and write a runnable adapter.py
  So that I can start testing without writing an adapter by hand

  Scenario: A full run goes through the phases and writes the adapter
    Given a live API at "http://127.0.0.1:8020" that publishes "/openapi.json"
    And probing gets at least one successful response from it
    When I run "python -m trailhound.bootstrap.cli --name my_api --display-name \"My API\" --base-url http://127.0.0.1:8020"
    Then it prints "[1/3] Discovering schema at http://127.0.0.1:8020 ..."
    And it prints "[2/3] Probing live SUT to confirm the schema (up to 8 probes) ..."
    And it prints "[3/3] Generating draft adapter ..."
    And it writes "trailhound/adapters/my_api/adapter.py" and an empty "trailhound/adapters/my_api/__init__.py"

  Scenario: The bootstrap prints the registry line and run command, and registers nothing
    Given a bootstrap run for "--name my_api" that ended "confirmed"
    When the adapter has been written
    Then it prints the line "\"my_api\": \"trailhound.adapters.my_api.adapter\"," to add to the _ADAPTERS dict in registry.py
    And it prints the run command "python -m trailhound.cli --adapter my_api"
    And "trailhound/adapters/registry.py" is unchanged
    And the generated adapter is not run

  Scenario: An inconclusive run says to read the warning first
    Given a bootstrap run whose probing ended "inconclusive"
    When the adapter has been written
    Then it prints "NOTE: bootstrap was inconclusive - review the warning comment at the top of the file before trusting it."

  Scenario Outline: Bad arguments stop the CLI before any model call
    When I run the bootstrap CLI with <arguments>
    Then it exits with a message containing "<message>"
    And no model client is built

    Examples:
      | arguments                                              | message                                                    |
      | --name "class"                                         | --name must be a valid Python identifier (not a keyword)   |
      | --name "my-api"                                        | --name must be a valid Python identifier (not a keyword)   |
      | no --display-name and no --discover-only               | --display-name is required unless --discover-only is set   |
      | --context-source jira --context-file notes.txt         | --context-file cannot be used with --context-source jira   |
      | --context-source jira and no --ticket                  | --ticket is required when --context-source jira            |
      | --ticket PROJ-101 with the default --context-source    | --ticket can only be used with --context-source jira       |
      | --context-file missing.txt that doesn't exist          | --context-file not found: missing.txt                      |
      | --context-source jira --ticket PROJ-999                | Unknown mock ticket 'PROJ-999'                             |

  Scenario: Nothing to probe stops the run after step 1
    Given every discovery path on the API answers 404
    And no "--spec-text" was given
    When I run the bootstrap CLI
    Then it exits with "No usable schema found or drafted (status: not_found). Nothing to probe - try passing --spec-text, or check the base URL."
    And no probe is sent

  Scenario: A probe loop with no success writes no adapter
    Given probing ends with status "failed"
    When the CLI reaches step 3
    Then it exits with "Bootstrap probing never got a working example - nothing real to generate an adapter around."
    And the message includes the reasoning from the last review, or "(none recorded)"
    And no adapter file is written
