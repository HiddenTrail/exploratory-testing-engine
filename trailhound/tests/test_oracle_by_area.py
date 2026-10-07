"""The oracle ranks ideas by how much of their area is still untested, and the most
important places the Driver reached beyond the map get ideas too (issue #330). No browser,
no model calls."""

import json

import pytest

from trailhound.adapters.web_gui import to_context
from trailhound.ontology import areas, product as product_layer
from trailhound.ontology.oracle_creator import build_product_ideas, load_vocabulary
from trailhound.tests.test_spoor_context import _map


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """A product with only Spoor's screens: a start page, a product dialog with a review
    form, and a basket."""
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path))
    import trailhound.ontology.seeder as seeder
    monkeypatch.setattr(seeder.product_layer, "load_product", lambda product, wiki_dir=None: None)
    monkeypatch.setattr(seeder.product_layer, "product_errors", lambda product, wiki_dir=None: [])
    to_context.write("shop", to_context.screens_from_map(_map(), "shop", "spoor-map test"))
    return tmp_path


def _context(path):
    return json.loads((path / "context_shop.json").read_text(encoding="utf-8"))


def _save(path, context):
    (path / "context_shop.json").write_text(json.dumps(context), encoding="utf-8")


def _tested(context, slug, runs, problems=None):
    """Tested hard: every control used and every field sent several kinds of value."""
    screen = next(s for s in context["screens"] if s["slug"] == slug)
    context.setdefault("coverage", {})[slug] = {
        "tests": 4 * len(runs), "runs": runs, "tried": list(screen["controls"]),
        "inputs": {f: ["empty", "markup", "negative"] for f in screen["fields"]}, "ideas": {},
        "problems": problems or {}, "order": 1}


def _best(ideas, slug):
    return max(i["score"] for i in ideas if i["entity"] == slug)


def test_without_coverage_the_order_is_the_oracles_own(shop, monkeypatch):
    import trailhound.ontology.oracle_creator as oc
    ideas = build_product_ideas("shop")["ranked_ideas"]
    monkeypatch.setattr(oc, "weigh_by_area", lambda ideas, context: None)
    unweighed = build_product_ideas("shop")["ranked_ideas"]
    assert [(i["id"], i["score"]) for i in ideas] == [(i["id"], i["score"]) for i in unweighed]
    assert not any("area" in i for i in ideas)


def test_an_idea_about_the_product_or_a_wiki_page_doesnt_move(shop, monkeypatch):
    import trailhound.ontology.oracle_creator as oc
    context = _context(shop)
    _tested(context, "screen-apple-juice-1000ml", ["r1", "r2"])
    _save(shop, context)
    ideas = build_product_ideas("shop")["ranked_ideas"]
    monkeypatch.setattr(oc, "weigh_by_area", lambda ideas, context: None)
    unweighed = {i["id"]: i["score"] for i in build_product_ideas("shop")["ranked_ideas"]}
    product_wide = [i for i in ideas if i["entity"] == "product"]
    assert product_wide and all(i["score"] == unweighed[i["id"]] and "area" not in i for i in product_wide)


def test_a_screen_never_tested_ranks_above_one_tested_in_three_runs(shop):
    # The issue's own check.
    before = build_product_ideas("shop")["ranked_ideas"]
    context = _context(shop)
    dialog, basket = "screen-apple-juice-1000ml", "screen-your-basket"
    assert {s["slug"] for s in context["screens"]} >= {dialog, basket}
    _tested(context, dialog, ["r1", "r2", "r3"])
    _save(shop, context)
    after = build_product_ideas("shop")["ranked_ideas"]
    assert _best(before, dialog) >= _best(before, basket)               # the dialog's form led before
    assert _best(after, dialog) < _best(before, dialog)                 # tested hard: it sinks
    assert _best(after, basket) > _best(after, dialog)                  # the screen never tested comes first
    on_basket = next(i for i in after if i["entity"] == basket)
    assert on_basket["area"].startswith("untested ") and "never tested" in on_basket["area"]
    assert {i["id"] for i in after} == {i["id"] for i in before}        # nothing drops out


def test_errors_found_in_an_area_dont_pull_the_oracle_back_to_it(shop):
    # Known findings are re-checked (#319), not chased: the oracle steers by `gaps`.
    context = _context(shop)
    dialog = "screen-apple-juice-1000ml"
    _tested(context, dialog, ["r1"])
    _save(shop, context)
    plain = _best(build_product_ideas("shop")["ranked_ideas"], dialog)
    context["coverage"][dialog]["problems"] = {"request: PUT /api/BasketItems/# -> 400": 3}
    _save(shop, context)
    with_errors = build_product_ideas("shop")["ranked_ideas"]
    assert _best(with_errors, dialog) == plain
    area = next(a for a in areas.rank(context) if a["key"] == dialog)
    assert area["importance"] == area["untested"] + areas.ERRORS
    assert "errors recorded" not in next(i for i in with_errors if i["entity"] == dialog)["area"]


