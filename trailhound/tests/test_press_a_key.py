"""A test step can press a key (issue #350). One test uses a real browser and is skipped
where none is installed; the rest need none."""

import pytest

from trailhound.adapters.web_gui import adapter as adp
from trailhound.adapters.web_gui import careful as careful_mod
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _ON_PAGE, _stepping_session


def _press(key, role="", name="", **extra):
    return {"do": "press", "value": key, **({"role": role} if role else {}), **({"name": name} if name else {}), **extra}


def test_a_press_step_needs_a_key_from_the_list_and_a_role_when_it_names_an_element():
    errors = lambda step: adp._step_errors("s", step)
    assert errors(_press("Enter")) == [] and errors(_press("Enter", "textbox", "Message")) == []
    assert errors(_press("Shift+Tab")) == [] and errors(_press("Space")) == []
    assert errors(_press("Control+A")) == [f"s (press) needs a key as its value, one of: {', '.join(live_session.PRESS_KEYS)}"]
    assert errors({"do": "press"})[0].startswith("s (press) needs a key")
    assert errors(_press("Enter", name="Message")) == ["s (press) needs a 'role' when it names an element"]
    assert errors(_press("Enter", "textbox", "Message", nth=0)) == ["s.nth must be a whole number from 1"]
    assert errors(_press("Enter", nth=2)) == ["s (press) has 'nth' but no element: give it a 'role' and 'name'"]


def test_testing_fully_a_key_goes_to_the_element_or_to_what_has_focus(monkeypatch):
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE)
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    assert sess._do_step(_press("Enter", "textbox", "Quantity"))["status"] == "done"
    assert pressed[-1] == {"press": "Enter", "role": "textbox", "name": "Quantity", "locator": "#q"}
    monkeypatch.setattr(sess, "_focused", lambda: _ON_PAGE[4])
    done = sess._do_step(_press("Enter"))
    assert done["status"] == "done" and pressed[-1] == {"press": "Enter"} and done["focused"] == "textbox:Quantity"
    # It replays on what had focus, not on whatever has it then.
    assert live_session._replay_step(_press("Enter"), done, None) == {"press": "Enter", "role": "textbox", "name": "Quantity"}
    assert sess._do_step(_press("Enter", "textbox", "Ghost"))["status"] == "not_found"


def test_enter_or_space_on_log_out_is_refused_everywhere(monkeypatch):
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE)
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    for step in (_press("Enter", "button", "Logout"), _press("Space", "button", "Logout")):
        refused = sess._do_step(step)
        assert refused["status"] == "refused" and "ends the session" in refused["detail"]
    monkeypatch.setattr(sess, "_focused", lambda: _ON_PAGE[2])           # Logout has focus after a Tab
    assert sess._do_step(_press("Enter"))["status"] == "refused"
    assert sess._do_step(_press("Tab"))["status"] == "done"             # moving on from it is fine
    assert pressed == [{"press": "Tab"}]


def test_enter_in_a_form_is_judged_by_the_buttons_that_submit_it(monkeypatch):
    # Found in review: Enter in a field submitted the form through a button nobody checked.
    tags = {"everything": False, "routes": [], "controls": ["Delete account"]}
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE, tags=tags)
    monkeypatch.setattr(sess, "_form_buttons", lambda element: ["Delete account"])
    refused = sess._do_step(_press("Enter", "textbox", "Quantity"))
    assert refused["status"] == "refused" and "Enter would submit the form, through 'Delete account'" in refused["detail"]
    assert sess._do_step(_press("Tab", "textbox", "Quantity"))["status"] == "done"
    monkeypatch.setattr(sess, "_form_buttons", lambda element: ["Sign out"])
    assert "ends the session" in sess._do_step(_press("Enter", "textbox", "Quantity"))["detail"]
    monkeypatch.setattr(sess, "_form_buttons", lambda element: ["Save"])
    monkeypatch.setattr(sess, "_careful_on_page", lambda tags: "")
    assert sess._do_step(_press("Enter", "textbox", "Quantity"))["status"] == "done"
    # No form, but the app may wire Enter to anything: not while a tagged control is on the page.
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    monkeypatch.setattr(sess, "_careful_on_page", lambda tags: "Delete account")
    refused = sess._do_step(_press("Enter", "textbox", "Quantity"))
    assert refused["status"] == "refused" and "Enter here could set off 'Delete account'" in refused["detail"]
    assert sess._do_step(_press("Enter", "button", "Next page"))["status"] == "done"   # judged by its own name


def test_enter_on_a_focus_it_cant_tell_apart_is_refused_everywhere(monkeypatch):
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE)
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    monkeypatch.setattr(sess, "_focused", lambda: None)                 # in a shadow root or a frame
    for key in ("Enter", "Space"):
        refused = sess._do_step(_press(key))
        assert refused["status"] == "refused" and "can't tell apart" in refused["detail"]
    assert sess._do_step(_press("Tab"))["status"] == "done"
    monkeypatch.setattr(sess, "_focused", lambda: {})                   # the page itself
    assert sess._do_step(_press("Enter"))["status"] == "done"


