# Prompt caching: the static prefix and the growing test history are cached.
#
# Anthropic caches by exact byte prefix, and an entry can only end at a content
# block that carries a cache_control marker. Two earlier designs got nothing back.
# Re-serialising the whole casting log every call reshuffled the JSON closing
# brackets, so the text wasn't even append-only. One growing string was
# append-only but was one block, so the last call's boundary fell in the middle of
# this call's block, and a live loop still measured about 0 cache_read.
#
# Now each checkpoint's history is rendered once as its own fragment and its own
# content block, never touched again. A request may carry 4 markers: one goes on
# the system prompt (tools render before system, so it covers both) and up to 3
# on the history segments.
#
# Code: engine/client.py (_cache_breakpoint, _breakpoint_indexes), engine/loop.py

Feature: The static prompt and the growing test history are cached
  As someone paying for runs
  I want the unchanged part of each call to be read from the prompt cache
  So that later calls in a run cost much less than the first

  Scenario: One marker on the system prompt caches the tools and system together
    Given a call site with cache_static_content on
    When the engine calls the model
    Then the system prompt is sent as one text block with cache_control type "ephemeral"
    And no tool schema gets a cache_control marker
    # With cache_static_content off (the default) system and tools are sent as given.

  Scenario: Casting and hypothesis calls send static evidence and history as separate blocks
    Given a run on checkpoint 3
    When the engine asks for a casting round or a hypothesis
    Then the message content is one block of static evidence, then one history block per checkpoint whose tests have run so far, then the fresh evidence
    # A checkpoint where the Driver gave up ran no tests and adds no block.
    And the fresh evidence block is never marked for caching
    # The Skeptic and bug report calls only cache their system prompt and tools.

  Scenario Outline: History markers sit on the first segment and the last two
    # Last: writes the entry the next call reads. Second-to-last: where the last
    # call's entry ends. First: the run-static evidence, a floor if the pair misses.
    Given <count> cached segments
    When the engine calls the model
    Then the segments with a cache_control marker are <marked>

    Examples:
      | count | marked  |
      | 1     | 0       |
      | 2     | 0, 1    |
      | 3     | 0, 1, 2 |
      | 4     | 0, 2, 3 |
      | 7     | 0, 5, 6 |

  Scenario: A request never carries more than 4 cache markers
    Given cache_static_content on and any number of cached segments up to 60
    When the engine calls the model
    Then the markers on system, tools and segments add up to 4 or fewer

  Scenario: History grows append-only, one fragment per checkpoint
    Given checkpoint 1 has run
    When checkpoint 2's tests run
    Then one new history fragment headed "--- checkpoint 2 ---" is added after checkpoint 1's
    And checkpoint 1's fragment is byte-identical to what the last call sent
    And the static head is byte-identical on every call
    # Fragments are serialised with sorted keys so the same entries always render the same.

  Scenario: The last call's final boundary is still marked on the next call
    Given a call sent segments "base", "cp1" and "cp2"
    When the next call sends "base", "cp1", "cp2" and "cp3"
    Then "cp2" carries a marker on both calls

  Scenario: Diagnostics and Skeptic feedback stay out of the cached prefix
    # They change every checkpoint. A changing block at the end costs nothing; one
    # inside the prefix would spoil the cache for everything after it.
    When the engine asks the Driver for a hypothesis
    Then "earlier_observations", "prior_skeptic_review" and "run_diagnostics" go in the fresh evidence block
