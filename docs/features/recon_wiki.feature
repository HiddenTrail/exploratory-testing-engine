# The recon wiki: an ontology.json turned into one HTML page a person can read.
#
# The wiki is measurement; the model only synthesizes. Everything in it is a
# rearrangement of what the crawl recorded: states and transitions become a
# navigation map, and the evidence becomes a "Functional findings" section with every
# HTTP error, failed request, console error and exception and the state it fired in.
# build_wiki is a pure function of the ontology, so it is tested with no browser and
# no model. An optional --llm section adds one batched model review, run after the
# crawl on the recorded map. Every claim in it must cite a measurement, carry a
# confidence marker and name the rival explanation it would lose to. It never gates
# anything, and a missing key or model leaves a note instead of breaking the wiki.
#
# Code: .experiments/web-recon/wiki.py (build_wiki), synthesize.py, analyze.py

Feature: The crawler writes an HTML wiki of the map
  As someone reviewing a mapped site
  I want wiki.py to write one page with findings, observations, a navigation map and a card per state, with optional model synthesis
  So that a person can see what was mapped and what looked wrong

  Scenario: The wiki is written next to the ontology by default
    When I run "python wiki.py out/ontology.json"
    Then it writes "out/wiki.html"
    And it prints how many states, transitions, findings and observations it rendered
    # --out <path> writes it somewhere else.

  Scenario: The page has its sections in a fixed order
    When the wiki is built from an ontology
    Then the header shows the target URL, the number of states, transitions, functional findings and actions, and "read-only, no model"
    And the sections are "Functional findings", "Structural observations", "Navigation map" and "States", in that order
    And a "Model synthesis" section comes before "States" only when --llm was given

  Scenario: Findings and observations are grouped by kind
    Given an ontology with two "http_error" findings and one "dead_end" observation
    When the wiki is built
    Then "Functional findings" has a group labelled "HTTP error" with 2 rows of state, detail and action number
    And "Structural observations" has a group labelled "Dead end (no way onward)"
    And with no findings it says "No functional findings" instead

  Scenario: Graph observations are recomputed when the wiki is rendered
    # So an ontology written by any path, including one from before observations
    # existed, shows them. Drift observations from --resume are kept as written.
    Given an ontology whose stored observations include "carried_state_absent" and an outdated "dead_control"
    When I run wiki.py on it
    Then the dead, blocked, redundant and dead-end observations come from running the graph oracles again
    And the "carried_state_absent" observation is kept

  Scenario: The navigation map draws states as nodes and transitions as edges
    When the wiki is built
    Then each state is a node laid out in rows by its depth from the entry state
    And a state with any functional finding is drawn red, the others blue
    And each pair of states with a transition between them gets one edge, labelled with the first such transition's control key
    And a state with a transition back to itself is marked with a loop sign

  Scenario: Each state gets a card with what was seen there
    When the wiki is built
    Then each state's card shows its id, signature, URL and title, and its screenshot when one was saved
    And it lists the states it is reached from
    And it lists each exit with its action, effect, destination and after-screenshot
    And an exit off the site says "external site (not followed)"
    And an exit the model nominated is tagged "model-proposed", and a vetted --mutate action "vetted mutation"
    And it lists the findings fired there
    And a collapsed table lists every interactive element with its role, name, gate verdict ("committing" or "safe") and locator

  Scenario: --llm adds a model synthesis with cited, calibrated claims
    # One tool-forced "submit_review" call over a digest of states, transitions,
    # findings and observations, using the engine's client (ENGINE_USE_BEDROCK and so on,
    # read from the repo's .env).
    When I run "python wiki.py out/ontology.json --llm"
    Then the "Model synthesis" section shows a summary and a table of claims
    And each claim has the measurement it cites, a confidence of "measured", "inferred" or "speculative", and the rival it "would lose to"
    And an answer with an empty claim, cites or rival, or another confidence, is rejected by validate_review

  Scenario: A synthesis that can't run leaves a note and the rest of the wiki
    Given no model is configured, or the call fails
    When I run wiki.py with --llm
    Then the "Model synthesis" section says "(model synthesis unavailable: <error type>: <message>)"
    And the deterministic sections are written as usual