def test_the_places_the_map_lacks_get_ideas_only_once_runs_have_learned_coverage(shop):
    context = _context(shop)
    context["discoveries"] = [{"id": "d1", "url": "http://shop/profile", "via": "x", "features": ["account"]}]
    assert product_layer.new_areas(context) == []


def test_the_most_important_places_the_map_lacks_get_ideas_with_a_route(shop):
    context = _context(shop)
    _tested(context, "screen-start-page", ["r1"])
    allowed = set(load_vocabulary()["tags"]["feature"])
    elements = [{"role": "textbox", "name": "Username"}, {"role": "button", "name": "Save the username"}]
    profile = {"id": "d1", "url": "http://shop/profile", "title": "Shop",
               "via": "menuitem:Go to user profile a.b@x.co", "times_reached": 2,
               "controls": ["button:save the username", "textbox:username"], "fields": ["textbox:username"],
               "changes_data": ["button:save the username"],
               "features": to_context.features_of(elements, [], allowed)}
    old = {"id": "d0", "url": "http://shop/#/old", "via": "button:x"}       # recorded before #330: no features
    context["discoveries"] = [profile, old] + [
        {**profile, "id": f"dx{n}", "fields": [], "changes_data": [], "features": ["navigation"]} for n in range(4)]
    _save(shop, context)
    new = [d["id"] for d, _ in product_layer.new_areas(context)]
    assert new[0] == "d1" and len(new) == product_layer.NEW_AREAS and "d0" not in new
    ideas = build_product_ideas("shop")["ranked_ideas"]
    on_profile = [i for i in ideas if i["entity"] == "d1"]
    assert on_profile and all(i["where"] == "/profile" for i in on_profile)
    assert "reached by the Driver, not mapped" in on_profile[0]["area"]
    assert "a.b@x.co" not in json.dumps(on_profile)                   # the title loses the email



def test_a_state_at_a_mapped_route_is_a_variant_and_gets_no_ideas_of_its_own(shop):
    # Found in the #330 benchmark: the basket after "Add to Basket" is a discovery at
    # "/#/basket", which the map has. Tests that start at that route count for the mapped
    # basket, so the variant looked untested for ever and kept 5 of the Driver's 15 ideas.
    context = _context(shop)
    _tested(context, "screen-start-page", ["r1"])
    context["discoveries"] = [
        {"id": "d1", "url": "http://shop/#/basket", "via": "button:Add to Basket", "features": ["cart", "text-field"]},
        {"id": "d2", "url": "http://shop/profile", "via": "menuitem:Profile", "features": ["account"]}]
    assert [d["id"] for d, _ in product_layer.new_areas(context)] == ["d2"]


def test_a_place_the_map_lacks_gets_no_bonus_for_being_reachable(shop, monkeypatch):
    # It's reached by replaying how it was found, not by its route (a dialog's route is
    # its page's). With the area weighing off, its ideas score the seeder's score plus the
    # untested bonus only; a mapped screen's ideas also get REACHABLE_BONUS.
    import trailhound.ontology.oracle_creator as oc
    from trailhound.ontology.seeder import build_oracle
    context = _context(shop)
    _tested(context, "screen-start-page", ["r1"])
    context["discoveries"] = [{"id": "d1", "url": "http://shop/profile", "via": "x", "features": ["account", "text-field"]}]
    _save(shop, context)
    monkeypatch.setattr(oc, "weigh_by_area", lambda ideas, context: None)
    seeded = {e["id"]: e["score"] for e in build_oracle("shop")["expectations"]}
    ideas = build_product_ideas("shop")["ranked_ideas"]
    on_profile = [i for i in ideas if i["entity"] == "d1"]
    on_basket = [i for i in ideas if i["entity"] == "screen-your-basket"]
    assert on_profile and all(i["score"] == seeded[i["id"]] + oc.UNTESTED_BONUS for i in on_profile)
    assert on_basket and all(i["score"] == seeded[i["id"]] + oc.UNTESTED_BONUS + oc.REACHABLE_BONUS for i in on_basket)
    assert not any(i["entity"] == "d0" for i in ideas)


def test_the_report_says_why_an_ideas_area_moved_it():
    from trailhound.report import render_oracle_ranked
    idea = {"rank": 1, "id": "oracle:x", "tier": "heuristic", "score": 7.5, "status": "untested",
            "claim": "c", "rationale": "r", "area": "untested 7.0: never tested; 2 field(s)"}
    assert "Its area: untested 7.0: never tested; 2 field(s)" in render_oracle_ranked([idea])
    assert "Its area" not in render_oracle_ranked([{**idea, "area": ""}])
