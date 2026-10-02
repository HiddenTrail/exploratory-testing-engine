# Discovery memory: screens a run reached beyond its map are kept across runs.
#
# A web_gui result records "discovered" when an action reaches a screen the carried
# map doesn't have (#157). The feedback CLI collects those records from output.json
# and merges them, by screen id, into the product's context file under "discoveries".
#
# A screen reached once might be a fluke, so it stays "seen once" until it is reached
# again, and only then becomes "reproduced" (the bar #148 sets for trusting anything
# once). A discovery stays in the context layer. Promoting one into the product wiki
# is a step a person takes; no code does it.
#
# Code: engine/ontology/feedback.py (extract_discoveries, merge_discoveries),
# engine/tests/test_ontology_claim_matching.py

Feature: Screens found beyond the map are remembered across runs
  As someone exploring an app over many runs
  I want each screen a run discovered written into the product's context file, marked "seen once" or "reproduced"
  So that what one run found beyond the map is remembered and its reliability is visible

  Scenario: Discoveries are read from each test's result
    Given a casting log where test 4's result has a "discovered" record with id "d1"
    And test 5's result has none
    When extract_discoveries runs
    Then it returns one record, for "d1", with "test_number" 4

  Scenario: The CLI writes them into context_<slug>.json
    When I run "python -m engine.ontology.feedback --sut web_gui --product juice-shop --run <output.json>"
    And the run discovered screens
    Then they go under "discoveries" in "engine/ontology/context_juice-shop.json"
    And the run is named by the output's "run_id", or by the folder output.json is in
    And it prints "Recorded N reach(es) of M screen(s) beyond the map (K known, R reproduced)"

  Scenario: A screen reached for the first time is "seen once"
    Given the context has no discoveries
    When a run "run-1" that reached screen "d1" is merged
    Then "d1" is stored with its "signature", "url", "title", "path", "from_state" and "via"
    And its "first_seen" and "last_seen" are "run-1"
    And its "runs" is ["run-1"] and its "times_reached" is 1
    And its "status" is "seen once"

  Scenario: A screen reached again is "reproduced"
    Given "d1" was recorded from "run-1"
    When a run "run-2" that reached "d1" again is merged
    Then "d1" has "times_reached" 2 and "runs" ["run-1", "run-2"]
    And its "first_seen" is still "run-1" and its "last_seen" is "run-2"
    And its "status" is "reproduced"

  Scenario: The latest reach updates the controls, the first reach keeps the path
    Given "d1" was first reached by one path
    When a later run reaches "d1" with different elements
    Then "d1" keeps the "path", "from_state" and "via" of its first reach
    And its "elements" and "controls_offered" are the latest run's

  Scenario: Counting is per reach, so two reaches in one run also count
    Given one run whose tests reached "d1" twice
    When the run is merged
    Then "d1" has "times_reached" 2 and "runs" with that run once
    And its "status" is "reproduced"

  Scenario: Nothing is promoted into the wiki
    Given "d1" is "reproduced"
    When feedback runs
    Then no wiki page is written or changed
    # A person decides whether a discovered screen belongs in the product wiki.
