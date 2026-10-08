# The Spoor contract: a change in Spoor's saved map can't break from_spoor unnoticed.
#
# Spoor (HiddenTrail/ht-spoor) is an optional dependency: the engine runs without it.
# trailhound/requirements-spoor.txt pins it to one commit (issue #144), so moving the pin
# is a deliberate PR. The "spoor contract" CI job runs a real Spoor at that commit on a
# tiny static site and checks its saved map with from_spoor's map_errors, the same
# check the converter runs on a real map. A weekly run does the same against Spoor's
# latest main, to warn before the pin is moved, without blocking anyone. The test
# talks to Spoor only through its CLI and the saved map, never its Python modules.
# Once Spoor tags releases (HiddenTrail/ht-spoor#171), a release gets pinned instead.
#
# It also covers mapping from a saved session (issue #156): the fixture site shows an
# account link only when localStorage holds contract_session=1, so a session file is
# the only way to reach the account page. Spoor maps from it, and from_spoor converts
# that map by replaying it from the same session.
#
# Code: trailhound/requirements-spoor.txt, .github/workflows/spoor-contract.yml,
# trailhound/tests/test_spoor_contract.py, trailhound/tests/fixtures/spoor_contract_site/,
# trailhound/adapters/web_gui/from_spoor.py (map_errors)

Feature: CI checks Spoor's saved map against what from_spoor reads
  As someone who depends on Spoor's map format
  I want a real, pinned Spoor run in CI and its map checked against the converter's contract
  So that a format change in Spoor shows up as a clear failure instead of a KeyError on the next real map

  Scenario Outline: The contract job runs on the pinned Spoor, or weekly on Spoor's latest main
    When the "spoor contract" workflow runs because of <trigger>
    Then it installs Spoor from <source>
    And it installs Chromium with "python -m playwright install --with-deps chromium"
    And it runs "python -m pytest trailhound/tests/test_spoor_contract.py -v" with REQUIRE_SPOOR set to "1"

    Examples:
      | trigger                                   | source                                                        |
      | a pull request to master                  | trailhound/requirements-spoor.txt (the pinned commit)             |
      | a push to master                          | trailhound/requirements-spoor.txt (the pinned commit)             |
      | a manual workflow_dispatch                | trailhound/requirements-spoor.txt (the pinned commit)             |
      | the weekly schedule, Mondays at 05:00 UTC | "ht-spoor @ git+https://github.com/HiddenTrail/ht-spoor@main" |

  Scenario: A pull request or push only triggers the job when our side of the contract changes
    Given a pull request to master
    When it changes none of trailhound/requirements-spoor.txt, trailhound/adapters/web_gui/from_spoor.py, trailhound/tests/test_spoor_contract.py, trailhound/tests/fixtures/spoor_contract_site/ or .github/workflows/spoor-contract.yml
    Then the "spoor contract" workflow does not run

  Scenario: The test explores a tiny static site with a capped Spoor run
    Given the fixture site trailhound/tests/fixtures/spoor_contract_site served on a free port on 127.0.0.1
    When the test runs "spoor explore <site url> --max-states 6 --max-seconds 120" in a temporary folder
    Then Spoor exits with code 0
    And exactly one saved map is written: a JSON file under ".spoor-cache/maps/" (older Spoor) or ".spoor-cache/spoor.db" (current Spoor, #385)

  Scenario: The saved map must be in the format from_spoor reads
    Given Spoor's saved map from the fixture site
    Then it has an entry keyed by the site URL, with or without a trailing slash
    And that entry's "exploration" is an object
    And map_errors finds nothing wrong with it
    And it has at least 2 states and at least one transition between different states
    # If this drops to one state, the format may be fine but the check is no longer
    # testing anything.

  Scenario: A saved session reaches a page a logged-out map can't
    Given a session file in our format whose localStorage for the site holds "contract_session" = "1", and which also carries a "sessionStorage" entry
    When the test runs "spoor explore <site url> --session <file>" in a folder of its own, so the logged-out map isn't overwritten
    Then the session map has the action "Your account" and more states than the logged-out map
    And the logged-out map has no "Your account" action
    And map_errors finds nothing wrong with the session map

  Scenario: from_spoor converts a session map and records the session
    Given Spoor's map made with the session file "logged-in.json"
    When "python -m trailhound.adapters.web_gui.from_spoor --map <map> --url <site url> --session <file> --out <file>" runs
    Then it exits with code 0
    And the converted map has a state whose URL ends with "/account.html", so the replay from the session reached it too
    And the converted map's "session"."session_name" is "logged-in"

  Scenario Outline: The test is skipped only when Spoor is missing and not required
    Given Spoor's CLI is <cli>
    And REQUIRE_SPOOR is <required>
    When the contract test runs
    Then it <result>

    Examples:
      | cli                                                      | required | result                                                                        |
      | not on PATH and SPOOR_CLI is unset                       | unset    | is skipped: "Spoor's CLI isn't installed (see trailhound/requirements-spoor.txt)" |
      | not on PATH and SPOOR_CLI is unset                       | "1"      | fails: "REQUIRE_SPOOR is set but Spoor's CLI isn't on PATH or in SPOOR_CLI"   |
      | on PATH                                                  | unset    | runs against that Spoor                                                       |
      | named by SPOOR_CLI, e.g. ../ht-spoor/.venv/Scripts/spoor | unset    | runs against that Spoor                                                       |
