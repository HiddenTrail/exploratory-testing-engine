# The test browser never leaves the product's site (issue #308).
#
# The safety gate judges a link by its href, so a link on the site that redirects
# elsewhere gets through. In a lean run on 2026-10-06, Juice Shop's
# "./redirect?to=https://github.com/..." took the logged-in test browser to GitHub, and
# GitHub's cookies were recorded as trusted signals. So the browser itself stops any
# main-frame navigation off the site, whatever caused it. That rule stays even when
# testing fully (#299).
#
# It uses Chrome's own interception (CDP Fetch) on page documents only. Playwright's
# route() was tried first: it doesn't see redirect hops, and routing every request
# kept Juice Shop's socket.io poll open, so no page ever counted as rested.
#
# Code: trailhound/adapters/web_gui/session.py (off_site_target, _guard_page, _on_document,
# _on_request_failed, _storage), adapter.py (API_SCHEMA_DOC, describe_result_for_log,
# render_test_entry). Tests: trailhound/tests/test_web_gui_adapter.py

Feature: The test browser never leaves the product's site
  As someone pointing the engine at a product
  I want the browser stopped before it goes to another site, even through a redirect
  So that a test never touches a system it wasn't pointed at

  Scenario Outline: A main-frame navigation off the site is stopped
    Given the site is "http://127.0.0.1:3000"
    When the page's main frame <navigates>
    Then the browser is stopped before it goes, and the test's result has "blocked_off_site": ["<target>"]

    Examples:
      | navigates                                                                                | target                 |
      | goes to "https://github.com/x"                                                           | https://github.com/x   |
      | gets a 302 from "/redirect?to=https://github.com/x" with Location "https://github.com/x" | https://github.com/x   |
      | goes to "http://localhost:3000/", which is another origin                                | http://localhost:3000/ |

  Scenario: Everything else loads as before
    Then a navigation on the site, a redirect that stays on it, a frame inside the page from another site, and any request that isn't a page document (scripts, styles, XHR, Juice Shop's socket.io poll) go through untouched
    And pages settle as fast as without the guard

  Scenario: Every page is guarded
    Then the page of every fresh browser context is guarded, and so is any tab a click opens
    And if the guard can't be set up, the log says "WARNING: couldn't guard the browser against leaving the site"

  Scenario: A stopped trip is reported, not mistaken for the product
    When a test's navigation was stopped
    Then the stopped request isn't counted as a failed request
    And the reading after the action is of the browser's error page, so every signal goes to signals_weak
    And the error page isn't recorded as a discovered screen
    And the log says "stopped from leaving the site for <target>", and the report shows a "stopped from leaving the site" badge
    And the Driver's API doc says a control that leads off the site can be worth reporting

  Scenario: Only the site's own cookies are read
    Then the storage the signals compare holds the site's own cookies only, never another site's
