# The Driver's testing story: more than pass or fail (issue #265).
#
# A hypothesis used to be a list of behaviours and observations. It said little about how
# the Driver tested, how much it thought it covered, or how good the system looked, so
# the Skeptic could only say "test more". Now each checkpoint the Driver also tells its
# testing story, area by area: where it was, how it tested, how much it thinks it covered
# and what it didn't, its estimate of the area's quality and how sure it is. The Skeptic
# is told to question that account against the tests, and the report and the CI summary
# show the last one as "where it stands". Part of epic #262.
#
# Code: engine/tools.py (HYPOTHESIS_TOOL "areas", AREA_TESTED, AREA_QUALITY, CONFIDENCE,
# validate_hypothesis_response, SKEPTIC_SYSTEM_PROMPT), engine/loop.py (the hypothesis
# call's max_tokens), engine/report.py (_areas_table, _render_standing_section),
# engine/run_summary.py, engine/client.py (find_misplaced_fields).

Feature: The Driver tells its testing story, and the Skeptic questions it
  As someone reading what a run found
  I want the Driver to say how it tested, how much it covered, how good things look and how sure it is
  So that the Skeptic can challenge the testing, not just ask for more of it, and people see where things stand

  Scenario: Every hypothesis has a testing story, area by area
    When the Driver forms a checkpoint hypothesis
    Then it has "areas", up to 5, each with "area", "approach", "tested", "not_tested", "tests", "quality", "confidence" and "why"
    And "tested" is thoroughly, partly or barely; "quality" is good, neutral or bad; "confidence" is high, medium or low
    And each area cites the tests behind it

  Scenario Outline: A testing story that doesn't hold together is retried with the reason
    Given an area where <problem>
    Then the hypothesis is rejected with "<message>"

    Examples:
      | problem                   | message                                                                                          |
      | there are no areas at all | 'areas' must be a non-empty list                                                                 |
      | "tested" is "mostly"      | areas[0].tested must be one of thoroughly, partly, barely                                        |
      | "quality" is "great"      | areas[0].quality must be one of good, neutral, bad                                               |
      | no tests are cited        | areas[0].tests must cite the test numbers behind it; an area with no tests belongs in 'untested' |

  Scenario: The Skeptic questions the story against the tests
    Then the Skeptic is told to check "thoroughly" against the cited tests and test_coverage, and to raise "coverage_overstated" when they don't support it
    And to raise "overclaimed" when the quality estimate or the confidence is more sure than the testing
    And "method_in_doubt" when the approach couldn't have found what it claims to have looked for

  Scenario: The report and the CI summary say where it stands
    When a run's report is rendered
    Then each checkpoint's details show "The Driver's testing story" as a table
    And a "Where it stands" section, linked in the top bar, shows the last checkpoint's areas
    And the CI summary has a "Where it stands" table: area, covered, quality, confidence, not tested
    And runs made before #265 have no areas, and get neither

  Scenario: The hypothesis has room for the story
    # With the story, answers ran 2,000 to 2,560 tokens and were cut off at the old 2,560.
    Then the hypothesis call allows 4,096 output tokens

  Scenario: A missing field found elsewhere in the answer is named in the log
    Given a rejected answer missing "observations", which sits inside behaviors[1]
    Then the log says "missing fields found elsewhere in the answer: observations at behaviors[1].observations"
