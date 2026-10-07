# The oracle ranks ideas by how much of their area is still untested (#330).
#
# The oracle ranked ideas by their facts' sources and reachability. It didn't know which
# screens earlier runs had tested hard and which nobody had touched, so a run could spend
# most of its tests where the last runs already went. Now, once a run has learned what it
# covered (#328), each idea about a screen moves with its area's "untested" score: the
# area's importance without the errors and broken ideas found there. Known findings will be
# re-checked by #319, not chased, so they don't pull the oracle back. And the places the
# Driver reached beyond the map with the most still untested get ideas like the map's screens.
#
# In the first check the idea weight was half a point and the area's importance included
# what was found there: the product dialog a run had tested 11 times took 6 of the
# Driver's 15 ideas, and no screen the run skipped got any. Steering by what's untested, at
# a full point, gave 6 of the 15 to places the run never touched. The check builds the next
# run's oracle from the context a live run learned, which costs nothing (runs/check330).
#
# Code: trailhound/ontology/oracle_creator.py (weigh_by_area, AREA_WEIGHT),
# trailhound/ontology/areas.py ("untested"), trailhound/ontology/product.py (context_screens,
# new_areas, NEW_AREAS), trailhound/adapters/web_gui/session.py (a discovery's "features"),
# trailhound/adapters/web_gui/to_context.py (common_controls), trailhound/report.py and
# trailhound/ontology/report.py (an idea's area).
# Tests: trailhound/tests/test_oracle_by_area.py

Feature: The oracle ranks ideas by how much of their area is still untested
  As someone running Trailhound against the same product again and again
  I want the oracle to send the Driver where testing is thin
  So that a run doesn't spend its tests where the last runs already went

  Scenario: Before any run has learned its coverage, the order is the oracle's own
    Given the product's context has no "coverage"
    Then no idea's score moves, and no idea has an "area"

  Scenario: An idea moves with how much of its area is still untested
    Given the context has coverage from earlier runs
    Then each idea about a screen gets 1 point per point its area's "untested" score is above or below the middle one's, among the areas ideas are about (the upper middle of an even count)
    And it says why in "area", like "untested 7.0: never tested; 2 field(s); 2 control(s) change data; reached by the Driver, not mapped"
    And the run's report and the oracle report show it as "Its area: ..."
    And an idea about the product or a wiki page doesn't move

  Scenario: A screen never tested ranks above one tested hard
    Given a screen was tested in three runs, every control used and every field sent several kinds of value
    And another screen was never tested
    Then the untested screen's best idea ranks above the tested screen's best
    And the tested screen's ideas sink, and none drop out of the oracle

  Scenario: What was found in an area doesn't pull the oracle back to it
    Given errors were recorded on a screen
    Then its importance goes up by 2 (unless its score was already at 0), but its "untested" score doesn't
    And its ideas score the same as without the errors, and their "area" doesn't name them

  Scenario: The places the Driver reached beyond the map with the most untested get ideas
    Given the context has coverage, and discoveries recorded with "features"
    Then the 3 with the highest "untested" score (ties to the one reached most often) become screens for the seeder, with their route and no facts
    And their ideas say "where" with the route, and "area" says "reached by the Driver, not mapped"
    But they get no REACHABLE_BONUS: a place beyond the map is reached by replaying how it was found
    And their titles lose any email, and they also name areas in the testing story (product_areas)
    But a discovery recorded before #330, with no features, gets no ideas and stays context only
    And with no coverage yet, no discovery gets ideas

  Scenario: A discovery's features leave out the toolbar
    Given a control is on 80% or more of the map's states
    Then it gives a discovery no features, the way it gives a mapped screen none
