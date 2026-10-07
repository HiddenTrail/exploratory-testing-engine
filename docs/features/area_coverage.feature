# What each run covered in each area of the product, and how much each area matters next (#328).
#
# The context learned where the Driver got to and which oracle ideas it cited, but not what
# it covered. So the next run couldn't tell a screen tested hard from one nobody touched,
# and the oracle couldn't point at the gaps. Now each test's outcome says where it started,
# which controls it used and the kinds of value it typed; --learn adds that up per area
# across runs and scores every area for the next run, with its reasons in words. The scores
# are for the next steps of the feedback loop: ranking ideas by them (#330), and sending
# the most important places the map lacks to Spoor (#329).
#
# A test counts for the area it started in. A step after one that moved to another screen
# is on that screen, which the outcome can't say, so it only counts where the start screen
# has the same control. That limitation is accepted and written down in areas.py.
#
# Code: trailhound/outcome.py (area, tried, inputs), trailhound/coverage.py (value_kinds),
# trailhound/adapters/web_gui/adapter.py (area_of, coverage_of),
# trailhound/adapters/web_gui/reference.py (control_token), trailhound/adapters/web_gui/session.py
# (changes_data, and a discovery's controls, fields and changes_data),
# trailhound/adapters/web_gui/to_context.py (each screen's controls, fields and changes_data),
# trailhound/ontology/areas.py, trailhound/ontology/feedback.py (learn, coverage_lines),
# trailhound/ledger.py (idea_answers), trailhound/run_summary.py. Tests: trailhound/tests/test_areas.py

Feature: The context keeps what each run covered, per area, and how much each area matters next
  As someone running Trailhound against the same product again and again
  I want each run to leave behind what it tested and what it never touched
  So that the next run goes where testing is thin, not where it has already been

  Scenario: A web test's outcome says where it started, what it used and what it typed
    Given a test that started at "st05", clicked "Add to Basket" and filled "Search" with "<b>x</b>"
    Then its outcome's "area" is "st05"
    And "tried" is ["button:add to basket", "textbox:search"]
    And "inputs" is [["textbox:search", "markup"]]
    But a step that was refused, not found or failed isn't in "tried"
    And a test that never reached its start has no "area", so it doesn't count anywhere
    And a route start "#/search?q=x" is the area "/#/search"
    And numbers in a control's name are "#", so "Reviews(2)" and "Reviews(3)" are both "button:reviews(#)"
    And nothing new goes into the history the model reads: the area is taken from the front of the result's "action"

  Scenario Outline: A value sent to a field has kinds
    When a test sends "<value>"
    Then its kinds are <kinds>

    Examples:
      | value                     | kinds                  |
      |                           | ["empty"]              |
      | -1                        | ["number", "negative"] |
      | 2.5                       | ["number", "decimal"]  |
      | <script>alert(1)</script> | ["markup", "script"]   |
      | ' OR 1=1--                | ["quote"]              |
      | a@b.co                    | ["email"]              |
      | hello                     | ["text"]               |

  Scenario: The map's screens and the screens the Driver reached list what can be tried
    Then each screen to_context writes has "controls", "fields" and "changes_data" as tokens like "button:add to basket"
    And a screen the Driver reached that the map lacks has the same three, from the live page

  Scenario: --learn adds up a run's coverage by area, across runs
    Given a run whose tests started at "st01", "/#/" and "/#/profile"
    When the run ends with --learn
    Then the context's "coverage" has an entry per area: the screen whose states hold the start, else the screen for that route with the shortest path, else the area token itself
    And each entry keeps "tests", "runs", "last_run", "last_tested", "order" (when it was last added to, so a later run's answer to an idea wins), "tried", "inputs" (each field's value kinds), "ideas" (each cited idea's latest answer, never replaced by a later run that only cited it) and "problems" (each error token and how often)
    And a skipped test isn't counted, and an idea id that isn't in the oracle isn't kept
    And learning from the same run again doesn't count it twice
    And coverage kept under a route before the map had a screen for it moves onto that screen

  Scenario: Every area gets an importance score, with its reasons
    When --learn ranks the areas into the context's "areas", most important first
    Then an area gets 3 for "never tested", or 2 times the share of its controls no test has used
    And 1.5 times the share of its oracle ideas no test has checked, wherever the test started
    And 1 for having fields, and 1 times the share of them never filled once it was tested
    And 1 if controls there change data, 2 if errors were recorded there, 1.5 if an idea about it broke
    And 2 for "reached by the Driver, not mapped": a screen the Driver reached beyond the map, or a route a test started from that no screen has
    And 0.1 less for each test already spent there, at most 3 less, and never below 0
    And "why" lists each of those in words, like "never tested" or "tested 21 time(s) already"
    And "untested" is the same score without the errors and broken ideas: what the oracle steers by (#330)
    But coverage left under a key with no screen (a slug a new map renamed) says "no screen in the context for it" and gets nothing for it

  Scenario: An untouched screen with a form ranks above a start page that was tested
    Given the start page was tested 10 times and a checkout screen with a card field and a Pay button never was
    Then the checkout screen ranks above the start page

  Scenario: A screen the map lacks is named by how it was reached
    Given the Driver reached "http://shop/#/profile" by "menuitem:Go to user profile"
    Then its area's title is "/#/profile, reached by menuitem:Go to user profile", cut to 70 characters
    And it says "reached by the Driver, not mapped"

  Scenario: The run says what it learned
    When --learn ends
    Then it prints "Covered: N area(s) tested this run, K for the first time: ..."
    And "Tested where the map has no screen: ..." when a test started where no screen is, naming three at most
    And "Most important areas for the next run: ..." with the top three and their reasons
    And it keeps these lines in the run's output.json as "learned"
    And the run summary shows them under "Learned for the next run"
