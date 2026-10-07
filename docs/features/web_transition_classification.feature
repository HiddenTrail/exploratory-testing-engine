# web_gui transition classes: a test predicts the kind of move, and the move is classified.
#
# On a first visit a screen has no name yet, so the strongest claim the Driver can
# check is the kind of move a control makes: it stays (same_screen), goes to a screen
# already known (known_screen), or goes somewhere neither the map nor this run has
# seen (new_screen). A screen is its web-recon signature: URL route, control skeleton
# and landmark headings. "Known" means in the map (including screens discovered and
# added this run) or already seen this run, which starts with the entry page read at
# the baseline. The result then becomes the engine's typed outcome through
# outcome_for, which never claims the app accepted a click it can't tell apart from a
# control that does nothing.
#
# Code: trailhound/adapters/web_gui/session.py (Session._classify, Session.act),
# trailhound/adapters/web_gui/adapter.py (execute_test, outcome_for),
# trailhound/adapters/web_gui/reference.py (PREDICTIONS)

Feature: Tests predict the kind of move, and each move is classified against the map
  As someone reading results
  I want each test to predict same_screen, known_screen or new_screen, and each action labelled the same way
  So that predictions can be checked on a first visit and unexpected navigation stands out

  Scenario: The Driver predicts one of three kinds of move
    When the Driver casts a test
    Then "predicted_screen" must be one of "same_screen", "known_screen" or "new_screen"
    And any other value is refused by the casting validator

  Scenario Outline: The screen after the click is classified against the screen before it
    Given the signature before the click is "sig-home"
    And the map has a state with the signature "sig-page2"
    And this run has already seen "sig-seen-earlier"
    When the signature after the click is "<after>"
    Then "screen_was" is "<screen_was>"

    Examples:
      | after            | screen_was   |
      | sig-home         | same_screen  |
      | sig-page2        | known_screen |
      | sig-seen-earlier | known_screen |
      | sig-brand-new    | new_screen   |

  Scenario: The result says whether the screen was mapped and whether it is a first sight
    When a test runs
    Then "was_measured_before" is true when the screen after the click is in the run's map
    And "first_sight_this_run" is true the first time this run reaches that signature

  Scenario Outline: prediction_matched compares the prediction with the class
    Given a test predicting "<predicted>"
    When the action is classified as "<screen_was>"
    Then "prediction_matched" is <matched>
    And "actual_screen" is "<screen_was>"

    Examples:
      | predicted    | screen_was   | matched |
      | known_screen | known_screen | true    |
      | same_screen  | new_screen   | false   |

  Scenario Outline: outcome_for turns the result into the engine's outcome
    Given an act result with verdict "<verdict>", screen_was "<screen_was>" and same_appearance <same_appearance>
    When outcome_for reads it
    Then the effect is "<effect>"
    And accepted is <accepted>

    Examples:
      | verdict      | screen_was   | same_appearance | effect     | accepted |
      | sent         | same_screen  | true            | none       | None     |
      | sent         | same_screen  | false           | variant    | None     |
      | sent         | known_screen | false           | transition | None     |
      | sent         | new_screen   | false           | transition | None     |
      | not_actuated | same_screen  | true            | unknown    | false    |

  Scenario: The outcome carries the states, timing and recovery
    Given a sent action that reached a new screen and recovered to the start
    When outcome_for reads it
    Then state_before is "screen_before" and state_after is "screen_after"
    And start_intended is "intended_before"
    And latency is "settle"
    And matched_prior is "was_measured_before"
    And reset_attempted is true and reset_ok is "recovered_ok"

  Scenario: An action that wasn't sent stays where it was
    Given an act result with verdict "not_actuated"
    When outcome_for reads it
    Then state_after is the same as state_before
