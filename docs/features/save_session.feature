# Saving a session: a person logs in, the engine keeps the cookies and storage.
#
# web_gui loads a saved session into every test (WEB_GUI_SESSION, #154) and Spoor maps
# from one (spoor explore --session). save_session makes that file (issue #155). It
# opens a visible browser at a URL, a person logs in (or puts the app in any state
# worth keeping), and it saves when Enter is pressed or when an --until condition
# holds. No password is stored anywhere. A session file holds live auth cookies, so it
# refuses to write anywhere git doesn't ignore, and it prints only the names of what
# it saved, never a value. A run can also save the session it reached with
# Session.save, under the same rule.
#
# Code: engine/adapters/web_gui/save_session.py, engine/adapters/web_gui/session.py
# (Session.save). Tests: engine/tests/test_save_session.py

Feature: A session is saved by logging in by hand, or when a condition holds
  As a tester of features behind a login
  I want save_session to open a browser where I log in, and save the session when I press Enter or a condition holds
  So that I can make a session file without the engine ever seeing my password

  Scenario: The session is saved under .sessions by product and name
    When I run "python -m engine.adapters.web_gui.save_session --url http://127.0.0.1:3000 --product juice-shop --name logged-in"
    Then a visible browser opens at "http://127.0.0.1:3000"
    And the session is written to ".sessions/juice-shop/logged-in.json"
    And it prints the WEB_GUI_SESSION value and the spoor explore --session line to use it

  Scenario Outline: Product and name must be lowercase slugs
    When I run save_session with --product "<product>" and --name "<name>"
    Then it stops with "--<flag> must be lowercase letters, digits and dashes"

    Examples:
      | product    | name      | flag    |
      | Juice Shop | x         | product |
      |            | x         | product |
      | juice-shop | ../escape | name    |

  Scenario Outline: --until saves as soon as a condition holds on the live page
    Given save_session was started with --until "<until>"
    When <condition>
    Then the session is saved without waiting for Enter

    Examples:
      | until            | condition                                             |
      | storage:token    | a local or session storage key "token" exists         |
      | cookie:sessionid | a cookie named "sessionid" exists                     |
      | url:/dashboard   | the page URL contains "/dashboard"                    |
      | selector:#logout | an element matching the CSS selector "#logout" exists |

  Scenario Outline: An --until that isn't one of the four kinds is refused
    When I run save_session with --until "<until>"
    Then it stops with "--until must be one of storage:<value>, cookie:<value>, url:<value>, selector:<value>"

    Examples:
      | until    |
      | token    |
      | header:x |
      | cookie:  |

  Scenario: Without a terminal to press Enter in, a condition is required
    Given stdin is not a terminal
    When I run save_session without --until
    Then it stops with "No terminal to press Enter in: pass --until so the session is saved when a condition holds."
    And no browser is started

  Scenario: Nothing is saved when the timeout runs out
    # --timeout defaults to 600 seconds. --headless hides the browser, which is only
    # useful with --until.
    Given save_session was started with --until "url:/dashboard" and --timeout 30
    When the URL never contains "/dashboard" within 30 seconds
    Then it stops with "Gave up after 30 s: url:/dashboard never held. Nothing was saved."
    And no session file is written

  Scenario: A session is only written where git ignores it
    # Checked with "git check-ignore". Without git, only a path inside .sessions/ counts.
    When save_session or Session.save is asked to write to "engine/leaked-session.json"
    Then it stops with "git doesn't ignore it, so it could be committed"
    And nothing is written
    # save_session checks this before it starts a browser.

  Scenario: What was saved is reported by name only
    Given the saved state has a cookie "token" and a localStorage entry "token", both with the value "SECRET"
    When the session is saved
    Then the summary is cookies "token" and storage "token"
    And the printed line ends with "Values are never printed."
    And "SECRET" appears nowhere in the summary
