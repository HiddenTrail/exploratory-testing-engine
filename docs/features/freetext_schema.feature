# Free-text schema: draft a schema from a written description when nothing is published.
#
# Phase 2 of the adapter bootstrap. Some APIs publish no OpenAPI document. Then one
# tool-forced model call reads the text given with --spec-text and proposes a draft
# schema for one endpoint. The draft is marked unconfirmed, because the model hasn't
# seen the real system answer anything. Probing (Phase 3) is what checks it.
#
# The model is told not to invent fields the text gives no basis for, and to say in
# confidence_notes what it had to guess. --spec-text is separate from
# --context-file: it is only ever read when discovery finds nothing.
#
# Code: trailhound/bootstrap/freetext.py, trailhound/bootstrap/schema.py

Feature: A schema is drafted from free text when discovery finds nothing
  As an engineer adding an API that publishes no OpenAPI document
  I want --spec-text to let a model draft the schema, marked as unconfirmed
  So that bootstrapping still works from a written description, and nobody mistakes the draft for fact

  Scenario: Discovery that finds a schema never calls the model
    Given discovery returns status "found"
    And "--spec-text" was given
    When the bootstrap gets its schema
    Then the discovered schema is used
    And no model call is made for it

  Scenario Outline: The model is only asked when discovery found nothing and there is text
    Given discovery returns status "<status>"
    And the spec text is <spec_text>
    When the bootstrap gets its schema
    Then <result>

    Examples:
      | status      | spec_text       | result                                            |
      | not_found   | a description   | one "submit_schema_draft" call drafts the schema  |
      | unreachable | a description   | one "submit_schema_draft" call drafts the schema  |
      | malformed   | a description   | one "submit_schema_draft" call drafts the schema  |
      | not_found   | not given       | the discovery result is returned as it is         |
      | not_found   | an empty string | the discovery result is returned as it is         |

  Scenario: The draft is marked unconfirmed and carries the model's own doubts
    Given discovery found nothing and the spec text describes "POST /submit"
    When the model answers "submit_schema_draft"
    Then the schema has source "freetext" and confirmed false
    And it has status "found", no fetched_from, and exactly one endpoint
    And its notes are the model's "confidence_notes"
    And a field whose "enum" came back as an empty list has no enum

  Scenario: An answer in the wrong shape is sent back to the model
    Given the model's draft has method "FETCH", or a field with type "text", or a field missing "required"
    When the draft is checked
    Then the errors are sent back and the model is asked again, up to the usual retry limit
