# web_gui signal trust: only signals that pass every check count as facts.
#
# A raw before/after diff looks like evidence when it isn't: background polling,
# timers, analytics and third-party calls all change things with no action at all.
# So each signal is split into two tiers (#143). "signals" holds only what passed
# every check, and the Driver is told to treat those as facts. "signals_weak" holds
# the same kinds of signal that failed a check, as hints for a next test, never
# evidence on their own. A request is the product's own if its origin matches
# exactly; a prefix check once let https://example.com.evil/ pass for
# https://example.com (Copilot on #152). A host with no dot that isn't localhost also
# counts as the product's own: PrestaShop requests http://modules/... on every load,
# a broken relative URL, and the first rule called that third-party (#146 audit).
# Screenshots are never a signal: pixels move with animations, cursors and fonts.
#
# Code: engine/adapters/web_gui/session.py (_signal_diff, _own_request, _console_key,
# _request_key), engine/adapters/web_gui/adapter.py (API_SCHEMA_DOC)

Feature: Only trustworthy signals count as evidence
  As someone who doesn't want false alarms
  I want a signal trusted only if it is the action's own effect, on the product's origin, on a settled page
  So that background noise can't become a claim, while the leads are still kept as hints

  Scenario Outline: Each trust check sends a failing item to signals_weak
    Given an action that was sent, with both reads settled
    And <item>
    When its signals are worked out
    Then it is in "<tier>"

    Examples:
      | item                                                                 | tier         |
      | a request to the product's origin, started after the click, got 500  | signals      |
      | a failed request went to "http://ads.example/pixel"                  | signals_weak |
      | a failed request matches one seen while the state sat idle           | signals_weak |
      | a console error matches one seen idle, digits aside                  | signals_weak |
      | a storage key changed that also changed while idle                   | signals_weak |
      | a control came or went that also came and went while idle            | signals_weak |
      | a console error not seen idle                                        | signals      |

  Scenario: Only requests started after the click are looked at
    Given a request was already in flight when the control was clicked
    When it fails afterwards
    Then it is not a signal of this action in either tier

  Scenario Outline: The product's own origin is an exact match
    Given the product's origin is "<origin>"
    When a request goes to "<url>"
    Then it counts as the product's own: <own>

    Examples:
      | origin                | url                                         | own   |
      | https://example.com   | https://example.com/api                     | true  |
      | https://example.com   | https://example.com:443/api                 | true  |
      | https://example.com   | https://example.com.evil/x                  | false |
      | http://127.0.0.1:8080 | http://127.0.0.1:80801/x                    | false |
      | http://127.0.0.1:8080 | http://127.0.0.1:8080/api/x                 | true  |
      | http://127.0.0.1:8080 | http://modules/blockreassurance/parcel.svg  | true  |
      | http://127.0.0.1:8080 | http://localhost:9999/x                     | false |
      | http://127.0.0.1:8080 | http://[::1]/x                              | false |
      | http://127.0.0.1:8080 | https://www.google-analytics.com/collect    | false |

  Scenario Outline: Nothing is trusted from an unsettled page or an action that wasn't sent
    Given a console error, a new cookie and a removed control after the action
    And <condition>
    When its signals are worked out
    Then "signals" has only "settled_before" and "settled_after"
    And all three are in "signals_weak", still cut at 5 with any "_more" counts added up

    Examples:
      | condition                                                     |
      | "settled_before" is false                                     |
      | "settled_after" is false                                      |
      | the action wasn't sent (the path drifted or the click failed) |

  Scenario: Screenshots are never a signal
    # The pixel diff is used only to tell a dead control from a visual change.
    Given the screenshots before and after the click differ
    When its signals are worked out
    Then no signal mentions pixels or the screenshot

  Scenario: The Driver is told how far each tier can be trusted
    When the Driver reads what a test result holds
    Then it is told that "signals" passed every trust check and to treat them as facts
    And that "signals_weak" is a hint for a next test, never evidence for a claim on its own
