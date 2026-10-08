# Test fully by default, and be careful only where a target is tagged careful (#299).
#
# Decided 2026-10-06: the engine is for testing. A read-only gate everywhere kept a
# webshop's basket, checkout, login and forms out of reach. So on a target, a test may
# click anything, type any value into any field, choose options, submit, add to the
# basket and check out, and open any route on the site. A tag marks what needs care:
# there the read-only safety gate decides each step, as it did everywhere before. Two
# things are refused everywhere: logging out, which ends the session every test starts
# from, and leaving the site (#308). A run says plainly which way it tests, because that
# line is what catches a run pointed at the wrong system.
#
# Code: trailhound/adapters/web_gui/careful.py (load, applies, logs_out, describe),
# session.py (_do_step, check_ready), adapter.py (SAFETY_NOTE, render_onboarding_section).
# Tests: trailhound/tests/test_careful.py, trailhound/tests/test_web_gui_adapter.py

Feature: A web run tests fully, except where the target is tagged careful
  As someone testing a product on a copy nobody depends on
  I want the Driver to use it fully, and to only look where I've said to be careful
  So that the product's real flows get tested, and nothing that needs care gets touched

  Scenario: Tags come from the target's file and the run's setting
    Given test-targets/careful/<product>.json has "routes" and "controls", and maybe "everything": true
    And WEB_GUI_CAREFUL adds routes (starting with "/" or "#") and control names for this run, comma-separated, or "*" for the whole target
    When check_ready runs
    Then the session's tags are both together

  Scenario Outline: The run says how far it may go
    Given the tags are <tags>
    Then the log, the Driver's evidence ("testing_mode") and the report's start say "<line>"

    Examples:
      | tags                        | line                                                                                           |
      | none                        | Testing fully: nothing on this target is tagged careful.                                       |
      | the route "/#/payment"      | Testing fully, except where tagged careful (routes /#/payment): there the Driver only looks.   |
      | the whole target ("*")      | Careful: this whole target is tagged careful, so the Driver only looks. ...                    |

  Scenario: Testing fully, any step may run
    Given nothing is tagged careful
    Then a test may click "Checkout" or "Add to Basket", type "-1" into a quantity, choose an option and open any route on the site

  Scenario Outline: Where tagged careful, the read-only safety gate decides
    Given the page's route or the control's name is tagged careful
    When a step <does>
    Then it is <result>

    Examples:
      | does                                       | result                                              |
      | clicks "Next page"                         | done                                                |
      | clicks "Checkout"                          | refused, "tagged careful, and the read-only safety gate refuses it" |
      | types into a search box                    | done, with the Driver's value                       |
      | types into any other field                 | refused                                             |
      | presses Escape or Tab                      | done (keys are judged in press_a_key.feature)       |
      | presses Enter in a field                   | refused                                             |

  Scenario: A careful route covers the routes under it
    Given "/#/payment" is tagged careful
    Then a step on "/#/payment" or "#/payment/confirm" is careful, and one on "/#/basket" isn't

  Scenario: Logging out is refused everywhere
    When a step clicks "Logout", "Log out", "Sign out" or "Log off", presses Enter or Space on one, or goes to a route like "/logout"
    Then it is refused: "it would log out, which ends the session every test starts from"

  Scenario: A session nobody set up is careful everywhere
    Given a Session that check_ready didn't set up
    Then every part of the target counts as careful
