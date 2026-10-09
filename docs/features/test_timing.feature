# Where a test's time went, and where its steps begin in its video (#391).
#
# The Juice Shop demo runs took 14.5, 8.2 and 52.4 minutes for about 20 tests each, and the
# videos were about a minute long, yet replaying the same tests took 14 s each. Nothing saved
# said where the time went, so each test now carries a timing. The video of a test is the
# browser context it ran in, from the moment that context opened, so the report says where
# the steps begin in it.
#
# Code: trailhound/adapters/web_gui/session.py (Session._act, _open_fresh_page),
# trailhound/adapters/web_gui/adapter.py (_timing_html, describe_result_for_log),
# trailhound/run_summary.py (_time_line). Tests: trailhound/tests/test_page_says.py,
# trailhound/tests/test_run_summary.py

Feature: Each test says where its time went
  As someone who finds a run slow or a video long
  I want every test to record its time by phase and where its steps begin in the video
  So that the cause of a slow run can be read from the saved files

  Scenario: A test records its timing in seconds
    When a test has run
    Then its result has "timing" with "reach", "idle_watch", "steps", "settle" and "total"
    And "reach" is the time to reach the start state: a fresh browser, the session, the route or the replayed path
    And "idle_watch" is the 6 s watch of the state's idle noise plus reaching the state again, and 0 when the state was already known this run
    And "steps" and "settle" are the existing "click" and "settle"
    And "total" is the whole test, including a recovery reboot

  Scenario: A recorded test says where its steps begin in the video
    Given videos are on
    When a test has run
    Then "timing" also has "video_start", the seconds from the video's first frame to the first step
    And "video_length", the length of the video so far
    # The video is the last browser context of the test: the idle watch happens in an earlier one.
    # With WEB_GUI_VIDEO=off neither is set.

  Scenario: The report and the console show it
    When the report is rendered
    Then each test that was sent shows "took N s in all" with the phases, and where its steps begin in the video
    And the console line for a test ends its first part with "N s in all"

  Scenario: The run summary says how long the run took
    Given a run with timed tests and model calls
    When its summary is written
    Then it has a line "Time:" with the minutes from the first to the last model call, the average test time and the slowest test
    # Start-up before the first model call is not counted.
