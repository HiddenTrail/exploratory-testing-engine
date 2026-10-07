# CI: the checks every change has to pass before it reaches master.
#
# Tests must give the same result every time and cost nothing, so no test calls a
# real model or needs an API key. That is a rule each test keeps by passing a stub
# client; there is no shared guard that blocks a real call. SUTs are faked with
# httpx.MockTransport or FastAPI's TestClient, except the race test, which needs a
# real server.
#
# Parity tests load the prototypes in .experiments/ by file path and check the ports
# haven't drifted (moving to fixtures is #77). The race test starts real uvicorn,
# since an in-process client may not use a real thread pool. It used to fail now and
# then when each thread built its own client and the burst spread out (#136).
#
# Code: .github/workflows/tests.yml, .github/workflows/spoor-contract.yml,
# trailhound/tests/test_*_parity.py, trailhound/tests/test_*sut_regression.py

Feature: CI checks Trailhound on every pull request
  As someone maintaining Trailhound
  I want every change compile-checked and tested without real model calls
  So that changes reach master only when they pass, for free and the same way every time

  Scenario: Tests stub the model and never need a key
    Given a test that exercises code which calls the model
    When the test runs
    Then it passes a fake client that answers from a fixed list of tool calls
    And no API key is needed and no request goes to a real model

  Scenario: The tests workflow runs on pushes and pull requests to master
    When a pull request to "master" is opened or a commit is pushed to "master"
    Then the "Trailhound tests" workflow runs on "ubuntu-latest" with Python "3.13"
    And it installs "trailhound/requirements.txt"
    And it runs "python -m compileall -q trailhound"
    And it runs "python -m pytest trailhound/tests -v"
    And it runs "python -m pytest clash-royale-kit -v"
    And it installs ".experiments/web-recon/requirements.txt" and runs "python -m pytest tests -v" in ".experiments/web-recon"
    # .experiments/game-ontology and .experiments/android-bot are Windows-only and stay out of CI.

  Scenario Outline: Parity tests keep the ports equal to their prototypes
    When "<test>" runs
    Then it loads "<prototype>" by file path
    And it checks the casting tool schema, the first-round casting prompt and the validator against the port
    And the only differences allowed are the ones the test names as deliberate

    Examples:
      | test                                    | prototype                                    |
      | trailhound/tests/test_tools_parity.py       | .experiments/token-purchase-poc/run_live.py  |
      | trailhound/tests/test_complex_sut_parity.py | .experiments/complex-sut-poc/run_live.py     |

  Scenario: The token_purchase regression tests pin the order of its checks
    When "trailhound/tests/test_sut_regression.py" runs against the mock SUT through TestClient
    Then a card number "1234567890" is declined "card_not_authorized", never "invalid_card_number"
    And a past but mismatched expiry is declined "expiry_mismatch", never "expired_card"

  Scenario: The race test runs against a real uvicorn server
    Given "trailhound/tests/test_complex_sut_regression.py" starts "trailhound.adapters.complex_sut.sut:app" with uvicorn on port 8791
    And it waits up to 10 seconds for "/docs" to answer
    When it sends 8 requests one after another for a fresh client_id
    Then exactly 5 are accepted
    When it sends 20 requests at once for another fresh client_id, from a client built beforehand and released by a barrier
    Then more than 5 are accepted

  Scenario: The Spoor contract job runs when its side of the contract changes
    When a change touches "trailhound/requirements-spoor.txt", "from_spoor.py", the contract test or its fixture site
    Then the "spoor contract" workflow installs the pinned Spoor and Chromium
    And it runs "trailhound/tests/test_spoor_contract.py" with "REQUIRE_SPOOR" set to "1"
    And once a week on Monday it runs the same against Spoor's latest main instead
