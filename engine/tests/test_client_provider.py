"""Provider selection: which client build_client() constructs and which model
ID default_model() hands back, driven by ENGINE_USE_BEDROCK. No network calls -
constructing a client doesn't authenticate, so these stay offline."""

import pytest
from anthropic import Anthropic, AnthropicBedrockMantle

from engine.client import (
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_MODEL,
    build_client,
    default_model,
    use_bedrock,
)
from engine.config import RunConfig

_AUTH_VARS = (
    "ENGINE_USE_BEDROCK",
    "ANTHROPIC_API_KEY",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """The real .env would otherwise leak a working ANTHROPIC_API_KEY into the
    missing-key cases, so load_dotenv is stubbed out and every auth variable is
    cleared - each test sets only what it's actually exercising."""
    monkeypatch.setattr("engine.client.load_dotenv", lambda *a, **k: None)
    for var in _AUTH_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes"])
def test_use_bedrock_accepts_the_documented_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", value)
    assert use_bedrock() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", " "])
def test_use_bedrock_is_false_for_anything_else(monkeypatch, value):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", value)
    assert use_bedrock() is False


def test_use_bedrock_is_false_when_unset():
    assert use_bedrock() is False


def test_default_model_is_the_direct_api_model_by_default():
    assert default_model() == DEFAULT_MODEL


def test_default_model_switches_to_the_bedrock_inference_profile(monkeypatch):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    assert default_model() == DEFAULT_BEDROCK_MODEL


def test_bedrock_default_uses_a_plain_anthropic_prefixed_id():
    # Guards the mistake this cost a live 404 to find: the eu.*/global.*
    # inference-profile IDs from `aws bedrock list-inference-profiles` are the
    # bedrock-runtime InvokeModel form and are rejected by the Messages endpoint.
    assert DEFAULT_BEDROCK_MODEL.startswith("anthropic.")
    assert not DEFAULT_BEDROCK_MODEL.startswith(("eu.", "global.", "us."))


def test_build_client_returns_a_direct_api_client_when_a_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = build_client()
    assert isinstance(client, Anthropic)


def test_build_client_without_a_key_or_bedrock_explains_both_options(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        build_client()
    message = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "ENGINE_USE_BEDROCK" in message


def test_build_client_returns_a_bedrock_client_when_enabled(monkeypatch):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    client = build_client()
    assert isinstance(client, AnthropicBedrockMantle)


def test_build_client_accepts_aws_default_region_as_the_fallback(monkeypatch):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert isinstance(build_client(), AnthropicBedrockMantle)


def test_build_client_in_bedrock_mode_ignores_any_anthropic_api_key(monkeypatch):
    # Both set is the state a half-finished migration leaves behind; the
    # explicit switch has to win, or the run silently bills the wrong provider.
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(build_client(), AnthropicBedrockMantle)


def test_build_client_in_bedrock_mode_without_a_region_fails_actionably(monkeypatch):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    with pytest.raises(SystemExit) as excinfo:
        build_client()
    assert "AWS_REGION" in str(excinfo.value)


def test_run_config_default_model_follows_the_provider(monkeypatch):
    assert RunConfig().model == DEFAULT_MODEL
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    assert RunConfig().model == DEFAULT_BEDROCK_MODEL


def test_run_config_explicit_model_still_wins(monkeypatch):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    assert RunConfig(model="some-other-model").model == "some-other-model"
