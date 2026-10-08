"""A test can start with no saved session, and the model reads each step's requests (issue
#381). One test uses a real browser and is skipped where none is installed."""

import pytest

from trailhound.adapters.web_gui import adapter as adp
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _good_test


def test_a_fresh_start_is_allowed_with_a_saved_session(monkeypatch):
    monkeypatch.setattr(live_session, "_SESSION", object())
    monkeypatch.setattr(live_session, "has_session", lambda: True)
    batch = lambda **kw: {"give_up": False, "reasoning": "r", "candidate_tests": [_good_test(**kw)]}
    assert "fresh" in live_session.START_AS
    assert adp.validate_casting_response(batch(start_as="fresh")) == []
    monkeypatch.setattr(live_session, "has_session", lambda: False)
    [error] = adp.validate_casting_response(batch(start_as="fresh"))
    assert "start_as is 'fresh', but this run has no saved session" in error


def test_a_fresh_start_reads_apart_from_the_saved_tab():
    test = {"start": "/#/", "steps": [{"do": "click", "role": "button", "name": "A"}], "predicted_screen": "same_screen"}
    assert adp.describe_test_for_log({**test, "start_as": "fresh"}).startswith("/#/ :: button:A (fresh, no saved session)")
    action = {"action": "/#/ :: button:A", "verdict": "sent", "screen_before": "s", "screen_after": "s",
              "screen_was": "same_screen", "steps": []}
    fresh = adp.outcome_for({**action, "started_as": "fresh"}).action_id
    assert fresh != adp.outcome_for(action).action_id != adp.outcome_for({**action, "started_as": "new_tab"}).action_id
    assert "FRESH START" in adp.API_SCHEMA_DOC and "start fresh, with no saved session" in adp.TEST_CAPABILITIES


def test_the_model_reads_each_steps_requests_capped():
    rows = [{"step": 1, "method": "GET", "path": "/rest/user/whoami", "status": 200}] + [
        {"step": 2, "method": "PUT", "path": f"/api/Users/<n>", "status": 200 if n else None} for n in range(10)]
    entry = {"result": {"steps": [{"do": "click", "status": "done"}, {"do": "click", "status": "done"}],
                        "request_log": {"own_site": rows, "static_files": 4, "third_party": 1}}}
    [redacted] = adp.redact_history_for_model([entry])
    first, second = redacted["result"]["steps"]
    assert "request_log" not in redacted["result"]
    assert first["requests"] == ["GET /rest/user/whoami -> 200"]
    assert second["requests"][0] == "PUT /api/Users/<n> -> no answer yet"
    assert len(second["requests"]) == 9 and second["requests"][-1] == "and 2 more"
    assert "requests" not in entry["result"]["steps"][0]                 # output.json's copy is untouched


def test_a_fresh_context_gets_no_saved_session(monkeypatch, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:
        pytest.skip(f"no browser installed here ({str(exc).splitlines()[0][:60]})")
    try:
        state = tmp_path / "state.json"
        state.write_text('{"cookies": [{"name": "token", "value": "abc", "domain": "example.invalid", "path": "/",'
                         ' "expires": -1, "httpOnly": false, "secure": false, "sameSite": "Lax"}], "origins": []}',
                         encoding="utf-8")
        sess = live_session.Session.__new__(live_session.Session)
        sess._browser, sess._context, sess.session_file, sess._session_storage_js = browser, None, str(state), None
        monkeypatch.setattr(sess, "_guard_page", lambda page: None)
        for start_as, cookies in (("same_tab", ["token"]), ("new_tab", ["token"]), ("fresh", [])):
            sess._start_as = start_as
            sess._open_fresh_page()
            assert [c["name"] for c in sess._context.cookies()] == cookies, start_as
    finally:
        browser.close()
        pw.stop()
