# web_gui signal audit: check signal handling against a live site, with no model calls.
#
# The trust rules for signals are only as good as the sites they were tried on. The
# signal audit runs web_gui's real act() many times against one target, across fresh
# sessions, with every chosen pair repeated, and reports the weak spots (#143, #146).
# The main one is a trusted signal that doesn't reproduce: it was treated as a fact,
# but it isn't one. It makes no model calls, so it is free to run after any change to
# how signals are captured or trusted, on more than one kind of site. The 3-site
# audit on #146 is where the carousel noise and the http://modules/ rule came from.
#
# Code: engine/adapters/web_gui/signal_audit.py (main, pick_pairs, analyse),
# engine/tests/test_signal_audit.py

Feature: Signal handling can be audited on a live site
  As someone maintaining the web adapter
  I want signal_audit to run the real actions many times and report flaky signals, flipping screen classes, unsettled reads and unstable noise
  So that weak spots in the harness are found before they show up as false findings

  Scenario: The audit runs the real actions across fresh sessions
    Given a map, a base URL and a site name
    When I run "python -m engine.adapters.web_gui.signal_audit --ontology <map> --url <url> --name <site>"
    Then it makes 4 sessions, each with its own headless browser and a baseline
    And in each it acts on up to 15 pairs, 2 times each
    And it prints progress after each session and the report as JSON at the end
    And it makes no model calls

  Scenario Outline: The audit's options
    When I run the audit with "<option>"
    Then <effect>

    Examples:
      | option              | effect                                                                    |
      | --sessions 2        | it makes 2 sessions instead of 4                                          |
      | --repeats 3         | each pair is acted on 3 times per session instead of 2                    |
      | --max-pairs 5       | it picks 5 pairs instead of 15                                            |
      | --out audit.json    | the report and every act's raw result are written to audit.json           |
      | --session <file>    | every session starts from that saved session                              |

  Scenario: Pairs are picked round-robin across states
    # So a big state doesn't take the whole budget.
    Given a map with pairs on "st01" and "st02"
    When the audit picks 2 pairs
    Then one is on "st01" and one is on "st02"

  Scenario: A trusted signal that comes and goes is a weak spot
    Given 3 reached runs of "st01 :: button:A"
    And 2 of them have the trusted signal "controls_removed: link:slide 1" and one has nothing
    When the audit analyses them
    Then "flaky_trusted" has "st01 :: button:A | controls_removed: link:slide 1 | in 2 of 3"

  Scenario: A signal a run moved to weak is demoted, not flaky
    Given 2 reached runs where one has a failed request trusted and the other has it weak
    When the audit analyses them
    Then "flaky_trusted" is empty
    And "demoted_to_weak_sometimes" is 1

  Scenario: Flipping screen classes and the reasons for weak signals are reported
    Given 3 reached runs of one pair: one "new_screen" and two "known_screen"
    And one has a weak failed request to "https://ads.example/p"
    And one wasn't sent and has a weak console error "boom"
    When the audit analyses them
    Then "flaky_screen" has "st01 :: button:A | {'new_screen': 1, 'known_screen': 2}"
    And "weak" counts "third-party | failed_requests: GET https://ads.example/p -> 0" once
    And it counts "not sent | console_errors: boom" once

  Scenario: The report's other fields
    When the audit analyses the runs
    Then the report has:
      | field                | what it is                                                                 |
      | unsettled_reads      | acts where either settled flag was false                                   |
      | unreached            | acts whose replay didn't reach the state, left out of the per-pair checks  |
      | trusted_signal_items | how many trusted signal items all acts had                                 |
      | weak                 | the 15 most common weak items, each with "not sent", "unsettled", "third-party" or "seen idle" |
      | noise_unstable       | states whose idle noise differed from one session to the next              |
      | noise_example        | the first session's idle noise for up to 3 states                          |
      | covered_by           | how often each cover was clicked through                                   |
      | wall_per_act         | the average seconds per act                                                |
    And it also has "target", "pairs", "acts", "errors" and "minutes"
