"""The hard spending limit for a run (engine/budget.py, issue #255). No model calls."""

import json
from types import SimpleNamespace

import pytest

from engine import budget
from engine.client import call_tool_with_retry

_TOOL = {"name": "t", "input_schema": {"type": "object", "properties": {}}}


def _usage(input_tokens=0, output_tokens=0):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class _Client:
    """Answers every call with a valid tool call, costing what `usage` says."""

    def __init__(self, usage):
        self.calls = 0
        self.usage = usage
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        block = SimpleNamespace(type="tool_use", input={}, id="x", name="t")
        return SimpleNamespace(content=[block], stop_reason="tool_use", usage=self.usage)


def _call(client):
    return call_tool_with_retry(client, model="m", system="s", tools=[_TOOL], tool_name="t", user_message="u",
                                validate_fn=lambda data: [], max_tokens=10)


def test_the_run_stops_at_the_call_limit_before_making_the_next_call():
    budget._GUARD = budget.SpendGuard(max_cost_usd=100, max_calls=3)
    client = _Client(_usage(10, 10))
    for _ in range(3):
        _call(client)
    with pytest.raises(budget.BudgetExceeded, match="3 model calls made, the limit is 3"):
        _call(client)
    assert client.calls == 3


def test_the_run_stops_once_the_estimated_cost_reaches_the_limit():
    budget._GUARD = budget.SpendGuard(max_cost_usd=0.50, max_calls=100)
    client = _Client(_usage(output_tokens=20_000))       # $0.30 a call at $15 per million output tokens
    _call(client)
    _call(client)                                        # $0.30 spent: still under, so this one goes
    with pytest.raises(budget.BudgetExceeded, match=r"about \$0.60 spent, the limit is \$0.50"):
        _call(client)
    assert client.calls == 2


def test_limits_come_from_the_environment_and_cant_be_switched_off(monkeypatch):
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "1.5")
    monkeypatch.setenv("ENGINE_MAX_MODEL_CALLS", "40")
    guard = budget.start_run()
    assert (guard.max_cost_usd, guard.max_calls, guard.calls) == (1.5, 40, 0)
    for bad in ("0", "-1"):
        monkeypatch.setenv("ENGINE_MAX_COST_USD", bad)
        with pytest.raises(SystemExit, match="can be raised, not switched off"):
            budget.start_run()
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "lots")
    with pytest.raises(SystemExit, match="isn't a number"):
        budget.start_run()
    monkeypatch.delenv("ENGINE_MAX_COST_USD")
    monkeypatch.delenv("ENGINE_MAX_MODEL_CALLS")
    assert (budget.start_run().max_cost_usd, budget.guard().max_calls) == (3.0, 80)


def test_a_run_stopped_by_the_limit_keeps_what_it_has_and_says_why(monkeypatch, tmp_path):
    import httpx
    import engine.loop as loop
    import engine.runner as runner
    from engine.adapter import SUTAdapter
    from engine.config import RunConfig

    monkeypatch.setenv("ENGINE_MAX_MODEL_CALLS", "1")
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(200))
    monkeypatch.setattr(runner, "get_happy_day_example", lambda a: {"request": {"body": {}}, "response": {"body": {}}})
    monkeypatch.setattr(runner, "build_client", lambda: _Client(_usage(10, 10)))

    def casting(client, *a, **k):
        budget.guard().check()
        budget.guard().record(_usage(10, 10))
        return {"give_up": False, "reasoning": "r", "candidate_tests": [{"linked_hypothesis": "", "predicted_outcome": "x"}]}

    def hypothesis(client, *a, **k):
        budget.guard().check()                            # the second call: over the limit of 1
        raise AssertionError("unreachable")

    monkeypatch.setattr(loop, "get_casting_round", casting)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", hypothesis)
    adapter = SUTAdapter(name="fake_budget", display_name="Fake", base_url="http://example.invalid",
                         test_endpoint_path="/x", casting_tool_schema={}, casting_system_prompt=lambda b, f: "",
                         validate_casting_response=lambda d: [],
                         execute_test=lambda test, n: {"test_number": n, "request": {}, "response": {}},
                         render_test_entry=lambda e: "", render_onboarding_section=lambda *a: "")
    output = runner.run(adapter, RunConfig(max_checkpoints=2, out_dir=tmp_path))
    assert output["stopped_reason"] == "budget_exceeded"
    assert "1 model calls made, the limit is 1" in output["error"]
    assert json.loads((tmp_path / "output.json").read_text())["stopped_reason"] == "budget_exceeded"
    assert (tmp_path / "report.html").exists()
