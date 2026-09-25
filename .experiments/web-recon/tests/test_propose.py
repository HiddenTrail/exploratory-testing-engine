"""The optional model proposer: its pure digest/validation/parse, and one fake-client call.

No network and no browser - the real call runs only behind `crawl --llm`. These pin the
contract the crawler relies on: a nomination is shape-checked, capped, deduped, and a
quote-bearing or off-list nomination is dropped before the crawler ever tries to resolve it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from propose import (  # noqa: E402
    MAX_CANDIDATES, parse_candidates, propose, propose_digest, validate_candidates)


class _Obs:
    """A minimal Observation stand-in for the pure digest."""
    url = "http://localhost/x"
    title = "X"
    headings = ["Welcome"]
    text = "some visible text"
    elements = [{"role": "button", "name": "Search"}]


def test_digest_lists_what_was_measured():
    d = propose_digest(_Obs())
    assert "http://localhost/x" in d and "Welcome" in d
    assert "button: Search" in d and "some visible text" in d


def test_digest_truncates_long_text():
    obs = _Obs()
    obs.text = "x" * 5000
    d = propose_digest(obs, max_text=100)
    assert "..." in d and len(d) < 1000


def test_validate_accepts_a_good_payload():
    data = {"candidates": [{"role": "button", "name": "Zoom", "why": "icon"}]}
    assert validate_candidates(data) == []


def test_validate_rejects_bad_role_and_empty_name():
    data = {"candidates": [{"role": "slider", "name": "x", "why": "y"},
                           {"role": "button", "name": "", "why": "y"}]}
    errors = validate_candidates(data)
    assert any("role" in e for e in errors) and any("name" in e for e in errors)


def test_validate_rejects_non_object():
    assert validate_candidates([]) and validate_candidates({"candidates": "no"})


def test_parse_drops_quotes_off_list_roles_and_dupes():
    data = {"candidates": [
        {"role": "button", "name": 'He said "hi"', "why": "q"},   # quote -> dropped
        {"role": "listbox", "name": "L", "why": "off-list"},       # off-list role -> dropped
        {"role": "link", "name": "Home", "why": "a"},
        {"role": "link", "name": "home", "why": "dupe (case-insensitive)"},  # dupe -> dropped
    ]}
    out = parse_candidates(data)
    assert [(c["role"], c["name"]) for c in out] == [("link", "Home")]


def test_parse_caps_the_list():
    data = {"candidates": [{"role": "button", "name": f"b{i}", "why": "x"}
                           for i in range(MAX_CANDIDATES + 5)]}
    assert len(parse_candidates(data)) == MAX_CANDIDATES


class _FakeClient:
    """Stands in for engine.client: call_tool_with_retry drives it through the real
    validate_fn, so this exercises propose() end to end without a model."""
    def __init__(self, payload):
        self._payload = payload

    class _messages:
        pass


def test_propose_returns_parsed_candidates_via_call_tool(monkeypatch):
    import propose as mod
    captured = {}

    def fake_call(client, **kw):
        captured.update(kw)
        # emulate the tool-runner having validated and returned the tool input
        errs = kw["validate_fn"]({"candidates": [{"role": "button", "name": "Menu", "why": "icon"}]})
        assert errs == []
        return {"candidates": [{"role": "button", "name": "Menu", "why": "icon"}]}

    monkeypatch.setattr(mod, "call_tool_with_retry", fake_call)
    out = propose(_Obs(), client=object(), model="m")
    assert out == [{"role": "button", "name": "Menu", "why": "icon"}]
    assert captured["tool_name"] == "propose_interactables"
