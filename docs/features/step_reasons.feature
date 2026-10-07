# A failed step says why, and a control with no name is told apart by what a person sees (#325).
#
# In a lean run on 2026-10-06 all six failed steps were fills on "textbox:", Juice Shop's
# toolbar search box, which is 0 pixels wide until the search icon opens it. The Driver
# took it for a basket quantity field, typed -1, 0 and -5 into it, got "failed" with no
# reason, and reported the harness as broken. In the #330 benchmark, blocking objections
# like "the fill target was the wrong element" stayed open for the same reason (#340).
#
# Code: trailhound/adapters/web_gui/session.py (failure_reason, _note_failure, _outcome,
# page_controls in _act), .experiments/web-recon/perceive.py (the capture's "hint"),
# trailhound/adapters/web_gui/reference.py (unnamed_key, _control_lines),
# trailhound/adapters/web_gui/from_spoor.py (keeps the hint in a converted map).
# Tests: trailhound/tests/test_step_reasons.py

Feature: A failed step says why, and unnamed controls are told apart
  As a Driver deciding what a failed step means
  I want to know why the browser couldn't do it, and which control has no name
  So that I neither guess at a field nor blame the harness

  Scenario Outline: A failed step's "detail" says why, from the browser's error
    When the browser's error says "<error>"
    Then the step is "failed" with the detail "<detail>"

    Examples:
      | error                             | detail                                                                      |
      | ... intercepts pointer events     | covered by another element                                                  |
      | ... element is not visible        | hidden: it has no size or isn't shown (it may open from another control)    |
      | ... element is not enabled        | disabled                                                                    |
      | ... element is not editable       | not editable (read-only)                                                    |
      | strict mode violation ...         | more than one control matched                                               |
      | Element is not a <select> element | not a dropdown with options (a custom one: click it, then click the option) |
      | ... did not find some options     | no option with that label                                                   |
      | Timeout 3000ms exceeded.          | timed out waiting for it                                                    |
    # Only Playwright's own words count: the call log also quotes the element's HTML, where
    # aria-disabled="false" on every Angular dropdown once read as "disabled".

  Scenario: The most telling reason wins
    Given a click tries several ways, the first failing with "element is not visible" and a forced click only timing out
    Then the detail is the hidden one, not the timeout
    And a goto stopped from leaving the site says "it leads off the site, and the browser was stopped"

  Scenario: A control with no name has a hint
    When the page is captured
    Then a control with no name gets a "hint": where it sits (in the toolbar, the navigation, a dialog, a form, a table row, or a card or list item), its image's alt text, an input type the role doesn't already say, and "no size (it may open from another control)"
    And a named control's hint is empty, and a screen's identity doesn't use it
    And an image's file name is never used: it can hold a user's id

  Scenario: page_controls and the map's guide list each unnamed control with its nth
    Then an unnamed control with a hint is listed on its own, like "textbox: nth 1 (in the toolbar, no size (it may open from another control))"
    And its nth counts every control of that role with no name, as a step's "nth" does (in page_controls, toasts too)
    And on Juice Shop's start page the unnamed product buttons read like 'button: nth 1 (in a card or list item, image "Apple Juice (1000ml)")'
    And past 5 of a role, the rest are one line, like "button: nth 6 to 36 (x31 more with no name)"
    And in page_controls the named controls come first, so the 40-line cap cuts hints, not the paging controls
    And in the guide the hint and the other notes share one bracket
    And a converted Spoor map and a screen the Driver reached beyond the map keep the hint, so the guide shows it too
