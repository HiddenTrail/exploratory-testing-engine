# Session freshness: a stale session is refused before a run spends anything.
#
# A saved session goes stale on the server long before the page shows it. Found in the
# milestone run (issue #227): the Juice Shop token cookie had expired overnight, the
# browser dropped it, and the token left in localStorage kept the page looking logged
# in while the server answered 500, which the engine reported as a bug. So before a
# run, web_gui reads the expiry of every credential in the session file (cookie dates
# and JWT "exp" claims), refuses an expired one, and warns about one that expires
# within 30 minutes. A session with no dates to judge passes that check, so
# WEB_GUI_SESSION_CHECK can name a path that only works logged in (for example
# /profile on Juice Shop), and the run stops if the server answers 400 or above.
#
# Code: engine/adapters/web_gui/session.py (session_expiry, check_session_fresh,
# _jwt_exp, Session.check_url, check_ready)

Feature: A stale saved session is refused before a run
  As someone paying for runs
  I want credential expiry checked, and optionally the server asked, before any test runs
  So that a run doesn't test a logged-out app while believing it's logged in

  Scenario Outline: Which entries in the session file count as credentials
    # A cookie counts by its name or by holding a JWT. A storage entry only counts
    # when its value is a JWT (three dot-separated parts starting with "eyJ").
    Given WEB_GUI_SESSION points at a session file that has <entry>
    When its expiry is checked
    Then it is checked as "<checked as>"

    Examples:
      | entry                                                        | checked as              |
      | a cookie "token" with an expiry date                         | cookie token            |
      | a cookie "theme" with an expiry date and a plain value       | not a credential        |
      | a cookie "x" whose value is a JWT with an "exp" claim        | cookie x (its JWT)      |
      | a session cookie "sid" with no expiry date and a plain value | not checked             |
      | a localStorage entry "token" whose value is a JWT with "exp" | storage token (its JWT) |
      | a sessionStorage entry "auth" whose value is a JWT with "exp" | storage auth (its JWT)  |
      | a localStorage entry "auth" with a plain value               | not checked             |

  Scenario: An expired credential stops the run
    Given WEB_GUI_SESSION points at ".sessions/juice-shop/logged-in.json"
    And the cookie "token" in the session expired before now
    When web_gui's check_ready runs
    Then the run stops with SystemExit saying the saved session "logged-in" has expired (cookie token)
    And the message says to save a fresh session with "python -m engine.adapters.web_gui.save_session"
    And no browser is launched

  Scenario: A credential that expires within 30 minutes only warns
    Given WEB_GUI_SESSION points at ".sessions/juice-shop/logged-in.json"
    And a JWT in the cookie "x" expires 10 minutes from now
    When web_gui's check_ready runs
    Then it prints "WARNING: the saved session 'logged-in' expires within 30 minutes (cookie x (its JWT)). Tests after that will run half logged in."
    And the run goes on

  Scenario: A session with no dates to judge passes the expiry check
    Given WEB_GUI_SESSION points at a session file
    And no credential in the session file has an expiry date or a JWT "exp"
    When web_gui's check_ready runs
    Then the expiry check neither stops the run nor warns

  Scenario Outline: WEB_GUI_SESSION_CHECK asks the server whether it still accepts the session
    # The path is opened in a fresh browser context loaded from the session, with a
    # 15 second timeout, before the entry state is checked.
    Given WEB_GUI_SESSION points at ".sessions/juice-shop/logged-in.json"
    And WEB_GUI_SESSION_CHECK is "/profile"
    And the server answers "<answer>" for "/profile"
    When web_gui's check_ready runs
    Then <result>

    Examples:
      | answer      | result                                                                                              |
      | 200         | it prints "Session 'logged-in' accepted by the server (/profile answered 200)." and the run goes on |
      | 401         | the browser is closed and the run stops, saying "/profile answered 401"                             |
      | 500         | the browser is closed and the run stops, saying "/profile answered 500"                             |
      | no response | the browser is closed and the run stops, saying "/profile answered nothing"                         |

  Scenario Outline: A WEB_GUI_SESSION_CHECK that isn't a path on the product stops the run
    # Git Bash rewrote "/profile" into "C:/Program Files/Git/profile", Juice Shop answered
    # 200 for that made-up path, and the check passed without checking anything (#243).
    Given WEB_GUI_SESSION_CHECK is "<value>"
    When web_gui's check_ready runs
    Then the run stops with SystemExit saying it "isn't a path on the product, like /profile"
    And the message says "MSYS_NO_PATHCONV=1" stops Git Bash rewriting the path
    And no browser is launched

    Examples:
      | value                        |
      | C:/Program Files/Git/profile |
      | profile                      |
      | http://other.test/profile    |
      | //other.test/profile         |

  Scenario: The server check only runs with a session
    Given WEB_GUI_SESSION is unset
    And WEB_GUI_SESSION_CHECK is "/profile"
    When web_gui's check_ready runs
    Then "/profile" is not opened
    And the run goes on to check the entry state
