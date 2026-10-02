# The recon safety gate: how the crawl may act on a control, or not at all.
#
# A read-only pass looks, navigates, toggles a view and types a search, but never
# commits data. plan() is a pure function of a captured element, so every rule is
# testable with no browser. It refuses whole classes of control instead of trusting one
# to look harmless; a false skip only costs coverage, a false act could change real
# data. The posture is honest, not guaranteed: a benignly named control that secretly
# writes (a "Public listing" switch that saves itself) would still get through.
# vet() is the opt-in extension for crawl --mutate: it admits only a reversible query
# submit (search, filter, sort, show), and a destructive verb is refused even then.
# The model never reaches either decision. web_gui and from_spoor use the same gate.
#
# Code: .experiments/web-recon/safety.py (plan, vet, action_plans, vetted_actions,
# safe_actions). Tests: .experiments/web-recon/tests/test_safety.py

Feature: The crawler's safety gate only allows non-committing actions
  As someone testing a real environment
  I want every control checked by fixed rules before the crawl touches it
  So that recon can't change the app or leave the site

  Scenario Outline: plan() decides click, fill or skip for each control
    Given the app's origin is "http://127.0.0.1:3000"
    And a control with role "<role>", name "<name>", type "<type>" and href "<href>"
    When plan() judges it
    Then the plan is "<plan>"
    And the reason is "<reason>"

    Examples:
      | role      | name            | type     | href                        | plan  | reason                                                    |
      | link      | About us        |          | /about                      | click | a same-origin navigation / benign control / view toggle   |
      | link      | About           |          | http://127.0.0.1:3000/about | click | a same-origin navigation / benign control / view toggle   |
      | button    | Open menu       |          |                             | click | a same-origin navigation / benign control / view toggle   |
      | tab       | Reviews         |          |                             | click | a same-origin navigation / benign control / view toggle   |
      | checkbox  | Show sold out   |          |                             | click | a same-origin navigation / benign control / view toggle   |
      | searchbox | Search products | search   |                             | fill  | a search/filter box - safe to type a query                |
      | textbox   | Postcode        |          |                             | fill  | a search/filter box - safe to type a query                |
      | button    | Delete account  |          |                             | skip  | the name 'delete account' carries a mutating verb         |
      | button    | Add to basket   |          |                             | skip  | the name 'add to basket' carries a mutating verb          |
      | button    | Go              | submit   |                             | skip  | an input of type 'submit' commits a form                  |
      | link      | Docs            |          | https://example.org/docs    | skip  | an off-site link to example.org leaves the app under test |
      | link      | Mail us         |          | mailto:a@b.c                | skip  | a mailto: link is not a navigation to follow              |
      | link      | Files           |          | ftp://127.0.0.1:3000/x      | skip  | a ftp: link is not an http navigation                     |
      | textbox   | Password        | password |                             | skip  | a sensitive field - read-only never types into it         |
      | textbox   | Email           |          |                             | skip  | a sensitive field - read-only never types into it         |
      | textbox   | Comment         |          |                             | skip  | a generic text field - read-only does not fill it         |
      | combobox  | Country         |          |                             | skip  | role 'combobox' is not a recognised actuable control      |
      | slider    | Volume          |          |                             | skip  | role 'slider' is not a recognised actuable control        |

  Scenario: A disabled control is skipped before any other rule
    Given a button named "Next" that is disabled
    When plan() judges it
    Then the plan is "skip" with reason "the control is disabled - acting would hang, not act"

  Scenario: A fill types the probe value "test" and never presses Enter
    # Enter can submit an enclosing form, a POST the gate never vetted. Live-filter
    # UIs react to the input itself; a submit-only search is missed on purpose.
    Given a search box the gate plans to "fill"
    When the crawler actuates it
    Then it types "test" into the box
    And it does not press Enter

  Scenario: With no known origin, every link naming a host is refused
    Given the app's origin is unknown
    And a link with href "http://127.0.0.1:3000/about"
    When plan() judges it
    Then the plan is "skip", because same-origin can't be confirmed
    And a relative link such as "/about" is still a "click"

  Scenario Outline: vet() admits only reversible query submits, and only under --mutate
    Given mutations are enabled
    And a control with role "<role>", name "<name>" and type "<type>"
    When vet() judges it
    Then the vetting is "<vetting>"
    And the reason is "<reason>"

    Examples:
      | role      | name            | type     | vetting       | reason                                                                |
      | searchbox | Search products | search   | submit_search | submit a search/filter query - an idempotent, reversible read         |
      | button    | Search          | submit   | submit        | a reversible query submit (search/filter/sort/show)                   |
      | button    | Go              | submit   | submit        | a reversible query submit (search/filter/sort/show)                   |
      | button    | Sort by price   |          | submit        | a reversible query submit (search/filter/sort/show)                   |
      | button    | Delete account  |          | refuse        | carries a destructive/irreversible verb - refused even under --mutate |
      | button    | Save search     |          | refuse        | carries a destructive/irreversible verb - refused even under --mutate |
      | textbox   | Password        | password | refuse        | a sensitive field - never submitted                                   |
      | textbox   | Comment         |          | refuse        | a generic text field - not a vetted query                             |
      | button    | Open menu       |          | refuse        | not an affirmatively-reversible commit - fail closed                  |
      | link      | Search          |          | refuse        | not an affirmatively-reversible commit - fail closed                  |

  Scenario: Without --mutate, vet() refuses everything
    Given mutations are not enabled
    When vet() judges a searchbox named "Search products"
    Then the vetting is "refuse" with reason "mutations are disabled - the crawl is read-only"
