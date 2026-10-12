"""The bootstrap pipeline keeps the spending limit settings like a run does (issue #419).
Its model calls always went through the guard, but bootstrap never started one from the
environment, so it kept the module's default limits and ignored TRAILHOUND_MAX_*. No
network or model calls: a stubbed client, schema and SUT."""

import sys

import pytest

import trailhound.bootstrap.probe as probe
from trailhound import budget
from trailhound.bootstrap import cli
from trailhound.tests.test_bootstrap_probe import (
    _FakeAnthropicClient, _canned_probe, _canned_review, _initial_schema, _tool_response,
)


def _bootstrap(monkeypatch, tmp_path, responses):
    """The CLI on a local base URL, with the model, the schema and the SUT stubbed."""
    client = _FakeAnthropicClient(responses)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_ADAPTERS_DIR", tmp_path / "adapters")
    monkeypatch.setattr(cli, "build_client", lambda: client)
    monkeypatch.setattr(cli, "discover_or_draft_schema", lambda *a: _initial_schema())
    monkeypatch.setattr(probe, "call_sut_once", lambda *a, **k: {"status": 200, "body": {"ok": True}})
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--name", "my_api", "--display-name", "My API",
                                      "--base-url", "http://127.0.0.1:8020", "--max-probes", "3"])
    cli.main()
    return client


def test_bootstrap_stops_at_the_model_call_limit_from_the_environment(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TRAILHOUND_MAX_MODEL_CALLS", "1")
    responses = [_tool_response("p1", _canned_probe()), _tool_response("r1", _canned_review())]
    with pytest.raises(SystemExit, match="Stopped by the spending limit: 1 model calls made.*Nothing was generated"):
        _bootstrap(monkeypatch, tmp_path, responses)
    assert "Spending limit: about $3.00 or 1 model calls" in capsys.readouterr().out


def test_each_bootstrap_starts_a_fresh_guard(monkeypatch, tmp_path):
    # Calls made before (another run in the same process) don't count against this one.
    budget.guard().calls = 79
    responses = [_tool_response("p1", _canned_probe()), _tool_response("r1", _canned_review("confident_enough"))]
    client = _bootstrap(monkeypatch, tmp_path, responses)
    assert client.messages.call_count == 2 and budget.guard().calls == 2
