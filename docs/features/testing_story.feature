# The Driver's testing story: more than pass or fail (issues #265, #271).
#
# A hypothesis used to be a list of behaviours and observations. It said little about how
# the Driver tested, how much it thought it covered, or how good the system looked, so the
# Skeptic could only say "test more". Now each checkpoint the Driver tells its testing
# story, after Michael Bolton's three strands, braided together:
# - the product's status: per area, what it has seen of the quality so far, in safety
#   language ("no problems seen yet", not "good")
# - how it tested: the approach, how it would recognize a problem (the oracle), how deep
#   the coverage went and what it was of, and what it didn't test
# - how good that testing was: what made it harder or impossible, and what would help
# Coverage levels have meanings, after James Bach's low-tech testing dashboard, so a claim
# of coverage can be checked. They are assessments grounded in tests, never counts.
#
# The Skeptic receives the story (it didn't at first: #271) and the previous checkpoint's
# story, and debriefs it the way a test lead debriefs a tester (session-based test
# management). The report leads with the story; the bug list is one strand of three.
# Part of epic #262.
#
# The story is asked for in its own call, right after the hypothesis: inside the hypothesis
# call the answer grew big enough to break too often (fields lost, or written in another
# tool-call format), and strict tool use isn't available on Bedrock.
#
# Code: engine/tools.py (TESTING_STORY_TOOL, TESTING_STORY_SYSTEM_PROMPT,
# validate_testing_story, COVERAGE_LEVELS, QUALITY_SEEN, CONFIDENCE, SKEPTIC_SYSTEM_PROMPT),
# engine/loop.py (get_testing_story, get_skeptic_review, run_checkpoint_loop), engine/report.py
# (_areas_table, _obstacles_list, _render_standing_section), engine/run_summary.py,
# engine/client.py (find_misplaced_fields).

Feature: The Driver tells its testing story, and the Skeptic debriefs it
  As someone reading what a run found
  I want the Driver's account of the product, of its testing, and of how good that testing was
  So that the Skeptic can challenge the testing, not just ask for more of it, and people see where things stand

  Scenario: The story is its own call, merged into the hypothesis
    When the Driver has formed a checkpoint hypothesis
    Then the engine asks it for the testing story in a separate call, "submit_testing_story", with the hypothesis in its evidence
    And the story's "areas" and "obstacles" are added to the hypothesis before the Skeptic sees it
    And the story call shares the hypothesis call's cached test history

  Scenario: Every checkpoint has a testing story, area by area
    When the Driver tells its testing story
    Then it has "areas", up to 5, each with "area", "approach", "coverage", "coverage_of", "oracle", "not_tested", "tests", "quality", "confidence" and "why"
    And each area cites the tests behind it
    And it has "obstacles", up to 3, each with "obstacle", "would_help" and "help_from" (engine, map, test_data or product), empty if nothing got in the way
    And "coverage_of" lists one or more of inputs, states, sequences, timing, data, users (#285: free text came back as prose about method)

  Scenario: Areas are parts of the product, not controls
    # #285: one row bundled the account menu, the language radio and "add new card"; another was named after an overlay.
    Given the evidence has "product_areas"
    Then the Driver is told to name each area after a part of the product from it, never after a control or an overlay, and to keep unrelated parts apart

  Scenario Outline: Coverage levels have meanings
    Then the coverage level "<level>" means "<meaning>"

    Examples:
      | level               | meaning                                                       |
      | can_it_work         | it can work at all: the basic path                            |
      | common_and_critical | the common and the critical cases                             |
      | deep                | if there were a bad bug here, we would probably know about it |

  Scenario Outline: Quality is what has been seen so far, in safety language
    Then the quality "<quality>" means "<meaning>"

    Examples:
      | quality              | meaning                                             |
      | no_problems_seen_yet | no problems seen so far, and no definite suspicions |
      | concerns             | something looks wrong, not confirmed                |
      | problems_found       | a problem was found and shown                       |

  Scenario Outline: A story that doesn't hold together is retried with the reason
    Given <problem>
    Then the story is rejected with "<message>"

    Examples:
      | problem                              | message                                                                                          |
      | there are no areas at all            | 'areas' must be a non-empty list                                                                 |
      | an area's coverage is "thoroughly"   | areas[0].coverage must be one of can_it_work, common_and_critical, deep                          |
      | an area's quality is "good"          | areas[0].quality must be one of no_problems_seen_yet, concerns, problems_found                   |
      | an area's coverage_of is prose       | areas[0].coverage_of must list one or more of inputs, states, sequences, timing, data, users     |
      | an obstacle's help_from is "someone" | obstacles[0].help_from must be one of engine, map, test_data, product                            |
      | an area names no oracle              | areas[0].oracle must not be empty                                                                |
      | an area cites no tests               | areas[0].tests must cite the test numbers behind it; an area with no tests belongs in 'untested' |
      | there's no "obstacles" field         | missing required field 'obstacles'                                                               |

  Scenario: The Skeptic receives the story, and the previous one
    # It was left off the Skeptic's evidence at first, so the Skeptic was asked to question
    # a story it never saw (#271).
    When the Skeptic reviews a checkpoint
    Then its evidence has the hypothesis "areas" and "obstacles"
    And from the second checkpoint on, "previous_story": the areas of the checkpoint before

  Scenario: The Skeptic debriefs the story the way a test lead would
    Then it asks "how do you know?" of every claim: proof of how it was tested, not just of the outcome
    And a coverage level the cited tests and test_coverage don't back is "coverage_overstated", and coverage is only ever of something
    And a quality call or a confidence more sure than the testing is "overclaimed"
    And an approach or oracle that couldn't have shown the problem is "method_in_doubt"
    And it distrusts a clean story, every area fine and nothing in the way
    And an area whose coverage and evidence didn't move since the previous story, though it was worked on, is "not_worth_continuing"

  Scenario: The report leads with the story
    When a run's report is rendered
    Then "Where it stands" comes first, right after the headline, and first in the top bar
    And it shows each area's approach and oracle, its coverage level and what it was of, what wasn't tested, what's been seen, the confidence and why
    And "What got in the way of testing" lists the obstacles and what would help
    And each checkpoint's details show its own story
    And the CI summary has a "Where it stands" table and "What got in the way"
    And runs made before #271 still render, with their older scales

  Scenario: The calls have room
    # When the hypothesis carried the story, answers ran 2,000 to 2,560 tokens and were cut off at the old 2,560.
    Then the hypothesis call allows 4,096 output tokens, and the story call 2,048

  Scenario: A missing field found elsewhere in the answer is named in the log
    Given a rejected answer missing "observations", which sits inside behaviors[1]
    Then the log says "missing fields found elsewhere in the answer: observations at behaviors[1].observations"
