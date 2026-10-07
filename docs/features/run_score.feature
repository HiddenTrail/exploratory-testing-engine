# Scoring a run: found X of Y known problems, by evidence (issue #277).
#
# Ten benchmark runs found the same things, and nothing said what they missed. A target
# can have a list of known problems (test-targets/known-problems/<target>.json), each with
# how it shows in a test's recorded signals and the words that name it. A run is scored
# against it by code, never by a model. Part of the epic "Know what it finds" (#280).
#
# Code: trailhound/adapters/web_gui/score.py, test-targets/known-problems/juice-shop.json,
# .github/workflows/exploratory-run.yml. Tests: trailhound/tests/test_score.py

Feature: A run is scored against a target's known problems
  As someone judging whether a change makes the engine find more
  I want each run scored as found X of Y known problems, by evidence
  So that changes are compared by what they find, not only by how they report

  Scenario: An observation finds a known problem by evidence and by name
    Given the known problem "JS02" shows as a console error containing "reading 'nativeElement'" and is named by "About" or "nativeElement"
    When an observation cites a test whose recorded console errors contain that text, and its claim says "About"
    Then JS02 is found, with the observation's id, kind, status and replay verdict

  Scenario: Evidence alone isn't enough
    # One observation about a 403 had "found" a failing CDN too, because its test showed both.
    Given an observation whose cited test shows JS03's and JS05's signals, and whose claim only names the 403
    Then JS03 is found, and JS05 is listed as seen by that test but not reported

  Scenario: A problem that needs a new tab only counts from a new-tab test
    Given JS01 matches only tests that started as "new_tab"
    Then a same-tab test showing the same error doesn't find it

  Scenario: The score says what was found, seen, missed and out of reach
    When I run "python -m trailhound.adapters.web_gui.score --known test-targets/known-problems/juice-shop.json --run <output.json>"
    Then it prints "Known problems found: X of Y" with the list's review status
    And each problem found (and how it was labelled), seen by a test but not reported, or missed
    And the problems listed as out of the harness's reach, which aren't counted
    And with --out it writes the score as JSON

  Scenario: A run scores itself when its target has a list
    # Since #285, through the adapter's score_run hook.
    Given WEB_GUI_KNOWN_PROBLEMS names a list, or WEB_GUI_PRODUCT is "juice-shop" and test-targets/known-problems/juice-shop.json exists
    When the run ends
    Then output.json has "score", the report's headline line and stats show "known problems found", and the run summary (and so the CI page) starts with it

  Scenario: The list says who checked it
    Then a known-problems list has "review": "status" "proposed" until a person has checked it, then "reviewed" with "by"
