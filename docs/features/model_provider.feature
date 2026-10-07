# The model provider: the direct Anthropic API, or Amazon Bedrock.
#
# The engine talks to Claude either with an ANTHROPIC_API_KEY or through Bedrock.
# Bedrock is switched on with the engine's own variable, TRAILHOUND_USE_BEDROCK, so the
# harness you write code with (Claude Code uses CLAUDE_CODE_USE_BEDROCK) and the
# engine you run can be switched separately. Bedrock credentials come from the
# standard AWS chain; the engine handles no keys of its own for it.
#
# The default model depends on the provider. Bedrock's Messages API endpoint does
# not carry claude-sonnet-4-6, so a Bedrock run uses the nearest Sonnet. Its ids
# are not the eu.* or global.* ids that "aws bedrock list-inference-profiles"
# prints; those belong to the older InvokeModel path and are rejected here.
#
# Code: engine/client.py (use_bedrock, default_model, build_client), engine/config.py

Feature: The engine uses the direct API or Bedrock, with a model to match
  As someone setting up the engine
  I want to pick the provider with one variable and get a working default model for it
  So that a run works the same whichever way my organisation reaches Claude

  Scenario Outline: TRAILHOUND_USE_BEDROCK picks the provider and the default model
    Given TRAILHOUND_USE_BEDROCK is "<value>"
    When the engine resolves its default model
    Then the provider is <provider>
    And the default model is "<model>"

    Examples:
      | value | provider       | model                     |
      | 1     | Bedrock        | anthropic.claude-sonnet-5 |
      | true  | Bedrock        | anthropic.claude-sonnet-5 |
      | YES   | Bedrock        | anthropic.claude-sonnet-5 |
      | 0     | the direct API | claude-sonnet-4-6         |
      |       | the direct API | claude-sonnet-4-6         |

  Scenario: The variables can come from .env
    Given TRAILHOUND_USE_BEDROCK and AWS_REGION are set in .env and not in the shell
    When the engine builds its client
    Then it builds a Bedrock client for that region
    # .env is loaded when use_bedrock() runs, which is why the default model is
    # worked out when a RunConfig is created, not when the module is imported.

  Scenario: The direct API needs a key
    Given TRAILHOUND_USE_BEDROCK is not set
    And ANTHROPIC_API_KEY is not set
    When the engine builds its client
    Then it exits with "Set ANTHROPIC_API_KEY in .env, or set TRAILHOUND_USE_BEDROCK=1 to authenticate through Bedrock instead (see .env.example)"

  Scenario: Bedrock uses the region and optional profile, and ignores any API key
    Given TRAILHOUND_USE_BEDROCK is "1"
    And AWS_REGION is "eu-west-1" and AWS_PROFILE is "dev"
    And ANTHROPIC_API_KEY is also set
    When the engine builds its client
    Then it builds an AnthropicBedrockMantle client with aws_region "eu-west-1" and aws_profile "dev"

  Scenario: Bedrock falls back to AWS_DEFAULT_REGION
    Given TRAILHOUND_USE_BEDROCK is "1"
    And AWS_REGION is not set but AWS_DEFAULT_REGION is "eu-west-1"
    When the engine builds its client
    Then it builds a Bedrock client for "eu-west-1"

  Scenario: Bedrock without a region fails before any call
    Given TRAILHOUND_USE_BEDROCK is "1"
    And neither AWS_REGION nor AWS_DEFAULT_REGION is set
    When the engine builds its client
    Then it exits with a message that starts "TRAILHOUND_USE_BEDROCK is set but no region is configured"
    And the message says to set AWS_REGION (e.g. eu-west-1)

  Scenario: An explicit model wins over the provider's default
    Given TRAILHOUND_USE_BEDROCK is "1"
    When the run starts with "--model anthropic.claude-opus-5"
    Then the run's model is "anthropic.claude-opus-5"
