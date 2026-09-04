"""Can a SUT that is not a web service be an adapter at all?

The checkpoint loop only ever calls `adapter.execute_test`, so the engine has
always been *described* as SUT-agnostic. It wasn't quite: a run could not begin
against anything without a URL, because the readiness probe and the happy-day
fetch were written out inline in `runner.py` and `loop.py`. Those are now the
defaults behind two adapter hooks, and this file is the check that the move was
real rather than cosmetic.

The test that carries the weight is
`test_a_non_http_adapter_runs_without_touching_httpx`. Adding the hooks and
having the existing suite still pass would prove nothing - the existing adapters
take the default path either way. Making every entry point of `httpx` raise on
contact is what distinguishes "the HTTP call is behind a hook" from "the HTTP
call is behind a hook and also still happening".
"""

import httpx
import pytest

import engine.runner as runner
from engine.adapter import SUTAdapter, validate_adapter


def _adapter(**overrides) -> SUTAdapter:
    """A valid adapter with the reach fields left to the caller.

    Everything here except the reach fields is required by `_REQUIRED_FIELDS`
    and is deliberately inert: these tests are about whether a run can *start*,
    so nothing below is ever called.
    """
    base = dict(
        name="reach_test",
        display_name="Reach",
        casting_tool_schema={},
        casting_system_prompt=lambda budget, is_first: "",
        validate_casting_response=lambda data: [],
        execute_test=lambda test, test_number: {},
        render_test_entry=lambda entry: "",
        render_onboarding_section=lambda *a: "",
    )
    return SUTAdapter(**{**base, **overrides})


def _reachable_by_hooks(**overrides) -> SUTAdapter:
    """An adapter for a SUT with no URL: both hooks, no HTTP fields."""
    hooks = dict(
        check_sut_ready=lambda adapter: None,
        fetch_happy_day_example=lambda adapter: {
            "request": {"gesture": "tap", "at": [0.5, 0.9]},
            "response": {"verdict": "allowed"},
        },
    )
    return _adapter(**{**hooks, **overrides})


# --- validation --------------------------------------------------------------

def test_an_adapter_with_no_url_but_both_hooks_is_valid():
    """The whole point of the change. Before it, this adapter was rejected for
    missing `base_url` - a field it has no meaning for."""
    validate_adapter(_reachable_by_hooks())


def test_an_http_adapter_is_still_valid_with_no_hooks_at_all():
    """The two shipped adapters supply neither hook, and must keep working
    without being touched. If this needed a change, the defaults are not
    defaults."""
    validate_adapter(_adapter(base_url="http://example.invalid", test_endpoint_path="/x"))


def test_an_adapter_that_supplies_no_way_to_reach_its_sut_is_rejected():
    """Dropping base_url from the required list must not turn a misconfigured
    adapter into one that fails at the first call instead of at validation. The
    message has to say what to do, because this is the error a new adapter's
    author sees first."""
    with pytest.raises(ValueError) as raised:
        validate_adapter(_adapter())
    message = str(raised.value)
    assert "no way to reach its SUT" in message
    assert "base_url" in message and "check_sut_ready" in message


@pytest.mark.parametrize("hook", ["check_sut_ready", "fetch_happy_day_example"])
def test_overriding_only_one_reach_hook_is_rejected(hook):
    """The genuinely dangerous case, and the reason the rule is "both or
    neither" rather than "at least one". An adapter that overrides only the
    readiness probe passes the probe and then falls back to the *HTTP*
    happy-day fetch - so a non-HTTP SUT reports itself ready and then dies on a
    connection error, at the one moment the run looked like it had started."""
    with pytest.raises(ValueError) as raised:
        validate_adapter(_adapter(**{hook: lambda adapter: None}))
    assert hook in str(raised.value)
    assert "both or neither" in str(raised.value).lower()


# --- the run actually starts -------------------------------------------------

