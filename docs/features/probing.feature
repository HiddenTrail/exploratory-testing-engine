# Probing: confirm or correct a draft schema by sending real requests to the live API.
#
# Phase 3 of the adapter bootstrap. A schema from discovery, or a free-text draft,
# says what the API should take. Probing finds out what it does take, and finds at
# least one real working request. Real error responses are the richest signal: a 422
# that names a missing field settles an unknown faster than a success would.
#
# Each round is two model calls: one proposes a probe, one reviews everything so far
# and decides whether to stop. They are one judgment from one voice, so there is no
# third call. A "confident" review is overruled in code when no probe has succeeded,
# because that is a fact code can check. Only the first endpoint of the schema is
# probed.
#
# Code: engine/bootstrap/probe.py, engine/http.py (call_sut_once)

Feature: The draft schema is checked by probing the live API
  As an engineer adding a new HTTP API
  I want real requests sent and their real responses used to confirm or correct the draft
  So that the generated adapter matches how the API actually behaves

  Background:
    Given a schema whose first endpoint is "POST /purchase"
    And a live API at the base URL

  Scenario: Each round proposes one probe, sends it for real, then reviews
    When a probing round runs
    Then the model is called once with the tool "submit_probe_request"
    And it gets the current schema fields, every probe so far and the previous review, if there is one
    And the proposed method, path and body are sent to the live API as a real request
    And the probe log gets the request, the real response and the probe's reasoning
    And the model is called once more with the tool "submit_schema_review" and every probe so far
    And the review's "updated_fields" become the schema fields for the next round

  Scenario: Error messages in real responses steer the next probe
    # The probe prompt says to follow up on an error message not yet acted on before
    # moving to something else. Sending the full responses is what makes that possible.
    Given an earlier probe got a 422 naming a missing field
    When the next probe is proposed
    Then the model sees that 422 response in full in "probes_so_far"
    And its instructions tell it to follow up on that error first

  Scenario: The first success becomes the happy-day example
    # A success is any status below 300, including a 200 whose body says "declined".
    Given probe 1 got a 422, probe 2 got a 200 and probe 3 got a 200
    When probing ends
    Then the happy-day example is probe 2's request and response

  Scenario: A confident review is overruled while nothing has succeeded
    Given no probe so far got a status below 300
    When the review answers verdict "confident_enough"
    Then the verdict is treated as "needs_more_probing"
    And probing goes on to the next round

  Scenario Outline: How probing ends decides the bootstrap status
    Given <how_it_went>
    When probing ends
    Then the bootstrap status is "<status>"
    And the schema is marked confirmed <confirmed>
    And the notes are <notes>

    Examples:
      | how_it_went                                                          | status       | confirmed | notes                               |
      | a probe succeeded and a review then said "confident_enough"          | confirmed    | true      | that review's reasoning             |
      | a probe succeeded but the probes ran out with no confident review    | inconclusive | false     | the last review's reasoning         |
      | the model set "give_up" after a success, before any confident review | inconclusive | false     | the last review's reasoning         |
      | the probes ran out and no probe ever succeeded                       | failed       | false     | the last review's reasoning         |
      | the model set "give_up" on the very first probe                      | failed       | false     | empty, and no request was ever sent |

  Scenario: --max-probes caps the rounds
    When I run the bootstrap CLI with "--max-probes 3"
    Then at most 3 probes are sent to the live API
    And without the flag the cap is 8

  Scenario: A review must name what is still unconfirmed
    Given a review answer with only 1 gap or only 1 recommended next probe
    When the review is checked
    Then it is sent back to the model, because "gaps" and "recommended_next_probes" need at least 2 entries each
    And this holds even when the verdict is "confident_enough"
