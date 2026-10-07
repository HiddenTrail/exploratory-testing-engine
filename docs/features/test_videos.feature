# Videos of the tests a run's conclusions rest on (issue #286).
#
# A reader should be able to watch what a test did, most of all the tests a finding, a
# bug or a debrief answer rests on. Every web test runs in a fresh browser context, so
# each one can be recorded on its own. A test of about 10 s came to just under 0.5 MB,
# and a run has 20 to 30 tests, so only the cited ones are kept. A video shows whatever the logged-in page
# shows, so it follows the screenshot rules: kept with the run's files, never committed,
# never sent to a model. Playwright traces would show more, but they hold cookies and
# tokens, so they aren't used.
#
# Code: trailhound/runner.py (cited_tests, keep_test_media), trailhound/adapter.py
# (save_test_media), trailhound/adapters/web_gui/session.py (save_videos),
# trailhound/adapters/web_gui/adapter.py (save_test_media, the test card).
# Tests: trailhound/tests/test_test_videos.py

Feature: The tests a run rests on can be watched
  As someone reading a run report
  I want a video of each test a conclusion rests on
  So that I can see what the test did, not only what it recorded

  Scenario: Every browser context records, and each test keeps the one it acted in
    Given WEB_GUI_VIDEO is not "off"
    And the session was started by check_ready, as a run's is
    When the web session opens a browser context
    Then it records a 960 x 675 video into a scratch folder
    And the recording of the context a test's action ran in is kept under the test's number
    # It shows the way to the state and then the action, before any recovery reboot.

  Scenario: Only the cited tests' videos are kept
    When the run ends, with or without an error
    Then the cited tests are the ones the checkpoints' observations, the final observations and the debrief answers cite
    And the adapter's save_test_media saves their videos as <out-dir>/videos/test_<n>.webm
    And recording stops first, so the last video is complete
    And the scratch folder, with every other recording, is deleted
    And the log says "Kept the videos of N cited test(s), e.g. <out-dir>/videos/test_<n>.webm"
    # Bug replays aren't kept: the report shows them only as a verdict.

  Scenario: A test's entry and card show its video
    Given test 3's video was kept
    Then its casting_log entry has "video": "videos/test_3.webm"
    And its card in the report has a fold "Video of this test" with a video player that loads nothing until it's played

  Scenario: Videos can be switched off, and only a run records
    Given WEB_GUI_VIDEO is "off"
    Then nothing is recorded and no entry has a "video"
    And the sweep sets it to "off" itself, and from_spoor and signal_audit start sessions that don't record

  Scenario: A lost video doesn't fail the run
    When saving the videos raises an error
    Then the log says "Couldn't keep the test videos" and the run's output is written as usual

  Scenario: CI keeps the videos with the run
    When the exploratory-run workflow uploads runs/ci/ as its artifact
    Then the videos are in it, kept 30 days like the rest
