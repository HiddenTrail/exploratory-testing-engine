"""The read-only safety gate: safe controls pass, everything risky is refused."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety import classify, committing, safe_actions  # noqa: E402


def el(**kw):
    return {"role": "button", "name": "", "href": "", "type": "", **kw}


def test_benign_link_and_buttons_are_safe():
    assert not committing(el(role="link", name="Home", href="/home"), "http://x")
    for n in ("Yes", "No", "Back", "Zoom in", "Next", "Details", "Open menu"):
        assert not committing(el(role="button", name=n)), n


def test_mutating_names_are_committing():
    for n in ("Delete", "Save", "Submit", "Buy now", "Checkout", "Sign out",
              "Add to cart", "Confirm", "Send", "Subscribe", "Download report"):
        assert committing(el(role="button", name=n)), n


def test_form_inputs_are_committing():
    for r in ("textbox", "checkbox", "radio", "combobox", "slider", "searchbox"):
        assert committing(el(role=r, name="x")), r


def test_submit_and_reset_inputs_are_committing():
    assert committing(el(role="button", name="", type="submit"))
    assert committing(el(role="button", name="", type="reset"))


def test_special_scheme_links_are_committing():
    assert committing(el(role="link", name="Email us", href="mailto:a@b.com"))
    assert committing(el(role="link", name="Call", href="tel:123"))
    assert committing(el(role="link", name="Run", href="javascript:void(0)"))


def test_off_site_links_are_committing_but_same_origin_is_safe():
    base = "https://localhost:5173"
    assert committing(el(role="link", name="OSM", href="https://openstreetmap.org/x"), base)
    assert not committing(el(role="link", name="Docs", href="https://localhost:5173/docs"), base)


def test_disabled_control_is_committing():
    # A disabled control cannot be clicked; selecting it would hang and misreport.
    assert committing(el(role="button", name="Yes", disabled=True))
    assert committing(el(role="link", name="Home", href="/home", disabled=True), "http://x")


def test_protocol_relative_and_odd_scheme_links_are_committing():
    base = "https://localhost:5173"
    assert committing(el(role="link", name="tiles", href="//openstreetmap.org/t.png"), base)
    assert committing(el(role="link", name="x", href="blob:https://localhost:5173/abc"), base)
    assert committing(el(role="link", name="x", href="ws://localhost:5173/s"), base)
    # A protocol-relative link to the SAME host is still same-origin and safe.
    assert not committing(el(role="link", name="local", href="//localhost:5173/y"), base)


def test_unrecognised_role_fails_closed():
    assert committing(el(role="generic", name="the whole map container"))
    assert committing(el(role="img", name="banner"))


def test_safe_actions_keeps_only_the_safe_ones():
    elements = [el(role="button", name="Yes"), el(role="button", name="Delete"),
                el(role="textbox", name="query"), el(role="link", name="Home", href="/h")]
    names = [e["name"] for e in safe_actions(elements, "http://x")]
    assert names == ["Yes", "Home"]


def test_classify_explains_itself():
    is_committing, reason = classify(el(role="button", name="Delete account"))
    assert is_committing and "mutating" in reason
    ok, reason = classify(el(role="link", name="Home", href="/home"), "http://x")
    assert not ok and "safe" in reason
