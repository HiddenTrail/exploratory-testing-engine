"""Settings are named TRAILHOUND_ since the rename (#335), and the old ENGINE_ names
still work for now. A spending limit set under the old name must not be ignored."""

import pytest

from trailhound import budget, settings
from trailhound.client import use_bedrock
from trailhound.ontology.oracle_creator import context_path

NAMES = ("MAX_COST_USD", "MAX_MODEL_CALLS", "USE_BEDROCK", "CONTEXT_DIR")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(settings.PREFIX + name, raising=False)
        monkeypatch.delenv(settings.OLD_PREFIX + name, raising=False)
    monkeypatch.setattr(settings, "_warned", set())
    monkeypatch.setattr("trailhound.client.load_dotenv", lambda *a, **k: None)


def test_the_new_name_is_read_and_wins_over_the_old_one_which_is_said_to_be_ignored(monkeypatch, capsys):
    monkeypatch.setenv("TRAILHOUND_MAX_COST_USD", " 2.5 ")
    assert settings.read("MAX_COST_USD") == ("2.5", "TRAILHOUND_MAX_COST_USD")
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "0.5")              # a stricter limit, left over
    assert settings.read("MAX_COST_USD") == ("2.5", "TRAILHOUND_MAX_COST_USD")
    assert capsys.readouterr().out.strip() == (
        "ENGINE_MAX_COST_USD is set too, and ignored: TRAILHOUND_MAX_COST_USD (2.5) counts, "
        "not ENGINE_MAX_COST_USD (0.5).")


def test_the_same_value_under_both_names_says_nothing(monkeypatch, capsys):
    monkeypatch.setenv("TRAILHOUND_USE_BEDROCK", "1")
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    assert settings.read("USE_BEDROCK") == ("1", "TRAILHOUND_USE_BEDROCK")
    assert capsys.readouterr().out == ""


def test_nothing_set_reads_as_empty_under_the_new_name():
    assert settings.read("MAX_COST_USD") == ("", "TRAILHOUND_MAX_COST_USD")


def test_the_old_name_still_works_and_says_so_once(monkeypatch, capsys):
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "1.5")
    assert settings.get("MAX_COST_USD") == "1.5"
    assert settings.get("MAX_COST_USD") == "1.5"
    out = capsys.readouterr().out
    assert out.count("ENGINE_MAX_COST_USD is the old name of TRAILHOUND_MAX_COST_USD") == 1


def test_a_spending_limit_under_the_old_name_still_limits(monkeypatch):
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "0.75")
    monkeypatch.setenv("ENGINE_MAX_MODEL_CALLS", "12")
    guard = budget.start_run()
    assert (guard.max_cost_usd, guard.max_calls) == (0.75, 12)


def test_a_stop_names_the_variable_the_limit_came_from(monkeypatch):
    monkeypatch.setenv("ENGINE_MAX_MODEL_CALLS", "1")
    guard = budget.start_run()
    guard.calls = 1
    with pytest.raises(budget.BudgetExceeded, match=r"the limit is 1 \(ENGINE_MAX_MODEL_CALLS\)"):
        guard.check()
    assert budget.SpendGuard().calls_var == "TRAILHOUND_MAX_MODEL_CALLS"


def test_an_error_names_the_variable_that_was_actually_set(monkeypatch):
    monkeypatch.setenv("ENGINE_MAX_COST_USD", "0")
    with pytest.raises(SystemExit, match="^ENGINE_MAX_COST_USD must be above 0"):
        budget.start_run()
    monkeypatch.setenv("TRAILHOUND_MAX_COST_USD", "lots")
    with pytest.raises(SystemExit, match="^TRAILHOUND_MAX_COST_USD='lots' isn't a number"):
        budget.start_run()


def test_bedrock_and_the_context_folder_take_either_name(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGINE_USE_BEDROCK", "1")
    assert use_bedrock()
    monkeypatch.setenv("TRAILHOUND_USE_BEDROCK", "0")
    assert not use_bedrock()
    monkeypatch.setenv("ENGINE_CONTEXT_DIR", str(tmp_path / "old"))
    assert context_path("x") == tmp_path / "old" / "context_x.json"
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path / "new"))
    assert context_path("x") == tmp_path / "new" / "context_x.json"
