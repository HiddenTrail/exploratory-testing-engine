# A test step can press a key (#350).
#
# A step could only click, fill, select, goto or go back, so nothing that sends on Enter,
# closes on Escape or moves focus on Tab could be tested. In the full run runs/full340/F1
# the Driver planned "fill the chat textbox then press Enter" at two checkpoints and
# clicked a Send button that doesn't exist instead, so the chatbot claim stayed open. The
# keys are a short list, what a tester needs, not shortcuts. A key press gets the same
# safety as a click: logging out is refused, the browser never leaves the site, and on a
# careful part the read-only gate judges the element the key goes to.
#
# Code: trailhound/adapters/web_gui/session.py (STEP_KINDS, PRESS_KEYS, _LOOK_KEYS,
# _press_step, _press, _focused, _actuate, _step_label, _replay_step),
# trailhound/adapters/web_gui/adapter.py (_step_errors, coverage_of, CASTING_TOOL,
# API_SCHEMA_DOC, SAFETY_NOTE). Tests: trailhound/tests/test_press_a_key.py

Feature: A test step can press a key
  As a Driver testing a chat box, a dialog or a keyboard path
  I want to press Enter, Escape, Tab and the like
  So that what only a key does can be tested at all

  Scenario: A press step names a key from the list
    Given a step with "do" "press"
    Then its "value" is one of Enter, Escape, Tab, Shift+Tab, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Space or Backspace
    And any other value is sent back with "(press) needs a key as its value, one of: ..."
    And a press that names an element ("name") needs a "role" too, and may have "nth"
    And an "nth" on a press with no element is sent back with "(press) has 'nth' but no element: give it a 'role' and 'name'"

  Scenario: The key goes to an element, or to what has focus
    Given a press step with a "role" and "name"
    Then the element is found on the live page by role and name the way a click's is, focused, and the key pressed there
    And an element that isn't there makes the step "not_found" (a press has no saved selector to fall back on)
    But a press step without a "role" presses the key on whatever has focus, after the step before (a field just filled)
    And its record says what that was in "focused", like "textbox:Text field for a chat message"
    And when the page itself has focus, the key goes to the page

  Scenario: Logging out is refused, and the browser stays on the site
    Then Enter or Space on a control whose name logs out is "refused", whether it's named or has focus
    And Tab or Escape on it is not refused: they don't press it
    And Enter in a form whose submit button's name logs out is refused the same way, since Enter submits the form through it
    And Enter or Space when something has focus that it can't tell apart (inside a component's shadow root or a frame) is "refused" everywhere, with "something has focus that it can't tell apart ..."
    And a key that takes the browser to another site is stopped, and the step "failed" with "it leads off the site, and the browser was stopped"

  Scenario: On a careful part, a key is judged like a click
    Given the part of the target the step is on is tagged careful
    Then Escape, Tab and Shift+Tab are allowed: they only move focus or close something
    And Enter and Space are allowed only on what the read-only gate would click, never in a field
    And Enter on anything in a form is "refused" when one of the form's submit buttons is on a careful part, with "Enter would submit the form, through '<button>'", even when only that button's name is tagged
    And Enter in a field, or on the page itself, is "refused" while any control on the page is tagged careful by name, with "Enter here could set off '<control>', which is on this page", since an app can wire Enter to an action with no form (Juice Shop's login has none)
    But Enter on a button or link is judged by that element's own name
    And the arrow keys and Backspace are allowed only in a box the gate would fill (a search box)
    And when it can't tell what has focus, any other key is "refused" with "it can't tell what has focus, so it can't judge what the key would do"
    And an element found only by its accessible name is "refused" for those keys with "it found the element only by its accessible name, so it can't judge what the key would do"

  Scenario: A press reads, replays and counts like other steps
    Then it reads in an action's label as "press Enter" or "press Enter on textbox:Message", with " #2" for an nth
    And a press on what had focus replays on that same element ("focused"), not on whatever has focus then
    And a screen it reaches is reached again by replaying the same key on the element, found by its selector when the page still has one control with that role and name, else by role, name and "nth" in the accessibility tree
    But a name the Driver gave only in part is looked up as the Driver wrote it, so that replay can miss, as a click's can
    And a press on a named element counts that control as tried in the area's coverage, and a press on what has focus counts nothing
