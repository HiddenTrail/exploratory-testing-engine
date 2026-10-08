# web_gui idle noise: learn what each state changes on its own, once per run.
#
# Polling, timers, analytics and carousels change a page with no action at all. To
# keep those from being blamed on the action, the first time a test reaches a state
# the session watches it idle: 3 looks, 2 s apart, so about 6 s. The signal audit on
# #146 found PrestaShop's home page carousel, which turns about every 5 s, reported
# as an action's trusted effect, which is why the watch covers that long and learns
# controls too. The watch only runs once the replay is verified to have reached the
# state: a drifted first replay once attached another page's noise to the state for
# the rest of the run (Copilot on #146). The watch also moves the page on (the
# carousel turned during it), so afterwards the state is reached afresh, the way
# every later test reaches it.
#
# Code: trailhound/adapters/web_gui/session.py (Session._idle_noise, Session.act,
# _NOISE_SAMPLES, _NOISE_SAMPLE_MS, _console_key, _request_key)

Feature: The engine learns each state's idle noise
  As someone testing busy pages
  I want each state watched idle once per run, recording what changes by itself
  So that polling, carousels and timers aren't blamed on the action

  Scenario: The idle watch looks 3 times over about 6 s
    Given a test reaches state "st02" for the first time this run
    When the session watches it idle
    Then it reads the page 3 times, 2000 ms apart
    And it records the requests started during the watch, without query or fragment
    And the console errors logged during it, with digits replaced by "#"
    And the storage and cookie keys whose value changed
    And the controls that came or went
    And the messages the page showed or stopped showing, with digits replaced by "#" (page_says.feature)

  Scenario: The idle watch learns controls that come and go
    Given a page whose links read "Slide 1", then "Slide 1", then "Slide 2"
    When the session watches it idle
    Then the noise for its controls is "link:slide 1" and "link:slide 2"

  Scenario: A state is watched once per run, then reached afresh
    Given a test on "st02 :: button:Back" whose replay reaches "st02"
    When it runs for the first time this run
    Then "st02" is watched idle
    And the session reboots and replays the path to "st02" again before the click
    When a second test on "st02" runs
    Then it is not watched again, and the session reboots only once

  Scenario: A state the replay didn't reach is not watched
    Given a test on "st02 :: button:Back" whose replay lands somewhere else
    When it runs
    Then nothing is watched and "st02" has no noise yet

  Scenario: What was seen idle goes to signals_weak
    Given "st02" was seen polling "GET http://x/api/poll" and changing "local:clock" while idle
    When a later action on "st02" fails that poll and changes "local:clock"
    Then both are in "signals_weak", not in "signals"
