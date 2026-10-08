# Each step says what the page started and stopped telling the user (#351).
#
# The Driver saw the page as controls (role and name) and signals (console, requests). It
# never saw the page's text, so it couldn't tell whether a form showed a validation
# message. In the full run runs/full340/F1 this came up at every checkpoint ("control-diff
# can't see inline error text") and the Driver conceded each validation claim. Now each
# step is followed by a read of what the page tells the user: fields marked invalid with
# their error text, error text under a field, alerts, status lines and other live regions
# (toasts, snack bars), and the browser's own required-field check, whose bubble isn't in
# the page. A field's value is never read, though a message can quote what the Driver
# typed, so lines are redacted like the server's messages (#326).
#
# Code: trailhound/adapters/web_gui/session.py (_PAGE_SAYS_JS, _INVALID_EVENTS_JS,
# page_says_lines, page_says_change, _page_says, _idle_noise, _act),
# trailhound/adapters/web_gui/adapter.py (_step_signals_html, describe_result_for_log,
# API_SCHEMA_DOC). Tests: trailhound/tests/test_page_says.py

Feature: Each step says what the page told the user
  As a Driver making a claim about validation or feedback
  I want to see the messages a step made appear or go away
  So that a claim about what the user is told can be settled either way

  Scenario: What the page tells the user is read as lines
    Given the page has a field with aria-invalid "true" and an error tied to it
    Then it reads "invalid field 'Email': Please provide an email address."
    And the error is tied to it by aria-errormessage, or by aria-describedby pointing at a mat-error, a role "alert" or an element with an error or invalid class, or else is a mat-error or role "alert" inside the same mat-form-field, .mat-mdc-form-field, .form-group or .field
    And an invalid field with no message shown reads "invalid field 'Password' (no message shown)"
    And a mat-error under a field that isn't marked invalid reads "error at 'Password': ..."
    And an element whose class names it error, invalid or danger reads "error: Invalid email or password.", or "error at '<field>': ..." inside a field's box
    And one whose class names it alert or warning reads "alert: ...", and notification, toast or snackbar reads "status: ..."
    And an element marked only by its class is left out when it holds a link, button, field or other control, since that's a panel, not a message
    And visible text in role alert, or aria-live "assertive", reads "alert: ..."
    And visible text in role status, aria-live "polite" or an output element reads "status: ..."
    And a live region's text leaves out the labels of the buttons and links inside it, so a cookie banner reads without "Me want it!"
    And a form the browser itself refuses (a required field left empty) reads "the browser refused 'Name': ..." with the browser's message, on the read after it fired only
    And that counts only while the user submits that form, by a click on its submit button or Enter in one of its fields, and only for the first field refused, the one the bubble points at
    But a page's own script calling checkValidity() isn't a refusal: it shows no bubble (PrestaShop's newsletter field on every load)
    And hidden elements, elements 1 px or smaller (a screen reader's copy of a toast) and aria-live "off" are left out
    And emails, tokens and long numbers are taken out, a field's name is cut at 60 characters, each line at 160, and the same text twice is one line
    And at most 20 lines are read, the browser's refusals always among them
    But other text in a live region (a name, an address) is not taken out: there's no allowlist, as there is for the server's message

  Scenario: Each step records what changed
    Given the page is read before the first step, after each step once the page has rested or the wait for it ran out, and after the last
    Then a step's record has "page_says" with "shown" (lines that appeared) and "gone" (lines that went away)
    And a step where nothing changed has no "page_says"
    And "the browser refused ..." is "shown" on every step that sets it off, even the same refusal as the step before, and never "gone": it's an event, not something on the page
    And each list is cut at 5 with "and N more"
    And it applies to a test with one step too

  Scenario: A step that isn't trusted gives a hint
    Given the step wasn't done, or the page hadn't rested before or after it, or the test's own signals aren't trusted
    Then the change is in "page_says_weak" instead

  Scenario: A message that comes and goes on its own isn't the step's
    Given the idle watch saw a message appear or go away while the page sat idle (a toast on every load)
    Then that message, with its digits ignored, is left out of every step's change on that state

  Scenario: The Driver, the log and the report show it
    Then the history the model reads keeps each step's "page_says" and "page_says_weak"
    And the run log line for a test says "page messages on N step(s)" when a trusted step showed any
    And the report lists under the step "the page showed ..." and "the page stopped showing ...", with "(a hint)" for a weak one
