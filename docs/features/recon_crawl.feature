# The web-recon crawler: a read-only map of a site, without Spoor.
#
# crawl.py explores a web app by frontier breadth-first search: list each state's safe
# actions (from the DOM, filtered by the safety gate), go to the nearest state that
# still has an untried one by replaying its discovery path from the start URL, act,
# and record where it led plus any evidence the oracles found. Replay from the start
# works for single-page apps whose "navigation" is a click. It waits for the network
# to go idle first, because apps fetch their data after first paint (EcoEstate renders
# its controls only once the fetch resolves). When the DOM says an action changed
# nothing, a screenshot diff confirms it before the control is called dead, so a
# canvas pan or zoom isn't a false dead. No model by default. This lives in
# .experiments/ but the engine loads it at run time (web_gui reuses its perception,
# identity and safety gate).
#
# Code: .experiments/web-recon/crawl.py, perceive.py (capture, visual_diff), propose.py

Feature: The read-only crawler maps a site from its start URL
  As someone onboarding a web app without Spoor
  I want crawl.py to explore a site and record its states, controls and transitions into ontology.json
  So that there is a map, with screenshots and evidence, even when Spoor isn't available

  Scenario: A crawl explores breadth-first, real controls before gestures
    # Defaults: start URL "http://localhost:5173/", --max 40 actions, --out "out/ontology.json".
    When I run "python crawl.py http://127.0.0.1:3000 --max 40 --out out/ontology.json"
    Then the start page is captured and registered as state "st01"
    And each next action is the first untried one on the state with the shortest discovery path
    And a state whose next untried action is a real control comes before one whose next is a gesture probe
    And the crawl stops after 40 actions that landed, or when nothing is left to try
    And the ontology is saved with schema "web-recon/1", its states, transitions, findings and observations
    # Before every capture and every action the page is settled: it waits for the
    # "networkidle" load state for up to 5 seconds, then another 900 ms.
    And each new state's screenshot is saved as "out/images/<state id>.png" and recorded as its "image"
    And each action's after-screenshot is saved as "out/images/act<NNN>.png" and recorded as the transition's "after_image"

  Scenario Outline: Reaching a state replays its path, and a replay that goes wrong is recorded
    # Before every action the crawler goes back to the start URL and replays the
    # state's discovery path, so a stray effect never compounds. A control is tried at
    # most 2 times (MAX_ACTION_ATTEMPTS) before it is given up.
    Given state "st03" was first reached by a path of 2 clicks
    When the crawler replays that path to try an action on "st03" and <what happens>
    Then a "state_unstable" finding is recorded on "st03" with summary "st03: <why>"

    Examples:
      | what happens                                   | why                                          |
      | a step in the path can't be actuated           | could not replay action on <the step's name> |
      | the page it lands on has a different signature | replaying the path reached a different state |

  Scenario: A click tries every reasonable way to reach the control, then records it blocked
    # Only controls the safety gate already cleared reach the ladder, so trying harder
    # makes reaching them more reliable without widening what may be touched.
    Given a control the gate cleared for a click
    When the crawler clicks it
    Then it tries in order: a unique role and accessible-name locator, the captured CSS path, scroll into view then the CSS path, a dispatched "click" event, a forced click
    And if all of them fail on the 2nd attempt, a transition with effect "blocked" is recorded back to the same state
    And a blocked control is not a functional finding

  Scenario Outline: Each action's effect is classified from the before and after captures
    Given the crawler acted on a control on state "st01"
    When <after>
    Then the transition's effect is "<effect>"

    Examples:
      | after                                                                       | effect   |
      | the page's signature differs                                                | navigate |
      | the signature is the same but the visible text hash differs                 | changed  |
      | signature and text are the same but over 2% of a 64x64 screenshot changed   | changed  |
      | signature, text and screenshot are all the same                             | dead     |
      | the page ended up on another origin (the crawler then reboots to the start) | external |

  Scenario: Every state is also probed with gestures, recorded as self-transitions
    # A drag over a slider or drag-drop could mutate; the reboot before every action
    # bounds that risk.
    When the crawler registers a new state
    Then it adds 6 gesture probes at the viewport centre: "hover centre", "wheel down", "wheel up", "ctrl+wheel zoom in", "ctrl+wheel zoom out", "drag-pan centre"
    And a gesture never creates a new state or a discovery-path step
    And its transition goes back to the state it was tried on, with effect "changed" or "dead"
    And the observation oracles still run on the page after it

  Scenario: --resume carries an earlier map forward and reports drift
    Given an earlier crawl wrote "prior.json"
    When I run crawl.py with "--resume prior.json"
    Then a state whose signature is in "prior.json" is marked "carried" true
    And each state in "prior.json" not reached this run gets a "carried_state_absent" observation
    And each state not in "prior.json" gets a "new_state" observation
    And the ontology's session records "resumed_from_states"

  Scenario: --llm lets a model nominate controls the DOM scan missed, and the gate still decides
    # Off by default. Without the engine's auth it prints that the proposer is
    # unavailable and the crawl stays deterministic. A failed call gives no candidates.
    When I run crawl.py with "--llm"
    Then each newly registered state gets at most 8 model nominations, each a role and a name
    And a nomination is dropped if it duplicates a known control, matches no unique enabled element by exact role and name, or the safety gate refuses it
    And a kept nomination is tested like any other control, with action origin "llm"

  Scenario: --mutate also tries vetted, reversible query submits
    # Off by default. A search box is then filled with "test" and Enter is pressed;
    # without --mutate it is only filled, never submitted.
    When I run crawl.py with "--mutate"
    Then each control that safety.vet admits gets an extra action with locator "__mutate__:<kind>:<css>" and origin "mutation"
    And a destructive control is still never actuated
