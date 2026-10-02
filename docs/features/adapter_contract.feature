# The adapter contract: everything per-SUT the generic engine needs supplied.
#
# A SUTAdapter is a frozen dataclass, built once at import time as the module's
# ADAPTER and only read during a run. It supplies the casting tool schema, the
# casting prompt and validator, execute_test, and how to draw a test and the
# onboarding section in the report. The hypothesis, Skeptic and bug report schemas
# are not part of it: they live in engine/tools.py and are the same for every SUT.
#
# Reaching the SUT can be done two ways, and an adapter must pick one wholly: HTTP
# fields for a web service, or both reach hooks for anything else. Supplying only
# one hook is refused, because the other would fall back to HTTP and fail with a
# confusing connection error just as the run seemed to have started.
#
# Code: engine/adapter.py (SUTAdapter, validate_adapter), engine/loop.py

Feature: Any system can be tested through one SUTAdapter
  As an engineer adding a new SUT
  I want one adapter object that supplies only the per-SUT parts, checked before the run starts
  So that the engine stays the same for every system, and a broken adapter fails at once

  Scenario: An adapter missing a required field is refused before anything else
    Given an adapter "half_done" with no execute_test and no render_test_entry
    When a run starts
    Then validate_adapter raises "Adapter 'half_done' is missing required field(s): execute_test, render_test_entry"
    And no client is built and the SUT is not contacted

  Scenario Outline: Each required field must be set
    Given an adapter where "<field>" is None or ""
    When validate_adapter checks it
    Then it names "<field>" as missing

    Examples:
      | field                     |
      | name                      |
      | display_name              |
      | casting_tool_schema       |
      | casting_system_prompt     |
      | validate_casting_response |
      | execute_test              |
      | render_test_entry         |
      | render_onboarding_section |

  Scenario Outline: The SUT must be reachable one way, wholly
    Given an adapter with <http> and <hooks>
    When validate_adapter checks it
    Then it is <result>

    Examples:
      | http                                  | hooks                                       | result                                      |
      | base_url and test_endpoint_path       | neither reach hook                          | valid                                       |
      | no base_url                           | check_sut_ready and fetch_happy_day_example | valid                                       |
      | no base_url and no test_endpoint_path | neither reach hook                          | refused: "there is no way to reach its SUT" |
      | base_url and test_endpoint_path       | only check_sut_ready                        | refused: "Supply both or neither"           |
      | no base_url                           | only fetch_happy_day_example                | refused: "Supply both or neither"           |

  Scenario Outline: Optional hooks fall back to an engine default
    Given an adapter that leaves "<hook>" unset
    When the engine needs it
    Then it uses <fallback>

    Examples:
      | hook                     | fallback                                                 |
      | check_sut_ready          | the HTTP probe of base_url plus docs_path                |
      | fetch_happy_day_example  | one live POST of happy_day_request to test_endpoint_path |
      | redact_history_for_model | engine/redact.py's default redaction                     |
      | describe_test_for_log    | the test's fields without linked_hypothesis, as a string |
      | describe_result_for_log  | the result's response body, as a string                  |
      | report_title             | "<display_name> Investigation Report"                    |

  Scenario Outline: The casting reply's token limit grows with the test budget
    Given an adapter that keeps the default casting_max_tokens
    When the casting round has a test budget of <budget>
    Then the casting call's max_tokens is <tokens>

    Examples:
      | budget | tokens |
      | 6      | 4096   |
      | 8      | 4096   |
      | 10     | 6144   |

  Scenario: The hypothesis, Skeptic and bug report tools are shared and can't be overridden
    # What counts as a claim, a bug and a strong result has to be the same for every SUT.
    Given any registered adapter
    When the engine asks for a hypothesis, a Skeptic review or bug reports
    Then it uses "submit_checkpoint_hypothesis", "submit_skeptic_review" and "submit_bug_reports" from engine/tools.py
    And SUTAdapter has no field to replace them
    And only the casting call uses the adapter's own tool schema and prompt
