# Test targets: real web apps to point the engine at, on fixed local ports.
#
# The mock SUTs are small APIs. Web testing needs real apps, run locally so nobody's
# environment gets touched. Between them the three targets cover what a browser
# adapter has to deal with: Juice Shop is an Angular single-page app, Sauce Demo is a
# single-page app behind a login, and PrestaShop is a server-rendered shop with real
# URLs, forms, cart and checkout. Versions are pinned so runs stay comparable.
#
# The file started as a copy of Spoor's fixtures/docker-compose.yml and uses the same
# host ports, so only one of the two sets can run at a time.
#
# Code: test-targets/docker-compose.yml, test-targets/sauce-demo/Dockerfile

Feature: Real web apps run locally as test targets
  As someone developing web testing
  I want Juice Shop, Sauce Demo and PrestaShop started from one compose file
  So that web runs use real apps on known ports without touching anyone's environment

  Scenario: One command starts every target
    When I run "docker compose -f test-targets/docker-compose.yml up -d"
    Then the services "juice-shop", "sauce-demo", "prestashop" and "prestashop-db" start

  Scenario Outline: Each target has a fixed host port
    When the targets are up
    Then <target> is served on host port <port>

    Examples:
      | target                                                      | port |
      | Juice Shop (image "bkimminich/juice-shop:v17.1.1")          | 3000 |
      | Sauce Demo, built from a pinned sample-app-web commit       | 3001 |
      | PrestaShop (image "prestashop/prestashop:8.1")              | 8080 |

  Scenario Outline: A taken port can be moved with an environment variable
    Given port <port> is already in use
    When I start the targets with "<variable>" set to another port
    Then <target> is served on that port instead
    And the container still serves on port 80

    Examples:
      | target     | port | variable        |
      | Sauce Demo | 3001 | SAUCE_DEMO_PORT |
      | PrestaShop | 8080 | PRESTASHOP_PORT |

  Scenario: PrestaShop waits for its database and keeps its install
    When the targets start for the first time
    Then PrestaShop starts only once the "mariadb:11" database passes its healthcheck
    And it installs itself into the database, which takes a few minutes the first time
    And the shop stays in the "ps-data" volume, so later starts are fast
    And its admin is at "/admin-dev"
    And the database has no port on the host

  Scenario: The test targets are labelled as safe to break
    When I look at the three targets in the compose file
    Then each has the label "qes.sandbox" set to "true"
    And "prestashop-db" doesn't have it, because it isn't a test target
    # Nothing reads the label yet. It marks which containers may have their data changed.

  Scenario: Juice Shop has no healthcheck
    # The image has no shell, curl or node on PATH, so a check inside it is fragile.
    When I want to know whether Juice Shop is ready
    Then I poll "http://127.0.0.1:3000" from outside the container
