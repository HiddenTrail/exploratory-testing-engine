# The sweep: what a run could have found at all (issue #276).
#
# A run's findings only mean something against what it could have found. On a web target
# that ceiling is set by the map (which actions the Driver may take) and the harness (what
# it can observe). The sweep runs every (state, control) pair once, as the same tab and as
# a new tab, with no model, and lists every problem the harness observed, deduplicated. It
# is a candidate list for a person to review before it becomes a target's known problems
# (#277). Part of the epic "Know what it finds" (#280).
#
# Code: trailhound/adapters/web_gui/sweep.py. Tests: trailhound/tests/test_sweep.py

Feature: A sweep runs every reachable action once and lists what the harness observed
  As someone benchmarking the engine on a web target
  I want to know every problem the harness can observe through the map's actions
  So that a run's findings can be scored against what it could have found

  Scenario: Every pair runs once, and again as a new tab when there's a saved session
    When I run "python -m trailhound.adapters.web_gui.sweep --ontology <map> --url <url> --session <file> --out <file>"
    Then every (state, control) pair in the map is acted on as "same_tab", and as "new_tab"
    And without a session, or with --no-new-tab, only as "same_tab"
    And it stops after --max-actions (400 by default)

  Scenario Outline: Problems are keyed so repeats collapse
    Given an action whose result shows <signal>
    Then the sweep records a "<type>" problem with the pattern "<pattern>"

    Examples:
      | signal                                                                  | type           | pattern                   |
      | a console error starting "ERROR TypeError: x", with a stack after it    | console_error  | ERROR TypeError: x        |
      | the failed request "GET http://127.0.0.1:3000/rest/basket/6?x=1 -> 500" | failed_request | GET /rest/basket/6 -> 500 |

  Scenario: Each problem says where and how it showed
    Then each problem has an id like "P01", its tier ("trusted" if any sighting was trusted, else "weak"), the routes, the actions, how the tests started, and how often
    And a problem seen only when the action started as a new tab is marked "new_tab_only"
    And actions that didn't reach their state are listed under "unreached"

  Scenario: Discovered screens are followed only on request
    # On Juice Shop, switching language "discovers" a translated copy of every screen: the
    # first sweep stopped at its 400-action cap with 1,220 actions still queued.
    Then the actions on screens discovered during the sweep run only with --follow-discoveries
