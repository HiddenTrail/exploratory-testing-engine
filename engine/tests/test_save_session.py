"""Saving a session for web_gui and Spoor (issue #155). No browser: the Playwright parts
are faked, and the checks that matter (never write where git would commit it, never print
a value) run before any browser starts."""

import json

import pytest

from engine.adapters.web_gui import save_session as ss
from engine.adapters.web_gui import session as live_session


def test_sessions_live_under_dot_sessions_by_product_and_name():
    assert ss.session_path("juice-shop", "logged-in") == ss.SESSIONS_DIR / "juice-shop" / "logged-in.json"
    for product, name in (("Juice Shop", "x"), ("juice-shop", "../escape"), ("", "x")):
        with pytest.raises(SystemExit):
            ss.session_path(product, name)


def test_until_takes_one_of_four_conditions():
    assert ss.parse_until("storage:token") == ("storage", "token")
    assert ss.parse_until("url:/#/search") == ("url", "/#/search")
    assert ss.parse_until(None) is None
    for bad in ("token", "header:x", "cookie:"):
        with pytest.raises(SystemExit):
            ss.parse_until(bad)


def test_only_a_path_git_ignores_counts_as_safe():
    assert ss.is_ignored(ss.SESSIONS_DIR / "juice-shop" / "logged-in.json")
    assert not ss.is_ignored(ss.REPO / "engine" / "README.md")


def test_nothing_is_written_where_it_could_be_committed():
    with pytest.raises(SystemExit, match="could be committed"):
        ss.capture_session("http://127.0.0.1:3000", ss.REPO / "engine" / "leaked-session.json",
                           until=("storage", "token"))


def test_without_a_terminal_a_condition_is_required():
    # pytest's stdin isn't a terminal, so there's no Enter to wait for.
    with pytest.raises(SystemExit, match="pass --until"):
        ss.capture_session("http://127.0.0.1:3000", ss.SESSIONS_DIR / "t" / "x.json", until=None)


class _Page:
    url = "http://127.0.0.1:3000/#/search"

    def query_selector(self, css):
        return object() if css == "#logout" else None

    def evaluate(self, js, key):
        return key == "token"


class _Context:
    def cookies(self):
        return [{"name": "token", "value": "SECRET"}]


def test_each_condition_kind_checks_the_live_page():
    page, context = _Page(), _Context()
    assert ss.condition_met(page, context, ("url", "/#/search"))
    assert not ss.condition_met(page, context, ("url", "/#/login"))
    assert ss.condition_met(page, context, ("selector", "#logout"))
    assert ss.condition_met(page, context, ("cookie", "token"))
    assert ss.condition_met(page, context, ("storage", "token"))
    assert not ss.condition_met(page, context, ("storage", "other"))


def test_the_summary_names_what_was_saved_and_never_a_value():
    state = {"cookies": [{"name": "token", "value": "SECRET"}],
             "origins": [{"origin": "http://x", "localStorage": [{"name": "token", "value": "SECRET"}],
                          "sessionStorage": [{"name": "bid", "value": "SECRET"}]}]}
    saved = ss.summary(state)
    assert saved == {"cookies": ["token"], "storage": ["token"], "session_storage": ["bid"]}
    assert "SECRET" not in repr(saved)


class _Tab:
    def __init__(self, origin, entries):
        self.answer = [origin, entries]

    def evaluate(self, js):
        if self.answer is None:
            raise RuntimeError("page closed")
        return self.answer


class _SavingContext:
    def __init__(self, pages=()):
        self.pages = list(pages)

    def storage_state(self, path=None):
        assert path is None   # save_state writes the file itself, with sessionStorage added
        return {"cookies": [{"name": "token", "value": "SECRET"}], "origins": []}


def test_a_run_can_save_the_session_it_reached_but_only_somewhere_ignored(tmp_path, monkeypatch):
    sess = live_session.Session.__new__(live_session.Session)
    sess._context = _SavingContext()
    with pytest.raises(SystemExit, match="could be committed"):
        sess.save(ss.REPO / "engine" / "leaked-session.json")
    # A temporary folder stands in for an ignored one, so the test writes nothing in the repo.
    monkeypatch.setattr(ss, "is_ignored", lambda path: True)
    target = tmp_path / "reached.json"
    assert sess.save(target) == {"cookies": ["token"], "storage": [], "session_storage": []}
    assert json.loads(target.read_text(encoding="utf-8"))["cookies"][0]["name"] == "token"


def test_sessionstorage_is_saved_per_origin_beside_playwrights_state(tmp_path):
    # Playwright's storage_state leaves sessionStorage out; Juice Shop keeps its basket id
    # there, so a session without it opened the basket with a TypeError (#228).
    closed = _Tab("http://x", [])
    closed.answer = None
    context = _SavingContext([_Tab("http://127.0.0.1:3000", [["bid", "6"]]), _Tab("null", [["x", "1"]]), closed])
    out = tmp_path / "s.json"
    assert ss.save_state(context, out)["session_storage"] == ["bid"]
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["origins"] == [{"origin": "http://127.0.0.1:3000", "localStorage": [],
                                 "sessionStorage": [{"name": "bid", "value": "6"}]}]
