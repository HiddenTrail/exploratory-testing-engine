"""The read-only gate plans an action per control: click, fill, or skip - safely."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety import action_plans, committing, plan, safe_actions, vet, vetted_actions  # noqa: E402


def el(**kw):
    return {"role": "button", "name": "", "href": "", "type": "", **kw}


def test_links_and_buttons_are_clicked():
    assert plan(el(role="link", name="Home", href="/home"), "http://x").kind == "click"
    for n in ("Yes", "No", "Back", "Zoom in", "Next", "Details", "Open menu"):
        assert plan(el(role="button", name=n)).kind == "click", n


def test_selection_controls_are_clicked_not_skipped():
    # A radio/checkbox/tab/switch toggles a view - non-mutating, so the crawl actuates it.
    for r in ("radio", "checkbox", "switch", "tab"):
        assert plan(el(role=r, name="Price heatmap")).kind == "click", r


def test_a_mutating_named_selection_is_still_skipped():
    assert committing(el(role="checkbox", name="Delete on save"))


def test_search_box_is_filled_with_a_benign_query():
    p = plan(el(role="textbox", name="Search postcodes", type="text"))
    assert p.kind == "fill" and p.value
    p2 = plan(el(role="searchbox", name="", type="search"))
    assert p2.kind == "fill"


def test_sensitive_and_generic_text_fields_are_skipped():
    assert committing(el(role="textbox", name="Password", type="password"))
    assert committing(el(role="textbox", name="Email", type="email"))
    assert committing(el(role="textbox", name="Card number"))
    assert committing(el(role="textbox", name="Comment", type="text"))  # generic, not a search


def test_mutating_names_are_committing():
    for n in ("Delete", "Save", "Submit", "Buy now", "Checkout", "Sign out",
              "Add to cart", "Confirm", "Send", "Subscribe", "Download report"):
        assert committing(el(role="button", name=n)), n


def test_submit_and_reset_inputs_are_committing():
    assert committing(el(role="button", name="Go", type="submit"))
    assert committing(el(role="button", name="Clear", type="reset"))


def test_special_scheme_links_are_committing():
    assert committing(el(role="link", name="Email us", href="mailto:a@b.com"))
    assert committing(el(role="link", name="Call", href="tel:123"))
    assert committing(el(role="link", name="Run", href="javascript:void(0)"))


def test_off_site_links_are_refused_and_same_origin_is_kept():
    base = "https://localhost:5173"
    assert committing(el(role="link", name="OSM", href="https://openstreetmap.org/x"), base)
    assert committing(el(role="link", name="Leaflet", href="//leafletjs.com/y"), base)
    assert not committing(el(role="link", name="Docs", href="https://localhost:5173/docs"), base)
    assert not committing(el(role="link", name="Rel", href="/local/page"), base)


def test_off_site_fails_closed_when_base_unknown():
    # No base origin -> any hosted link is refused (cannot confirm same-origin).
    assert committing(el(role="link", name="x", href="https://anywhere.example/x"))
    # ...but a relative link stays in the app and is fine.
    assert not committing(el(role="link", name="x", href="/still/here"))


def test_disabled_control_is_committing():
    assert committing(el(role="button", name="Yes", disabled=True))


def test_unrecognised_role_fails_closed():
    assert committing(el(role="generic", name="the whole map container"))
    assert committing(el(role="img", name="banner"))
    assert committing(el(role="slider", name="Year"))
    assert committing(el(role="combobox", name="Mode"))


def test_vetting_is_off_unless_enabled():
    # With mutations disabled (the default) every control is refused - the crawl is read-only.
    assert vet(el(role="button", name="Search", type="submit"), enabled=False).kind is None
    assert vet(el(role="textbox", name="Search postcodes"), enabled=False).kind is None


def test_vetting_admits_only_reversible_query_submits():
    # A search/filter box -> a submit_search (fill + Enter); a Search/Filter/Sort button -> submit.
    assert vet(el(role="textbox", name="Search postcodes", type="text"), enabled=True).kind == "submit_search"
    assert vet(el(role="searchbox", name="", type="search"), enabled=True).kind == "submit_search"
    assert vet(el(role="button", name="Search", type="submit"), enabled=True).kind == "submit"
    assert vet(el(role="button", name="Apply filter"), enabled=True).kind == "submit"
    assert vet(el(role="button", name="Sort by price"), enabled=True).kind == "submit"


def test_vetting_refuses_destructive_even_when_enabled():
    # The "even if you asked, no" list: irreversible / money / auth / data-writing.
    for n in ("Delete", "Buy now", "Pay", "Checkout", "Save", "Send", "Publish",
              "Sign out", "Subscribe", "Confirm order", "Reset", "Upload"):
        assert vet(el(role="button", name=n, type="submit"), enabled=True).kind is None, n


def test_vetting_refuses_sensitive_and_unrecognised_even_when_enabled():
    assert vet(el(role="textbox", name="Password", type="password"), enabled=True).kind is None
    assert vet(el(role="textbox", name="Card number"), enabled=True).kind is None
    # A plain submit with no reversible-query name is not affirmatively reversible -> refused.
    assert vet(el(role="button", name="Continue", type="submit"), enabled=True).kind is None
    assert vet(el(role="button", name="OK"), enabled=True).kind is None
    assert vet(el(role="button", name="Search", type="submit", disabled=True), enabled=True).kind is None


def test_vetted_actions_pairs_only_admitted_controls():
    elements = [el(role="textbox", name="Search postcodes", type="text"),
                el(role="button", name="Delete", type="submit"),
                el(role="button", name="Filter", type="submit")]
    got = {e["name"]: v.kind for e, v in vetted_actions(elements, enabled=True)}
    assert got == {"Search postcodes": "submit_search", "Filter": "submit"}
    assert vetted_actions(elements, enabled=False) == []   # off by default


def test_safe_actions_and_plans():
    elements = [el(role="button", name="Yes"), el(role="button", name="Delete"),
                el(role="textbox", name="Comment", type="text"),
                el(role="radio", name="Trend"), el(role="link", name="Home", href="/h")]
    names = [e["name"] for e in safe_actions(elements, "http://x")]
    assert names == ["Yes", "Trend", "Home"]
    kinds = {e["name"]: p.kind for e, p in action_plans(elements, "http://x")}
    assert kinds == {"Yes": "click", "Trend": "click", "Home": "click"}