def test_where_tagged_careful_a_key_is_judged_like_a_click(monkeypatch):
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE, tags=dict(careful_mod.EVERYTHING))
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    for key in ("Escape", "Tab", "Shift+Tab"):                            # only move focus or close
        assert sess._do_step(_press(key, "button", "Checkout"))["status"] == "done"
    assert sess._do_step(_press("Enter", "button", "Next page"))["status"] == "done"
    refused = sess._do_step(_press("Enter", "button", "Checkout"))
    assert refused["status"] == "refused" and "mutating verb" in refused["detail"]
    # Enter in a field submits its form: refused, even in a search box.
    assert sess._do_step(_press("Enter", "searchbox", "Search"))["status"] == "refused"
    assert sess._do_step(_press("ArrowDown", "searchbox", "Search"))["status"] == "done"
    assert sess._do_step(_press("Backspace", "textbox", "Quantity"))["status"] == "refused"
    # Nothing focused that it can judge: refused rather than guessed.
    monkeypatch.setattr(sess, "_focused", lambda: {})
    refused = sess._do_step(_press("Enter"))
    assert refused["status"] == "refused" and "can't tell what has focus" in refused["detail"]
    assert sess._do_step(_press("Escape"))["status"] == "done"
    # Found only by its accessible name: there's no element for the gate to judge.
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "", "a11y_nth": 1})
    refused = sess._do_step(_press("Enter", "button", "Next page"))
    assert refused["status"] == "refused" and "only by its accessible name" in refused["detail"]


def test_a_key_that_leaves_the_site_is_stopped(monkeypatch):
    sess, _ = _stepping_session(monkeypatch, _ON_PAGE)
    monkeypatch.setattr(sess, "_form_buttons", lambda element: [])
    monkeypatch.setattr(sess, "_actuate", lambda step: sess.blocked_off_site.append("https://elsewhere.example/") or True)
    failed = sess._do_step(_press("Enter", "button", "Next page"))
    assert failed["status"] == "failed" and failed["detail"] == "it leads off the site, and the browser was stopped"


def test_a_press_reads_as_a_label_replays_and_counts_its_element_as_tried():
    assert live_session._step_label(_press("Enter")) == "press Enter"
    assert live_session._step_label(_press("Enter", "textbox", "Message", nth=2)) == "press Enter on textbox:Message #2"
    assert live_session._replay_step(_press("Enter", "textbox", "Message", locator="#m"), {}, None) == {
        "press": "Enter", "role": "textbox", "name": "Message", "locator": "#m"}
    result = {"steps": [{**_press("Enter", "textbox", "Message"), "status": "done"},
                        {**_press("Tab"), "status": "done"}]}
    assert adp.coverage_of(result) == {"tried": ["textbox:message"], "inputs": []}


def test_the_driver_is_told_how_to_press():
    assert "press   a key, as value: Enter, Escape, Tab" in adp.API_SCHEMA_DOC
    assert "Escape, Tab and Shift+Tab are fine" in adp.SAFETY_NOTE
    step = adp.CASTING_TOOL["input_schema"]["properties"]["candidate_tests"]["items"]["properties"]["steps"]["items"]
    assert "press" in step["properties"]["do"]["enum"] and "Shift+Tab" in step["properties"]["value"]["description"]


def test_keys_press_in_a_real_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:
        pytest.skip(f"no browser installed here ({str(exc).splitlines()[0][:60]})")
    try:
        page = browser.new_page()
        page.set_content("""
          <form onsubmit="event.preventDefault(); document.getElementById('sent').textContent = 'sent: ' + this.m.value">
            <input name="m" aria-label="Message"><button>Send</button></form>
          <p id="sent"></p><p id="keys"></p>
          <script>document.addEventListener('keydown', (e) => { document.getElementById('keys').textContent += e.key + ','; });</script>""")
        sess = live_session.Session.__new__(live_session.Session)
        sess.page, sess.last_failure = page, ""
        page.fill("input", "hello")
        assert sess._press({"press": "Enter", "role": "textbox", "name": "Message", "locator": "input"})
        assert page.text_content("#sent") == "sent: hello"
        # A replayed path with no selector finds the element by its accessible name.
        page.fill("input", "again")
        sess._live_locator = lambda role, name: ""
        assert sess._press({"press": "Enter", "role": "textbox", "name": "Message"})
        assert page.text_content("#sent") == "sent: again"
        for key in live_session.PRESS_KEYS:                    # every key on the list is one Playwright knows
            assert sess._press({"press": key}), key
        assert page.text_content("#keys") == "Enter,Enter,Enter,Escape,Tab,Shift,Tab,ArrowUp,ArrowDown,ArrowLeft,ArrowRight, ,Backspace,"
        assert sess._focused()                                 # Tab moved focus onto a control
        page.focus("input")
        assert sess._form_buttons(None) == ["Send"]            # Enter here would submit through Send
        page.evaluate("document.activeElement.blur()")
        assert sess._focused() == {} and sess._form_buttons(None) == []
    finally:
        browser.close()
        pw.stop()
