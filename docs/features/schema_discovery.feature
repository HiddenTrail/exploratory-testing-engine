# Schema discovery: read the API's own OpenAPI or Swagger document first.
#
# Most APIs built with common frameworks (FastAPI, Spring with springdoc, NestJS,
# Django with drf-spectacular) publish a machine-readable schema for free. Both mock
# SUTs here are FastAPI apps with one at /openapi.json. Discovery makes no model
# call, so it's free and gives the same answer every time.
#
# It hand-parses only the slice it needs: the JSON request body and the JSON 200
# response of each operation, with $ref resolved against components.schemas. No
# OpenAPI library is added for this. A catch-all 200 page (an SPA fallback) at one of
# the paths must not be read as a schema, so a document has to say what it is.
#
# Code: trailhound/bootstrap/discovery.py, trailhound/bootstrap/report.py,
# trailhound/bootstrap/cli.py (--discover-only)

Feature: The schema is read from the API's own OpenAPI document
  As an engineer adding a new HTTP API
  I want the bootstrap to fetch and parse the OpenAPI or Swagger document the API already publishes
  So that the schema is exact, and costs nothing, whenever the API has one

  Scenario: The usual paths are tried in order until one holds a schema
    Given an API where "/openapi.json" answers 404 and "/swagger.json" answers a valid document
    When discovery runs against it
    Then it tries "/openapi.json", "/swagger.json", "/v3/api-docs" and "/api/schema/" in that order
    And it stops at the first path that holds a schema document
    And the result has status "found" and fetched_from "/swagger.json"

  Scenario Outline: A response only counts as a schema document if it says it is one
    Given an API whose only answer at the candidate paths is <response>
    When discovery runs against it
    Then that response is skipped and the next path is tried

    Examples:
      | response                                               |
      | a 404                                                  |
      | a 200 that isn't JSON                                  |
      | a 200 with a JSON list                                 |
      | a 200 with a JSON object with no "openapi" or "swagger" key |

  Scenario Outline: Discovery tells apart why it found nothing
    Given an API where <situation>
    When discovery runs against it
    Then the result has status "<status>"
    And it has no endpoints

    Examples:
      | situation                                                           | status      |
      | every path answers, but none holds a schema document                | not_found   |
      | every path fails at the connection level                            | unreachable |
      | a document has an "openapi" key but no "paths"                      | malformed   |
      | a document's paths hold no get, post, put, patch, delete, options or head operation | malformed |
      | a $ref points at a schema that isn't in components.schemas          | malformed   |
      | a $ref points anywhere other than "#/components/schemas/"           | malformed   |

  Scenario: $ref is resolved, and a reference cycle is cut off
    Given a request body that refers to "#/components/schemas/PurchaseRequest"
    And a schema in components.schemas that refers back to itself
    When discovery parses the document
    Then the request fields come from "PurchaseRequest"
    And $ref is followed inside "properties", "items", "anyOf", "oneOf" and "allOf"
    And the self-reference is replaced by an empty schema, so discovery doesn't hang and the result is still "found"

  Scenario: Each field gets its name, type, requiredness, enum, default and description
    # Optional[X] in FastAPI comes out as anyOf [X, null], and JSON Schema 2020-12 can
    # write ["string", "null"]. Both give the non-null type.
    Given the token_purchase mock SUT's real "/openapi.json"
    When discovery parses it
    Then "POST /purchase" has the required fields "auth_token", "card_number", "expiry_month", "expiry_year", "cvv" and "credit_count"
    And "expiry_month" has type "integer"
    And a field typed through anyOf with null, or a type list with "null", gets the non-null type
    And a field with no type it can read gets type "unknown"
    And a field with an "enum", directly or in an anyOf branch, lists its allowed values
    And complex_sut's "priority" is optional with a default of "normal"

  Scenario: --discover-only writes the result as JSON and HTML, with no model calls
    When I run "python -m trailhound.bootstrap.cli --name my_api --base-url http://127.0.0.1:8000 --discover-only"
    Then discovery runs and nothing else does
    And no model client is built
    And "--display-name" is not needed
    And it prints each endpoint with its fields, as "name: type - required" or "- optional"
    And it writes "runs/my_api/discovered_schema.json" and "runs/my_api/discovered_schema.html"
    And the HTML shows the status as a badge, the source, whether it is confirmed and the number of endpoints

  Scenario: --discover-only exits with an error when it found nothing
    Given an API with no schema document
    When I run the bootstrap CLI with "--discover-only"
    Then both files are still written
    And it exits with "No OpenAPI/Swagger schema found (status: not_found)"
