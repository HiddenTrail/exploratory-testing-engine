# web_gui actuation: press one control, the way the safety gate classified it.
#
# A search or filter box is filled; everything else is clicked. A click first looks
# the control up on the live page by web-recon's role and name, because the saved
# selector is positional and can shift: on Juice Shop a toast in the same overlay
# container moved it (#123). Then it checks what sits on top of the control's centre.
# Something else on top (a cookie notice, say) used to cost the full 4 s + 3 s of
# timeouts, and then the forced click landed on the cover, so "Next page" never paged
# (#130). Now a covered control gets the click event sent to it directly, and the
# result names the cover in covered_by. A cover is described by role or tag with id
# and classes, so the Driver can tell covers apart (#150). A search box is filled with
# "test" and Enter is never pressed, matching the read-only recon.
#
# Code: trailhound/adapters/web_gui/session.py (_actuate, _fill, _cover, _COVER_JS,
# _live_locator), .experiments/web-recon/safety.py (TEXT_ROLES, SEARCH_PROBE)

Feature: Controls are pressed by role and name, and a cover is reported
  As someone testing a changing app with banners and overlays
  I want each click to find the control on the live page first, get past a cover, and say what covered it
  So that a shifted layout or a cookie notice doesn't send the click to the wrong element

  Scenario: A search box is filled with "test" and never submitted
    Given a control with role "textbox" (or "searchbox") named "Search postcodes"
    When it is actuated
    Then it is filled with "test", by role and name when exactly one matches, else by its saved selector
    And Enter is not pressed
    And it is not clicked, since a click would only focus it and look like a dead control

  Scenario: The click goes to where the control is now
    # Playwright's role lookup names by the accessibility tree ("Help getting
    # started"), where web-recon's DOM name is "school Help getting started".
    Given a button saved at "#saved" with the name "school Help getting started"
    And Playwright's role lookup finds no match
    And web-recon's element list shows exactly one such button, now at "#now"
    When it is actuated
    Then "#now" is clicked
    And "#saved" is not

  Scenario Outline: What is on top of the control decides how it is pressed
    Given a button "Next page" whose centre is <on_top>
    When it is actuated
    Then it is pressed by <how>
    And "covered_by" is <covered_by>

    Examples:
      | on_top                                                   | how                                        | covered_by                         |
      | the control itself or inside it                          | the click ladder                           | not set                            |
      | a part of the same control, such as its label            | a forced click                             | not set                            |
      | another element that goes away within a second           | the click ladder                           | not set                            |
      | a dialog named "cookieconsent" that stays                | a click event dispatched to the control    | "dialog 'cookieconsent'"           |

  Scenario: A cover gets up to a second to go away
    Given another element is on top of the control
    When it is actuated
    Then the session checks again every 200 ms, up to 5 times
    And it stops waiting as soon as the control is clear

  Scenario: The click ladder tries the most specific way first
    Given nothing covers the control
    When it is actuated
    Then it tries, in order, until one works:
      | step                                                                        | timeout |
      | Playwright's role and exact name, if the role is locatable and one matches  | 4 s     |
      | the live selector from web-recon's role and name, if it differs from saved  | 3 s     |
      | the saved selector                                                          | 3 s     |
      | the saved selector with a forced click                                      | 2 s     |

  Scenario: A control that can't be pressed is not_actuated
    Given every step of the ladder fails
    When a test on that control runs
    Then "verdict" is "not_actuated"
    And "covered_by" is not in the result
    And the log line reads "NOT ACTUATED - the control could not be clicked"
