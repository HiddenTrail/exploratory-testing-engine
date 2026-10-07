# Bootstrap context: what the API is for, fed into probing and into the adapter.
#
# Field names alone say little about realistic values. A short text on what the API
# does and how it's normally used lets probing try sensible values instead of guessing.
# The text is treated as a starting hypothesis: the prompts say a real response wins
# over anything the context implies, because descriptions can be wrong or stale.
#
# The source is pluggable. "file" reads a text file. "jira" reads a MOCKED ticket
# store with two fixed tickets, which shows the source can be swapped without
# touching probe.py or generate.py. A real JIRA client is not built yet (a TODO in
# jira_mock.py). This context is separate from --spec-text, which only feeds the
# free-text schema fallback.
#
# Code: trailhound/bootstrap/cli.py, trailhound/bootstrap/jira_mock.py,
# trailhound/bootstrap/probe.py, trailhound/bootstrap/generate.py

Feature: Background context feeds probing and the generated adapter
  As an engineer who knows what the API is for
  I want to hand the bootstrap a description of the API, from a file or a ticket
  So that probes use realistic values and later runs start from what I know

  Scenario: A context file is read with the default source
    Given a file "purchase_notes.txt" describing the API
    When I run the bootstrap CLI with "--context-file purchase_notes.txt"
    Then the context source is "file", the default for "--context-source"
    And the file's text, stripped of surrounding whitespace, is the API context

  Scenario Outline: A ticket from the mocked JIRA store is the context
    When I run the bootstrap CLI with "--context-source jira --ticket <ticket>"
    Then the API context is the ticket's summary, a blank line, then its description
    And the summary is "<summary>"

    Examples:
      | ticket   | summary                                                     |
      | PROJ-101 | Exploratory testing needed for the credits-purchase API     |
      | PROJ-102 | Rate-limiting concerns on the burst-submission endpoint     |

  Scenario: An unknown ticket names the tickets the mock knows
    When I run the bootstrap CLI with "--context-source jira --ticket PROJ-999"
    Then it exits with a message containing "Unknown mock ticket 'PROJ-999'. Known tickets: PROJ-101, PROJ-102"

  Scenario: The context goes into every probe proposal and never into the review
    Given an API context
    When probing runs for several rounds
    Then every "submit_probe_request" call has the context under "api_context" in its evidence
    And no "submit_schema_review" call has it
    And with no context the evidence has no "api_context" key at all

  Scenario: The context is baked into the generated adapter
    Given an API context
    When the adapter source is generated
    Then API_SCHEMA_DOC ends with "Background context (supplied at bootstrap time):" followed by the context
    And the casting prompt says background context is a starting hypothesis that real test results override
    And with no context API_SCHEMA_DOC has no background context section

  Scenario: Context that looks like code stays text
    Given an API context with triple quotes, braces, "{test_budget}" and a line "EVIL = 1"
    When the adapter source is generated and imported
    Then it imports and passes validate_adapter()
    And the module has no name "EVIL"
    And API_SCHEMA_DOC holds the context word for word, with "{test_budget}" left unfilled
