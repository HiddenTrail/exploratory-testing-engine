# Saved sessions: web_gui tests can start logged in.
#
# The Driver can't type credentials, and that stays. So to test features behind a
# login, a person saves a Playwright session file (context.storage_state(): cookies
# plus storage) and WEB_GUI_SESSION points at it (issue #154). Each test still gets a
# fresh browser context, so results stay attributable, but that context is loaded from
# the file instead of starting empty. A missing or malformed file stops the run before
# it starts, as Spoor's --session does, instead of quietly running every test logged
# out. The file holds live auth cookies, so only its name ever reaches the Driver, the
# report or the map. A map made logged out doesn't match a logged-in start page (Juice
# Shop shows a basket button), so a session/map mismatch is warned about up front.
#
# Playwright can't restore sessionStorage from the file, so web_gui puts it back with an
# init script that runs before the app's own scripts (issue #228).
#
# Code: engine/adapters/web_gui/session.py (load_session_file, session_name,
# session_storage_script, Session._open_fresh_page, check_ready),
# engine/adapters/web_gui/reference.py

Feature: web_gui tests start from a saved login session
  As a tester of features behind a login
  I want WEB_GUI_SESSION to load a saved session into every fresh browser context
  So that tests reach logged-in pages without the engine ever holding a password

  Scenario Outline: A session file that can't be used stops the run before it starts
    Given WEB_GUI_SESSION points at "<file>"
    When web_gui's check_ready runs
    Then the run stops with SystemExit saying "<message>"

    Examples:
      | file                                 | message                    |
      | a path that does not exist           | which does not exist       |
      | a file that isn't JSON               | isn't valid JSON           |
      | JSON without "cookies" and "origins" | isn't a Playwright session |

  Scenario: Without WEB_GUI_SESSION every test starts as a first-time visitor
    Given WEB_GUI_SESSION is unset
    When a test reboots the browser
    Then it gets a new browser context with no cookies and no storage
    And the onboarding evidence has no "session" entry

  Scenario: Every fresh context is loaded from the saved session
    # A reused page let Juice Shop remember a dismissed banner in a cookie, so later
    # restarts landed on a different start screen (issue #117). A fresh context per
    # test fixes that, and the session file is loaded into each one.
    Given WEB_GUI_SESSION points at ".sessions/juice-shop/logged-in.json"
    When each test reboots the browser before replaying its path
    Then each test gets a new browser context created with that file as its "storage_state"
    And no cookies or storage carry over from the previous test's context

  Scenario: A saved session's sessionStorage is put back in every fresh context
    # Without it, Juice Shop opened the basket with "TypeError: Cannot read properties
    # of null (reading 'Products')" in every test.
    Given the session file has the sessionStorage entry "bid" for "http://127.0.0.1:3000"
    When a test reboots the browser
    Then the new context gets an init script that sets "bid" on pages of "http://127.0.0.1:3000"
    And the script only fills an empty sessionStorage, so it never overwrites what the app wrote
    And a session file without sessionStorage adds no script

  Scenario: Only the session's name reaches the Driver and the report
    Given WEB_GUI_SESSION points at ".sessions/juice-shop/logged-in.json"
    When check_ready fills in the onboarding evidence
    Then the "session" entry says every test starts from the saved session "logged-in" in a fresh browser context
    And the session is named by its file name without the extension
    And no cookie or storage value from the file appears in it

  Scenario Outline: A run warns when its session isn't the one the map was made with
    # The map records the session it was made with in session.session_name (from_spoor
    # --session writes it). An empty name means no session.
    Given the carried map was made with session "<map session>"
    And the run starts with session "<run session>"
    When check_ready runs
    Then the mismatch warning printed is "<warning>"

    Examples:
      | map session | run session | warning                                                                                                           |
      | logged-in   | logged-in   | none                                                                                                              |
      |             |             | none                                                                                                              |
      |             | logged-in   | WARNING: the carried map was made without a saved session, but this run starts from the saved session 'logged-in' |
      | logged-in   |             | WARNING: the carried map was made from the saved session 'logged-in', but this run starts without a saved session |

  Scenario: The mismatch warning does not stop the run
    Given the carried map was made without a saved session
    And the run starts from the saved session "logged-in"
    When check_ready runs
    Then the warning tells the user to make the map with the same session (from_spoor --session)
    And the run goes on to launch the browser and check the entry state
