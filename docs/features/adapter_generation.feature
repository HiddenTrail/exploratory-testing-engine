# Adapter generation: turn a probing result into a runnable adapter.py.
#
# Phase 4 of the adapter bootstrap. It writes Python source for a SUTAdapter that
# the checkpoint loop can run with no hand-written code. Only the simple pattern is
# generated: one request in, one response out, and the prediction is the HTTP status
# family. Concurrency or aggregation logic like complex_sut's stays hand-written.
#
# The file is a draft for a person to read. An inconclusive result still gets a file,
# with a warning banner at the top. A result with no working example gets none,
# because there is nothing real to build around. Text from the model or the user
# (the notes, field descriptions, background context) goes in as comments or string literals, so it can't
# become code.
#
# Code: trailhound/bootstrap/generate.py
# Example output: docs/examples/bootstrap_demo/generated_adapter.py

Feature: A probing result is turned into a draft adapter
  As an engineer adding a new HTTP API
  I want a runnable adapter.py written from what probing confirmed
  So that I can run the checkpoint loop against the API straight away, after reading the draft

  Scenario: The generated adapter holds what probing found
    Given a bootstrap result with status "confirmed" for "POST /purchase" at "http://127.0.0.1:8020"
    When the adapter source is generated
    Then it sets BASE_URL, TEST_ENDPOINT_PATH "/purchase" and HTTP_METHOD "POST"
    And API_SCHEMA_DOC lists every request field with its type, whether it is required, its enum and its description
    And HAPPY_DAY_REQUEST is the body of the first successful probe
    And CASTING_TOOL has one property per discovered field, and lists the required ones as required
    And every cast test also needs "linked_hypothesis", "predicted_outcome" and "predicted_status_family"
    And it defines execute_test, casting_system_prompt, validate_casting_response, render_test_entry and render_onboarding_section
    And the module's ADAPTER passes validate_adapter()

  Scenario Outline: A test's prediction is checked against the status family
    Given a generated adapter
    And a cast test predicting "<predicted>"
    When execute_test sends it and the API answers <status>
    Then actual_status_family is "<actual>"
    And prediction_matched is <matched>

    Examples:
      | predicted | status | actual | matched |
      | 2xx       | 200    | 2xx    | true    |
      | 4xx       | 422    | 4xx    | true    |
      | 2xx       | 500    | 5xx    | false   |

  Scenario: Only discovered fields go into the request body
    Given a generated adapter whose discovered fields include an optional field missing from the happy-day example
    When a cast test sets that optional field and also "linked_hypothesis" and "predicted_outcome"
    Then the request body holds the optional field
    And it doesn't hold "linked_hypothesis", "predicted_outcome" or "predicted_status_family"

  Scenario: The generated validator checks required fields, types and enums
    Given a generated adapter
    When the Driver casts a test that misses a required field, gives a string for an integer field or a value outside an enum
    Then validate_casting_response returns an error for each problem
    And "predicted_status_family" must be one of "2xx", "4xx" or "5xx"

  Scenario: An inconclusive result gets a DRAFT banner with the remaining gaps
    Given a bootstrap result with status "inconclusive"
    When the adapter source is generated
    Then the file has the banner "DRAFT, NOT FULLY CONFIRMED" right after its docstring
    And the banner holds the last review's notes, each line as a "# " comment
    And the docstring gives the bootstrap status as "inconclusive"

  Scenario Outline: Some results can't be turned into an adapter
    Given a bootstrap result where <problem>
    When the adapter source is generated
    Then it raises a ValueError and no source is produced

    Examples:
      | problem                              |
      | the status is "failed"               |
      | there is no happy-day example        |
      | the schema has no endpoints          |

  Scenario Outline: The adapter is only written inside trailhound/adapters/
    When write_adapter_module is asked to write the adapter named "<name>"
    Then <result>

    Examples:
      | name     | result                                                                |
      | my_api   | it writes "my_api/adapter.py" and an empty "my_api/__init__.py"       |
      | ../evil  | it raises a ValueError and writes nothing                             |
      | a/b      | it raises a ValueError and writes nothing                             |
