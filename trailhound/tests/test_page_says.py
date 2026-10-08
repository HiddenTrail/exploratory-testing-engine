"""What the page tells the user, step by step (issue #351). One test uses a real browser
and is skipped where none is installed; the rest need none."""

import pytest

from trailhound.adapters.web_gui import adapter as adp
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _acting_session, _Obs


def test_each_kind_reads_as_one_redacted_line():
    lines = live_session.page_says_lines([
        {"kind": "invalid", "field": "Email", "text": "Please provide an email address."},
        {"kind": "invalid", "field": "Password", "text": ""},
        {"kind": "error", "field": "Repeat Password", "text": "Passwords do not match"},
        {"kind": "error", "field": "", "text": "Something is wrong"},
        {"kind": "alert", "text": "Invalid email  or\npassword for jim@juice-sh.op"},
        {"kind": "status", "text": "Code 1234567 sent"},
        {"kind": "status", "text": "Passwords do not match"},          # a screen reader's copy
        {"kind": "status", "text": "a long toast " * 30}])
    assert lines[:6] == ["invalid field 'Email': Please provide an email address.",
                         "invalid field 'Password' (no message shown)",
                         "error at 'Repeat Password': Passwords do not match",
                         "error: Something is wrong",
                         "alert: Invalid email or password for <email>",
                         "status: Code <n> sent"]
    assert len(lines) == 7 and lines[6].endswith("...") and len(lines[6]) == live_session._PAGE_SAYS_CHARS


def test_a_step_records_what_appeared_and_what_went_away():
    before, after = ["status: 1 - 12 of 35", "alert: Welcome"], ["status: 13 - 24 of 35", "alert: Welcome"]
    assert live_session.page_says_change(before, after, set(), trusted=True) == {
        "page_says": {"shown": ["status: 13 - 24 of 35"], "gone": ["status: 1 - 12 of 35"]}}
    assert live_session.page_says_change(before, before, set(), trusted=True) == {}       # a quiet step adds nothing
    # Not trusted: the same, as a hint.
    assert "page_says_weak" in live_session.page_says_change([], ["alert: x"], set(), trusted=False)


def test_a_long_change_is_cut_and_the_browsers_check_is_never_gone():
    many = [f"status: toast {n}" for n in range(7)]
    assert live_session.page_says_change([], many, set(), True)["page_says"]["shown"] == many[:5] + ["and 2 more"]
    check = "the browser refused 'Name': Please fill out this field."
    assert live_session.page_says_change([check], [], set(), True) == {}
    # Found in review: the same refusal again on the next step was dropped as unchanged.
    assert live_session.page_says_change([check], [check], set(), True) == {"page_says": {"shown": [check]}}
    assert live_session.page_says_lines([{"kind": "browser_check", "field": "Name", "text": "Please fill out this field."}]) == [check]


def test_a_message_that_also_comes_and_goes_while_idle_isnt_the_steps():
    noise = {live_session._console_key("status: Language changed to English 2")}
    change = live_session.page_says_change(["status: Language changed to English 7"],
                                           ["invalid field 'Email': Required"], noise, trusted=True)
    assert change == {"page_says": {"shown": ["invalid field 'Email': Required"]}}


def test_each_step_of_a_test_gets_its_own_change(monkeypatch):
    after = _Obs(elements=[{"role": "button", "name": "A", "locator": "#a"}])
    after.url = "http://app.example/"
    sess = _acting_session(monkeypatch, after)
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#a"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/")
    sess.careful = {"everywhere": False, "routes": [], "controls": []}
    readings = iter([[], ["invalid field 'Email': Please provide an email address."], []])
    monkeypatch.setattr(sess, "_page_says", lambda: next(readings))
    result = sess.act_steps("st01", [{"do": "click", "role": "button", "name": "A"},
                                     {"do": "click", "role": "button", "name": "B"}])
    first, second = result["steps"]
    assert first["page_says"] == {"shown": ["invalid field 'Email': Please provide an email address."]}
    assert second["page_says"] == {"gone": ["invalid field 'Email': Please provide an email address."]}


def _one_step(monkeypatch, readings, rests=()):
    after = _Obs(elements=[{"role": "button", "name": "A", "locator": "#a"}])
    after.url = "http://app.example/"
    sess = _acting_session(monkeypatch, after)
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#a"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/")
    sess.careful = {"everywhere": False, "routes": [], "controls": []}
    readings, rests = iter(readings), iter(rests)
    monkeypatch.setattr(sess, "_page_says", lambda: next(readings))
    monkeypatch.setattr(sess, "_rest", lambda: next(rests, True))
    return sess.act_steps("st01", [{"do": "click", "role": "button", "name": "A"}])


def test_a_one_step_test_gets_it_and_an_unrested_step_gives_a_hint(monkeypatch):
    [step] = _one_step(monkeypatch, [[], ["error: Invalid email or password."]])["steps"]
    assert step["page_says"] == {"shown": ["error: Invalid email or password."]}
    [step] = _one_step(monkeypatch, [[], ["error: Invalid email or password."]], rests=[False])["steps"]
    assert "page_says" not in step and step["page_says_weak"] == {"shown": ["error: Invalid email or password."]}


