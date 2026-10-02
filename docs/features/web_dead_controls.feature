# web_gui dead controls: a control counts as dead only if nothing at all moved.
#
# A control that does nothing is one of the anomalies a web run looks for. But a
# signature can't see everything: a canvas map that pans or zooms keeps the same
# route, controls and headings. So same_appearance needs three things. The signature
# stayed the same, the visible text stayed the same (web-recon's appearance, a hash of
# the page text on top of the signature), and the screenshots differ by at most 0.02
# of a downscaled frame. That threshold is the one web-recon's crawler uses, through
# the shared perceive.visual_diff. When the pixel diff can't be worked out (no
# screenshot, or Pillow missing), only the signature and text decide.
#
# Code: engine/adapters/web_gui/session.py (Session.act, _VISUAL_CHANGE_THRESHOLD),
# .experiments/web-recon/perceive.py (visual_diff), identity.py (appearance)

Feature: Dead controls are told apart from visual changes
  As someone looking for broken controls
  I want a control counted as dead only if the state, the text and the screenshot all stayed the same
  So that a canvas pan or zoom isn't reported as a dead button

  Scenario Outline: same_appearance needs the same signature, text and pixels
    Given a sent action where <change>
    When the result is worked out
    Then "screen_was" is "<screen_was>"
    And "same_appearance" is <same_appearance>

    Examples:
      | change                                                         | screen_was   | same_appearance |
      | nothing changed and the screenshots differ by 0.01             | same_screen  | true            |
      | nothing changed and the screenshots differ by exactly 0.02     | same_screen  | true            |
      | only the screenshots changed, by 0.05 (a map pan)              | same_screen  | false           |
      | only the visible text changed                                  | same_screen  | false           |
      | the signature changed to a mapped state's                      | known_screen | false           |

  Scenario: Without a pixel diff the signature and text decide
    Given a sent action where the signature and text stayed the same
    And no screenshot could be taken
    When the result is worked out
    Then "same_appearance" is true

  Scenario Outline: The outcome separates a dead control from a variant
    Given a sent action with "screen_was" "same_screen" and "same_appearance" <same_appearance>
    When outcome_for reads it
    Then the effect is "<effect>"

    Examples:
      | same_appearance | effect  |
      | true            | none    |
      | false           | variant |
