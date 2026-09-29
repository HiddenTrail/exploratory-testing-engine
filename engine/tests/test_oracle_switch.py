"""TOKEN_PURCHASE_ORACLE=off leaves the oracle out of the Driver's evidence
(issue #42), so a run can be compared with and without it. No LLM calls."""

import importlib

import engine.adapters.token_purchase.adapter as adapter_module


def _reloaded(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TOKEN_PURCHASE_ORACLE", raising=False)
    else:
        monkeypatch.setenv("TOKEN_PURCHASE_ORACLE", value)
    return importlib.reload(adapter_module)


def test_the_ranked_oracle_is_in_the_evidence_by_default(monkeypatch):
    adapter = _reloaded(monkeypatch, None)
    assert adapter.ADAPTER.onboarding_extra["oracle_ranked"] == adapter.ORACLE_RANKED
    assert "oracle_library" not in adapter.ADAPTER.onboarding_extra


def test_off_leaves_the_oracle_out(monkeypatch):
    adapter = _reloaded(monkeypatch, "off")
    assert "oracle_ranked" not in adapter.ADAPTER.onboarding_extra
    assert adapter.ADAPTER.onboarding_extra["known_accounts"] == adapter.KNOWN_ACCOUNTS
    _reloaded(monkeypatch, None)
