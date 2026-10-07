# web_gui readiness: check the carried map and the live app before any model call.
#
# The web_gui adapter tests a live web app through a map an earlier read-only recon
# made (a web-recon ontology.json, or one converted from a Spoor map). check_ready
# loads that map, launches Chromium once, and reboots to the start page, all before
# an API call is spent. A run against an app that isn't there, or a map that isn't a
# web-recon map, stops with SystemExit and a message saying what to fix. A start page
# that doesn't match the map only warns: the app may have changed since the recon,
# and the run can still be useful, but every known/new reading is relative to the map.
# What check_ready finds is written into the Driver's onboarding evidence.
#
# Code: trailhound/adapters/web_gui/session.py (check_ready, _resolve_ontology_path,
# Session.baseline), trailhound/adapters/web_gui/adapter.py (fetch_happy_day_example)

Feature: The web_gui adapter checks its map and the live app before a run starts
  As someone about to spend money on a web run
  I want a missing map, a foreign map, an empty action space or an unreachable app to stop the run up front
  So that no model call is made against a run that can't work

  Scenario Outline: A run without a usable map or app stops with a message saying what to fix
    Given <setup>
    When check_ready runs
    Then the run stops with SystemExit saying "<message>"

    Examples:
      | setup                                                         | message                                                     |
      | WEB_GUI_ONTOLOGY is unset                                     | The web-GUI adapter needs a carried reference               |
      | WEB_GUI_ONTOLOGY points at a file that does not exist         | which does not exist                                        |
      | the map's "schema" does not start with "web-recon"            | does not look like a web-recon ontology                     |
      | the map has no target.url and WEB_GUI_URL is unset            | No base URL                                                 |
      | the map has no safe (state, control) pairs                    | The carried reference has no safe (state, control) pairs    |
      | the browser can't load the base URL                           | Could not reach the SUT at                                  |

  Scenario: The base URL comes from WEB_GUI_URL, else from the map
    Given a map whose target.url is "http://127.0.0.1:3000"
    And WEB_GUI_URL is set to "http://localhost:5173"
    When check_ready runs
    Then the browser opens "http://localhost:5173"

  Scenario Outline: WEB_GUI_HEADED decides whether Chromium is visible
    Given WEB_GUI_HEADED is "<value>"
    When check_ready launches the browser
    Then Chromium runs <mode>

    Examples:
      | value | mode                                    |
      |       | headless                                |
      | 0     | headless                                |
      | false | headless                                |
      | 1     | headed, with 300 ms between its actions |

  Scenario: A start page that matches the map is confirmed
    Given the map's entry state is "st01"
    And the live start page has the same signature as "st01"
    When check_ready runs
    Then the onboarding "baseline" reads "Start state st01 confirmed" with the first 50 characters of the signature
    And the report shows "Where the run started" with the badge "confirmed"

  Scenario: A start page that drifted from the map warns and the run goes on
    # Not fatal on purpose: the app may have changed since the recon.
    Given the live start page has a different signature from the map's entry state
    When check_ready runs
    Then a line starting "WARNING: the SUT's entry state does not match the carried map" is printed
    And the same warning is the onboarding "baseline"
    And the report shows "Where the run started" with the badge "drifted"
    And the run is not stopped

  Scenario: What check_ready found goes into the Driver's onboarding evidence
    When check_ready has run
    Then the onboarding evidence has "carried_map" with the map's Driver briefing
    And it has "baseline" with the start-page confirmation or warning
    And it has "safety_note", saying the run is read-only
    And it has "oracle_ranked" unless WEB_GUI_ORACLE is "off"

  Scenario: A web run has no happy-day example
    # Since #285: one click on the start page told the Driver nothing, and cost a test and
    # evidence tokens on every call. check_ready already proves the machinery.
    When the loop asks for the happy-day example
    Then its request and response are empty, and nothing is acted on
    And the Driver's evidence and the report leave it out

  Scenario: The Driver gets the names of the product's parts
    When check_ready runs
    Then the onboarding evidence has "product_areas": the wiki's screen titles when WEB_GUI_PRODUCT has a wiki, then every screen of the map by route, e.g. "start page", "basket", "privacy security / privacy policy"
    And with earlier discoveries, "earlier_discovery_routes" maps each screen id to its route, which the report shows next to the id
