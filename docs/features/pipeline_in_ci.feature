# The whole pipeline in GitHub Actions, with no person at the keyboard (issue #255).
#
# Every step already ran from the command line, but a person had to type them in order,
# and one step needed a person: logging in. The exploratory-run workflow chains them on
# a throwaway Juice Shop started on the runner. A login recipe logs in from a config
# file. Spoor maps the site from that session, the map is converted, the engine runs
# with --learn, and the report goes up as an artifact with a summary on the run's page.
# It calls a model (about $0.60 a run), so it only runs when someone asks for it. The
# trigger rules (#172) and what a run tells the pipeline (#173) aren't decided yet, so
# a run with bugs doesn't fail the job.
#
# Code: .github/workflows/exploratory-run.yml, engine/adapters/web_gui/login_recipe.py,
# test-targets/login-recipes/juice-shop.json, engine/run_summary.py.
# Tests: engine/tests/test_login_recipe.py, engine/tests/test_run_summary.py

Feature: The whole pipeline runs in GitHub Actions and reports as an artifact
  As someone who wants to see the engine work end to end without typing six commands
  I want one GitHub workflow that logs in, maps, tests, learns and reports
  So that a run is one click, and its report is a download on the run's page

  Scenario Outline: The workflow only runs when someone asks for it
    When <event>
    Then the exploratory-run job <result>

    Examples:
      | event                                                      | result                                                          |
      | someone starts it from the Actions tab (workflow_dispatch) | runs, with the checkpoints, budgets, model and Spoor time given |
      | a pull request gets the label "run-exploration"            | runs with the defaults                                          |
      | a pull request gets any other label                        | is skipped                                                      |
      | someone pushes                                             | doesn't start                                                   |

  Scenario: Without the model key it stops before anything is installed
    Given the repository secret ANTHROPIC_API_KEY is unset, or the pull request is from a fork
    When the job starts
    Then it fails with "The repository secret ANTHROPIC_API_KEY isn't set"

  Scenario: One run at a time
    Given an exploratory run is in progress
    When another is started
    Then it waits for the first to finish, because both would learn from the same context

  Scenario: Each run starts from what the last successful run learned
    Given an earlier successful run uploaded the artifact "context-juice-shop"
    When a new run starts
    Then it downloads context_juice-shop.json into engine/ontology before the engine runs
    And without one it says "No earlier context; this run starts fresh."

  Scenario: The steps run in order on a throwaway Juice Shop
    Given Juice Shop v17.1.1 runs as a service on port 3000
    When the job runs
    Then it logs in with "python -m engine.adapters.web_gui.login_recipe --recipe test-targets/login-recipes/juice-shop.json"
    And it maps the site with "spoor explore" from that session, in its own folder
    And it converts the map with from_spoor from the same session, to runs/ci/map.json
    And it runs "python -m engine.cli --adapter web_gui" with WEB_GUI_SESSION_CHECK "/profile", WEB_GUI_PRODUCT "juice-shop" and "--learn juice-shop", logging to runs/ci/run.log

  Scenario: The report is an artifact and a summary, never the credentials
    When the job ends, whether the run succeeded or not
    Then runs/ci is uploaded as the artifact "exploratory-run" (report.html, output.json, bugs.json, run.log, map.json)
    And "python -m engine.run_summary" writes the summary on the run's page: counts, a table of observations worst first with their replay verdicts, model calls, retries and an estimated cost
    And .sessions and .spoor-cache are never uploaded
    And the context file is uploaded as "context-juice-shop" only when the job succeeded

  Scenario: A login recipe logs in with no person
    Given a recipe with credentials "generated:email" and "generated:password", steps, and "until": "storage:bid"
    When login_recipe runs it against "http://127.0.0.1:3000"
    Then the credentials are fresh for this run, and the steps get them as {email} and {password}
    And the steps run in order: requests, goto, click, click_if_present (skipped when missing) and fill
    And the session is saved to ".sessions/juice-shop/logged-in.json" once "until" holds
    And it prints only the names of what it saved, never a value

  Scenario Outline: A recipe is checked before it runs
    Given a recipe where <problem>
    When login_recipe loads it
    Then it stops with "<message>"

    Examples:
      | problem                                        | message                                       |
      | a credential is a literal value                | credential 'email' must be                    |
      | there are no steps                             | 'steps' must be a non-empty list              |
      | a step is both a goto and a click              | steps[0] must have exactly one of             |
      | a fill step has no value                       | steps[0] fills a field, so it needs a 'value' |
      | there's no "until"                             | 'until' must say when the login is done       |
      | a credential is "env:SHOP_USER" and it's unset | needs the environment variable SHOP_USER      |

  Scenario: A recipe that sends requests only runs against this machine
    # A request can create data, such as an account.
    Given a recipe with a request step
    When it's run against "https://shop.example.com"
    Then it stops with "only runs against this machine"
    And against 127.0.0.1 or localhost it runs

  Scenario: A failed request stops the login and names the step, not the values
    When a recipe's request answers 500
    Then it stops with "Login recipe step 0 (POST /api/Users/) answered 500."
    And no credential appears in the message
