# Learning between runs: a run starts from the screens earlier runs discovered.
#
# Spoor's map never covers the whole product, so runs find screens beyond it (#157,
# #158) and the feedback step keeps them in the product's context file. Before
# #159 the next run ignored them: it started from the same map again. Now the
# web_gui preflight checks each one by replaying it, and the ones that still land
# where they did join the map the Driver is briefed with.
#
# Learning happens between runs, never between checkpoints: re-ranking mid-run would
# slow every checkpoint and break the prompt cache. The run command's --learn runs
# the feedback step when the run ends, so one command per run is enough, and the
# next run rebuilds its oracle from what this one learned. The engine's own writes
# never start a run. Earlier discoveries are read from the context file of
# WEB_GUI_PRODUCT, so this needs a product with a wiki.
#
# Code: engine/adapters/web_gui/session.py (join_earlier_discoveries, Session.reaches,
# check_ready), engine/adapters/web_gui/reference.py (add_discovery, state_label),
# engine/adapters/web_gui/adapter.py (render_onboarding_section),
# engine/ontology/feedback.py (learn, reached_at_start, merge_reached_again),
# engine/cli.py (--learn)

Feature: A run starts from the screens earlier runs discovered, and learns for the next one
  As someone running the engine against the same product again and again
  I want each run to start from what earlier runs found beyond the map
  So that testing goes deeper with every run instead of starting over

  Scenario Outline: Each earlier discovery is checked before the Driver is briefed
    Given WEB_GUI_PRODUCT is "juice-shop" and context_juice-shop.json has a discovery that <case>
    When web_gui's check_ready runs
    Then it is listed under "<outcome>" in the onboarding evidence's "earlier_discoveries"

    Examples:
      | case                                             | outcome        |
      | replays from a fresh start to the same signature | joined         |
      | replays somewhere else, or the replay fails      | not_reached    |
      | has a signature the carried map already has      | already_in_map |
      | is more than 6 steps from the start              | too_deep       |

  Scenario: At most 20 are checked, the most often reached first
    Given the context has 25 discoveries
    When check_ready checks them
    Then only the 20 with the highest "times_reached" are replayed

  Scenario: A joined screen is part of the map from the first round
    Given the earlier discovery "d79c8b1e3" at "http://127.0.0.1:3000/#/basket" joined
    Then carried_map lists it as "d79c8b1e3 (/#/basket, found by an earlier run)" with its cleared controls
    And a test may name it as its state from the first round
    And reaching it in a test is not recorded as a new discovery

  Scenario: The report lists the screens from earlier runs
    Given the onboarding evidence has "earlier_discoveries"
    When the report renders the onboarding section
    Then it has a "Screens from earlier runs" section listing the ids joined, not reached, already in the map or too deep

  Scenario: A screen reached again at the start counts as one more reach
    Given a discovery that is "seen once" in the context
    And a run's output.json lists it under onboarding_extra.earlier_discoveries.joined
    When feedback learns from that run
    Then its "times_reached" goes up by one and its status becomes "reproduced"
    And the run is added to its "runs"

  Scenario: Feedback says what this run learned compared with before
    When feedback learns from a run
    Then it prints how many screens beyond the map were new this run, how many from earlier runs were reached again at the start, and how many known ones tests found again
    And how many screens are known and how many are reproduced

  Scenario Outline: --learn runs the feedback step when the run ends
    When I run "python -m engine.cli --adapter web_gui --out-dir runs/x <learn>"
    Then <result>

    Examples:
      | learn              | result                                                                                          |
      | --learn juice-shop | after the run, its output.json is fed into context_juice-shop.json                              |
      | --learn            | after the run, its output.json is fed into the adapter's own context file, context_web_gui.json |
      |                    | nothing is written to the context layer                                                         |

  Scenario: A run that broke teaches nothing
    Given the run ends with stopped_reason "error"
    When it was started with --learn
    Then the feedback step doesn't run
