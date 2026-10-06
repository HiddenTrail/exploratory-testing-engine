"""Spoor's map feeds the product's context, and the oracle is built from it (issue #311).
No browser, no model calls."""

import json

import pytest

from engine.adapters.web_gui import reference as ref_mod
from engine.adapters.web_gui import to_context
from engine.ontology import product as product_layer
from engine.ontology.oracle_creator import build_product_ideas
from engine.ontology.seeder import GENERATED_FACT_PENALTY, build_oracle

TOOLBAR = [{"role": "button", "name": "Show the shopping cart", "locator": "#cart"},
           {"role": "button", "name": "Language selection menu", "locator": "#lang"}]


def _state(sid, n, route, heading, extra=(), sig_extra=""):
    elements = TOOLBAR + list(extra)
    controls = ";".join(sorted(f"{e['role']}:{e['name'].lower()}" for e in elements))
    return {"id": sid, "first_seen": n, "url": f"http://shop/{route}", "title": "Shop",
            "signature": f"/|{controls}{sig_extra}|{heading}", "elements": elements}


def _map():
    review = [{"role": "textbox", "name": "Text field to review a product", "locator": "#r"},
              {"role": "button", "name": "Send the review", "locator": "#send", "changes_data": True},
              {"role": "button", "name": "Add to Basket", "locator": "#add", "changes_data": True}]
    states = [
        _state("st01", 0, "#/", ""),
        _state("st02", 1, "#/", "apple juice (1000ml)", review),
        _state("st03", 2, "#/", "apple pomace", review + [{"role": "button", "name": "Reviews(2)", "locator": "#rv"}]),
        _state("st04", 3, "#/basket", "your basket (<email>)", [{"role": "button", "name": "Checkout", "locator": "#c"}]),
    ]
    edge = lambda i, src, dst, name: {"id": f"tr{i}", "source": src, "dest": dst, "effect": "navigate",
                                      "action": {"kind": "click", "element_key": f"button:{name}", "target": "#x"}}
    return ref_mod.Reference({"schema": "web-recon/1", "target": {"url": "http://shop/"}, "states": states,
                              "transitions": [edge(1, "st01", "st02", "Apple Juice (1000ml)"),
                                              edge(2, "st01", "st03", "Apple Pomace"),
                                              edge(3, "st01", "st04", "Show the shopping cart")]})


def test_states_that_share_a_route_and_most_controls_are_one_screen():
    screens = to_context.screens_from_map(_map(), "shop", "spoor-map test")
    assert [s["title"] for s in screens] == ["shop start page", "shop apple juice (1000ml) and 1 more like it",
                                             "shop your basket"]
    dialog = screens[1]
    assert dialog["route"] == "/#/" and dialog["states"] == ["st02", "st03"]
    assert dialog["examples"] == ["apple juice (1000ml)", "apple pomace"]
    assert screens[2]["route"] == "/#/basket" and "<email>" not in screens[2]["title"]


def test_features_come_from_what_is_on_the_screen_not_from_the_toolbar():
    screens = to_context.screens_from_map(_map(), "shop", "spoor-map test")
    start, dialog, basket = screens
    assert "localization" in start["features"]             # the toolbar counts on the start screen
    assert "localization" not in dialog["features"]
    assert dialog["features"] == ["text-field", "input-field", "cart", "form"]   # a field and "Send the review"
    assert basket["features"] == ["cart"]


def test_facts_say_only_what_the_map_saw():
    screens = to_context.screens_from_map(_map(), "shop", "spoor-map test")
    facts = [f["text"] for f in screens[1]["facts"]]
    assert facts == ["shop apple juice (1000ml) and 1 more like it has the fields Text field to review a product.",
                     "On shop apple juice (1000ml) and 1 more like it, these change data: Send the review, Add to Basket.",
                     "shop apple juice (1000ml) and 1 more like it is one screen shown for: apple juice (1000ml), apple pomace."]
    start_facts = [f["text"] for f in screens[0]["facts"]]
    assert "Show the shopping cart on shop start page leads to shop your basket." in start_facts
    assert all(f["kind"] == "shown" and f["source"] == "spoor-map test" for f in screens[0]["facts"])


def test_names_lose_emails_and_get_short():
    assert to_context._name("account_circle qes-1@example.test Orders") == "account_circle Orders"
    assert to_context._name("x " * 60).endswith("...") and len(to_context._name("x " * 60)) <= 43


@pytest.fixture
def context_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_CONTEXT_DIR", str(tmp_path))
    return tmp_path


def test_writing_screens_keeps_the_rest_of_the_context(context_dir):
    (context_dir / "context_shop.json").write_text(json.dumps({"test_results": [{"claim_id": "x"}]}))
    to_context.write("shop", to_context.screens_from_map(_map(), "shop", "spoor-map test"))
    saved = json.loads((context_dir / "context_shop.json").read_text(encoding="utf-8"))
    assert saved["test_results"] == [{"claim_id": "x"}] and len(saved["screens"]) == 3


def test_a_product_with_only_screens_gets_an_oracle_with_routes(context_dir, tmp_path):
    to_context.write("shop", to_context.screens_from_map(_map(), "shop", "spoor-map test"))
    screens = product_layer.context_screens("shop")
    assert screens[1]["facts"][0]["id"] == "shop.screen-apple-juice-1000ml.G1"
    empty_wiki = tmp_path / "wiki"
    empty_wiki.mkdir()
    oracle = build_oracle("shop", wiki_dir=empty_wiki)
    facts = [e for e in oracle["expectations"] if e["tier"] == "fact"]
    assert facts and all(e["score"] == 5.0 - GENERATED_FACT_PENALTY for e in facts)
    assert any(e["entity"] == "screen-your-basket" for e in oracle["expectations"] if e["tier"] == "heuristic")


def test_ideas_on_a_reachable_screen_rank_higher_and_say_where(context_dir, monkeypatch):
    to_context.write("shop", to_context.screens_from_map(_map(), "shop", "spoor-map test"))
    monkeypatch.setattr(product_layer, "WIKI_DIR", context_dir / "no-wiki")
    import engine.ontology.seeder as seeder
    monkeypatch.setattr(seeder.product_layer, "load_product", lambda product, wiki_dir=None: None)
    monkeypatch.setattr(seeder.product_layer, "product_errors", lambda product, wiki_dir=None: [])
    ideas = build_product_ideas("shop")["ranked_ideas"]
    on_screens = [i for i in ideas if i["entity"].startswith("screen-")]
    assert on_screens and all(i["where"] in ("/#/", "/#/basket") for i in on_screens)
    assert all("where" not in i for i in ideas if i["entity"] == "product")