def _stub_a_finished_loop(monkeypatch):
    """Replace the checkpoint loop with one completed, anomaly-free checkpoint.

    The loop is not what these tests are about and running it would need an API
    key. The shape has to satisfy `render_report`, which is the point at which a
    half-built stub shows up as a KeyError rather than as a skipped assertion.
    """
    monkeypatch.setattr(runner, "build_client", lambda: object())
    monkeypatch.setattr(
        runner, "run_checkpoint_loop",
        lambda *a, **k: ([], [{
            "checkpoint": 1,
            "hypothesis": {"observed_behavior": "b", "anomalies": [], "untested_areas": [],
                           "prior_gaps_response": []},
            "skeptic_review": {"verdict": "strong_enough", "gaps": [],
                               "coverage_breadth": {"material": False, "note": ""},
                               "anomaly_checks": [], "recommended_next_tests": [],
                               "prior_critique_addressed": "n/a"},
        }], "skeptic_satisfied"),
    )


@pytest.fixture
def httpx_is_a_trap(monkeypatch):
    """Every way out of httpx raises. Nothing here is a real network guard - it
    is an assertion, expressed as a fixture, that the code under test does not
    reach for HTTP at all."""
    def explode(*args, **kwargs):
        raise AssertionError("the engine reached for HTTP against a non-HTTP SUT")

    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(httpx, "request", explode)
    monkeypatch.setattr(httpx, "Client", explode)


def test_a_non_http_adapter_runs_without_touching_httpx(monkeypatch, tmp_path, httpx_is_a_trap):
    """Readiness and happy-day both come from the adapter, and the run reaches
    the checkpoint loop. The loop itself is stubbed - it is not what is being
    tested, and running it would need an API key."""
    from engine.config import RunConfig

    _stub_a_finished_loop(monkeypatch)

    output = runner.run(_reachable_by_hooks(), RunConfig(out_dir=tmp_path))

    assert output["stopped_reason"] == "skeptic_satisfied"
    assert output["anomaly_found"] is False
    assert output["happy_day_example"]["response"] == {"verdict": "allowed"}


def test_the_console_line_survives_a_happy_day_example_with_no_body(capsys, monkeypatch, tmp_path,
                                                                   httpx_is_a_trap):
    """`runner` printed `happy_day_example['request']['body']` directly, which is
    the last place in generic code that assumed an HTTP shape. A gesture has no
    body, and a KeyError there would abort a run that was otherwise fine - so it
    falls back to printing the whole half."""
    from engine.config import RunConfig

    _stub_a_finished_loop(monkeypatch)

    runner.run(_reachable_by_hooks(), RunConfig(out_dir=tmp_path))

    printed = capsys.readouterr().out
    assert "'verdict': 'allowed'" in printed


def test_a_readiness_hook_that_refuses_stops_the_run_before_any_casting(monkeypatch, tmp_path,
                                                                       httpx_is_a_trap):
    """The hook's contract is to raise SystemExit, not to return a flag, and the
    reason is cost: a run against a SUT that isn't there should not discover
    that after paying for a casting round.

    `build_client` still runs first - it has always been ordered that way and it
    makes no network call - so the claim worth asserting is that nothing was
    *cast*, and that `run` propagates the exit rather than catching it into a
    `stopped_reason` and writing a report about a SUT it never reached.
    """
    from engine.config import RunConfig

    monkeypatch.setattr(runner, "build_client", lambda: object())

    def never(*a, **k):
        raise AssertionError("a casting round was paid for despite the SUT not being ready")

    monkeypatch.setattr(runner, "run_checkpoint_loop", never)

    def refuse(adapter):
        raise SystemExit("the emulator isn't running - start it first.")

    with pytest.raises(SystemExit, match="emulator isn't running"):
        runner.run(_reachable_by_hooks(check_sut_ready=refuse), RunConfig(out_dir=tmp_path))
    assert not (tmp_path / "output.json").exists(), "no report for a SUT that was never reached"
