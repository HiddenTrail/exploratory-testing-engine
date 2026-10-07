# State identity: is this the same screen as one already seen?
#
# A state is a place: its URL route plus the set of real controls on the page, plus
# its first visible headings. Content that changes inside one view (a map that pans, a
# feed that scrolls, "Loading" turning into "Error") is a variant of the state, not a
# new one, and an appearance hash of the visible text tells variants apart. Headings
# were added because two PoC pages, "You said yes" and "You said no", both had only a
# Back button and collapsed into one state. Identity reads controls straight off the
# DOM: on EcoEstate, a Leaflet canvas app, the accessibility snapshot was empty.
# Controls inside a live region are left out, because Juice Shop's "Force page reload"
# toast shows for about 3.5 seconds after load and made one page two states depending
# on how long the path took (issue #123). Text that says who is logged in is replaced
# by a placeholder, because Juice Shop's basket heading holds the user's email and a map
# made as one throwaway user never matched a run as another (issue #303). web_gui uses
# the same signature.
#
# Code: .experiments/web-recon/identity.py (signature, control_keys, landmark_keys,
# impersonal, appearance), perceive.py (capture, visual_diff),
# engine/adapters/web_gui/reference.py (rewrite_signatures), session.py

Feature: Screens are identified by a signature
  As someone mapping an app
  I want each state identified by its URL route, its sorted controls and its first headings
  So that the same screen is recognised across visits without relying on pixels

  Scenario: A signature is route, control skeleton and landmark headings
    Given a page at "http://127.0.0.1:3000/products?year=2021"
    And its controls are a link "  About  Us", a button "Go" and a disabled button "Off"
    And its visible headings are "Welcome", "Offers", "News" and "Footer"
    When its signature is computed
    Then the signature is "/products|button:go;button:off;link:about us|welcome;offers;news"

  Scenario Outline: What the signature leaves out
    Given two captures of the same page that differ only in <difference>
    When their signatures are computed
    Then the signatures are equal

    Examples:
      | difference                                                                     |
      | the URL query string, such as "?year=2021" versus "?year=2022"                 |
      | the URL fragment                                                               |
      | the visible body text                                                          |
      | the order the controls were read in                                            |
      | an element with role "generic" (the page container whose name is all its text) |
      | a button inside an "aria-live", "role=alert" or "role=status" region (a toast) |
      | a fourth or later heading                                                      |
      | who is logged in, such as "Your Basket (trailhound-147eb336@example.test)"     |

  Scenario Outline: What makes two captures different states
    Given two captures that differ in <difference>
    When their signatures are computed
    Then the signatures differ

    Examples:
      | difference                                                                |
      | the URL path                                                              |
      | one has a control the other lacks                                         |
      | a control's role or its normalised name                                   |
      | one of the first three headings, such as "You said yes" and "You said no" |

  Scenario: Controls are named in lowercase with whitespace collapsed, headings cut to 60 characters
    Given a control named "  Open   Sidenav " with role "button"
    And a visible heading 80 characters long
    When the signature is computed
    Then the control appears as "button:open sidenav"
    And the heading appears as its first 60 characters, lowercased

  Scenario: Emails and generated ids are replaced before the signature is made
    Given a heading "Your Basket (trailhound-147eb336@example.test)" and a control "Signed in as a.b@x.co.uk"
    When the signature is computed
    Then the heading appears as "your basket (<email>)" and the control as "menuitem:signed in as <email>"
    And a UUID or a run of 16 or more hex characters appears as "<id>"
    And short numbers, like "page 2 of 37" or "order #1234", stay as they are
    And this happens before a heading is cut to 60 characters, so an email isn't cut in half first

  Scenario: A map or discovery saved before #303 still matches
    Given a map or an earlier run's discovery whose signature still holds an email
    When web_gui loads it
    Then its signatures are made impersonal the same way, which gives the signature made now

  Scenario: The appearance tells variants of one state apart
    Given two captures with the same signature
    And their visible body text differs
    When their appearances are computed
    Then each appearance is the signature, "#", and a 12-character hash of the normalised visible text
    And the two appearances differ

  Scenario: The visual diff measures how much of a screenshot changed
    # Shared by the crawler and web_gui, so both judge "did nothing" the same way.
    # Stretching the contrast first makes a change on a pale map or a mostly white page
    # register; an unchanged frame stays at 0.0.
    Given a screenshot before and a screenshot after an action
    When the visual diff is computed
    Then both are made grayscale, contrast-stretched ignoring the 1% extremes, and shrunk to 64x64
    And the result is the fraction of the 4096 cells whose value moved by more than 20

  Scenario: The visual diff gives no answer when it can't compare
    Given a missing screenshot, an unreadable one, or no Pillow installed
    When the visual diff is computed
    Then the result is None
    And the crawler then treats the action as having made no visual change
