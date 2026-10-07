"""A failed step says why, and a control with no name is told apart by what a person
sees (issue #325). One test drives a real headless browser when one is installed."""

import pytest

from trailhound.adapters.web_gui import careful as careful_mod
from trailhound.adapters.web_gui import reference as ref_mod
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _acting_session, _Obs


@pytest.mark.parametrize("error, reason", [
    ("Timeout 4000ms exceeded.\n  - element is not visible\n  - retrying", "hidden: it has no size or isn't shown "
                                                                           "(it may open from another control)"),
    ("<div class=cdk-overlay-backdrop> intercepts pointer events", "covered by another element"),
    ("waiting for element to be visible, enabled\n - element is not enabled", "disabled"),
    ("Error: Element is not an <input>... element is not editable", "not editable (read-only)"),
    ("strict mode violation: get_by_role resolved to 2 elements", "more than one control matched"),
    ("Timeout 3000ms exceeded.", "timed out waiting for it"),
    # Found live in review: an Angular dropdown's call log quotes aria-disabled="false".
    ('Error: Element is not a <select> element\n  - <mat-select aria-disabled="false" role="combobox">',
     "not a dropdown with options (a custom one: click it, then click the option)"),
    ('Timeout 4000ms exceeded.\n  - <button aria-disabled="false">', "timed out waiting for it"),
    ("Timeout 4000ms exceeded.\n  - did not find some options", "no option with that label"),
    ("net::ERR_SOMETHING odd\nmore", "net::ERR_SOMETHING odd"),
    ("", "the browser couldn't do it"),
])
def test_a_playwright_error_becomes_a_reason(error, reason):
    assert live_session.failure_reason(error) == reason


def _stepping_session(monkeypatch, errors):
    sess = live_session.Session.__new__(live_session.Session)
    sess.careful = dict(careful_mod.NOTHING)
    sess.blocked_off_site = []
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#q"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/#/")

    def fails(step):
        for e in errors:                     # the ladder tries several ways, each failing
            sess._note_failure(Exception(e))
        return False
    monkeypatch.setattr(sess, "_actuate", fails)
    return sess


def test_a_failed_step_keeps_the_most_telling_reason(monkeypatch):
    # The issue's case: a hidden toolbar search box, then a forced click that only timed out.
    sess = _stepping_session(monkeypatch, ["Timeout 3000ms exceeded.\n - element is not visible",
                                           "Timeout 2000ms exceeded."])
    step = sess._do_step({"do": "click", "role": "button", "name": "Search"})
    assert step["status"] == "failed"
    assert step["detail"] == "hidden: it has no size or isn't shown (it may open from another control)"
    sess = _stepping_session(monkeypatch, [])
    assert sess._do_step({"do": "click", "role": "button", "name": "X"})["detail"] == "the browser couldn't do it"


def test_page_controls_tell_unnamed_controls_apart_with_their_nth(monkeypatch):
    products = [{"role": "button", "name": "", "hint": f'in a card or list item, image "P{n}"', "locator": f"#p{n}"}
                for n in range(1, 9)]
    after = _Obs(elements=[
        {"role": "textbox", "name": "", "hint": "in the toolbar, no size (it may open from another control)",
         "locator": "#s"},
        {"role": "button", "name": "", "hint": "", "locator": "#t", "transient": True},     # a toast: counted, not shown
        *products,
        {"role": "button", "name": "", "locator": "#x"},                                     # no hint: counted as before
        {"role": "button", "name": "A", "locator": "#a"},
        {"role": "button", "name": "Next page", "locator": "#next"},
    ])
    after.url = "http://app.example/"
    result = _acting_session(monkeypatch, after).act("st01", "button:A")
    controls = result["page_controls"]
    # Named controls first, so the cap cuts hints, not the paging controls.
    assert controls[:3] == ["button:", "button:A", "button:Next page"]
    assert "textbox: nth 1 (in the toolbar, no size (it may open from another control))" in controls
    # The toast is button nth 1, so the products are nth 2 on, as a step's nth counts; past 5, one line.
    assert 'button: nth 2 (in a card or list item, image "P1")' in controls
    assert 'button: nth 5 (in a card or list item, image "P4")' in controls
    assert controls[-1] == "button: nth 6 to 9 (x4 more with no name)"


def test_the_maps_guide_lists_unnamed_controls_with_their_hint():
    lines = ref_mod._control_lines([
        {"role": "button", "name": "Add to Basket"}, {"role": "button", "name": "Add to Basket"},
        {"role": "button", "name": ""},                                   # no hint: still counted for nth
        {"role": "button", "name": "", "hint": "in the toolbar", "spoor_reached": False},
        {"role": "link", "name": ""}, {"role": "link", "name": ""}])
    # One bracket for the hint and the notes; the nth counts the unhinted button before it.
    assert lines == ["button:Add to Basket (x2)", "button:", "button: nth 2 (in the toolbar, behind a dialog, or not "
                     "reached by the recon)", "link: (x2)"]


def test_the_capture_gives_an_unnamed_control_a_hint_in_a_real_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:
        pytest.skip(f"no browser installed here ({str(exc).splitlines()[0][:60]})")
    try:
        page = browser.new_page()
        page.set_content("""
          <header><input type="text" style="width:0;padding:0;border:0"><button>Menu</button></header>
          <ul><li><button><img src="/img/apple_juice.jpg" alt="Apple Juice"></button></li></ul>
          <form><input type="number" style="width:50px"></form>""")
        elements = page.evaluate(live_session.ELEMENTS_JS)
        one = lambda **want: next(e for e in elements if all(e.get(k) == v for k, v in want.items()))
        assert one(tag="input", type="text")["hint"] == "in the toolbar, no size (it may open from another control)"
        assert one(tag="input", type="number")["hint"] == "in a form, type number"
        assert one(tag="button", name="")["hint"] == 'in a card or list item, image "Apple Juice"'
        assert one(name="Menu")["hint"] == ""                                              # named: no hint
    finally:
        browser.close()
        pw.stop()