def test_the_idle_watch_learns_the_messages_that_come_and_go(monkeypatch):
    sess = live_session.Session.__new__(live_session.Session)
    sess._requests = {}
    sess.col = type("C", (), {"drain": lambda self: ([], [])})()
    sess.page = type("P", (), {"wait_for_timeout": lambda self, ms: None})()
    readings = iter([["status: 1 - 12 of 35", "alert: Language changed 1"], ["status: 1 - 12 of 35"],
                     ["status: 1 - 12 of 35"], ["status: 1 - 12 of 35", "alert: Welcome back"]])
    for name, fn in (("_storage", lambda: {}), ("_controls_now", lambda: set()), ("_page_says", lambda: next(readings))):
        monkeypatch.setattr(sess, name, fn)
    noise = sess._idle_noise()
    assert noise["page_says"] == {"alert: Language changed #", "alert: Welcome back"}     # never the steady one


def test_the_driver_keeps_it_and_the_report_shows_it():
    step = {"do": "click", "role": "button", "name": "Log in", "status": "done",
            "page_says": {"shown": ["invalid field 'Email': Required"]},
            "page_says_weak": {"gone": ["alert: Welcome"]}}
    entry = {"test_number": 1, "result": {"steps": [step]}}
    [redacted] = adp.redact_history_for_model([entry])
    assert redacted["result"]["steps"][0]["page_says"] == {"shown": ["invalid field 'Email': Required"]}
    assert redacted["result"]["steps"][0]["page_says_weak"] == {"gone": ["alert: Welcome"]}
    line = adp.describe_result_for_log({"result": {"verdict": "sent", "screen_was": "same_screen", "settle": 0.4,
                                                   "reached_target_state": True, "steps": [step, step]}})
    assert line.endswith("page messages on 2 step(s)")
    html = adp._steps_html([step])
    assert "the page showed invalid field &#x27;Email&#x27;: Required" in html
    assert "the page stopped showing alert: Welcome (a hint)" in html


def test_the_page_is_read_in_a_real_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:
        pytest.skip(f"no browser installed here ({str(exc).splitlines()[0][:60]})")
    try:
        page = browser.new_page()
        page.set_content("""
          <form id="native"><label for="n">Name</label><input id="n" required><input id="age" aria-label="Age" required>
            <button>Send</button></form>
          <mat-form-field><label for="e">Email</label>
            <input id="e" aria-invalid="true" aria-describedby="e-err">
            <mat-error id="e-err">Please provide an email address.</mat-error></mat-form-field>
          <mat-form-field><label for="p">Password</label><input id="p">
            <mat-error>Password must be 5-40 characters long.</mat-error></mat-form-field>
          <label for="c">City</label><input id="c" aria-invalid="true" aria-errormessage="c-err"><span id="c-err">Pick a city.</span>
          <div class="form-group"><input aria-label="Zip" aria-invalid="true"><div class="invalid-feedback">Zip is too short.</div></div>
          <div class="error">Invalid email or password.</div>
          <div class="alert alert-warning">Your session ends soon.</div>
          <div class="notification-panel"><a href="#">Read all</a> 3 new</div>
          <div role="dialog" aria-live="polite">We use cookies. <a href="#">Learn more</a><button>Me want it!</button></div>
          <div aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden">Old toast</div>
          <div role="alert">The server is busy.</div>
          <div aria-live="polite"><span>Added to basket</span></div>
          <div role="status" style="display:none">hidden toast</div>
          <div aria-live="off">not live</div>""")
        # set_content doesn't run init scripts, so the listener goes in by hand here.
        page.evaluate(live_session._INVALID_EVENTS_JS)
        # A page's own checkValidity() shows no bubble, so it isn't a refusal (PrestaShop).
        page.evaluate("document.getElementById('age').checkValidity()")
        page.click("#native button")
        lines = live_session.page_says_lines(page.evaluate(live_session._PAGE_SAYS_JS))
        assert lines[:10] == ["invalid field 'Email': Please provide an email address.",
                             "invalid field 'City': Pick a city.",
                             "invalid field 'Zip': Zip is too short.",
                             "error at 'Password': Password must be 5-40 characters long.",
                             "error: Invalid email or password.",
                             "alert: Your session ends soon.",
                             "status: We use cookies.",
                             "alert: The server is busy.",
                             "status: Added to basket",
                             "the browser refused 'Name': Please fill out this field."]
        assert len(lines) == 10                      # not the hidden toast, the 1 px copy, aria-live off or the panel
        # The browser's checks are handed over once.
        assert not any("'Name'" in line for line in
                       live_session.page_says_lines(page.evaluate(live_session._PAGE_SAYS_JS)))
    finally:
        browser.close()
        pw.stop()
