"""The seeded oracle (issue #138): the product layer read from the wiki, the FEW
HICCUPPS seeds, and the oracle built from both. No model calls."""

import json

from engine.ontology import feedback, oracle_creator, product, seeder

JUICE_SHOP = seeder.build_oracle("juice-shop")["expectations"]


def test_juice_shops_wiki_pages_are_a_valid_product_layer():
    assert product.product_errors("juice-shop") == []
    loaded = product.load_product("juice-shop")
    assert loaded["surfaces"] == ["gui"]
    login = next(e for e in loaded["entities"] if e["slug"] == "login-page")
    assert "login" in login["features"]
    assert login["facts"][0]["id"] == "juice-shop.login-page.F1"
    assert login["facts"][0]["source"].endswith("S21.png")   # the page's source id, resolved to its file


def test_a_bad_product_page_is_reported(tmp_path):
    (tmp_path / "overview.md").write_text("---\ntype: Product Overview\nproduct: demo\nsurfaces: [gui]\n---\n",
                                          encoding="utf-8")
    (tmp_path / "demo-home.md").write_text(
        "---\ntype: Entity\nproduct: demo\nfeatures: [login, teleport]\n"
        "sources:\n  - id: doc\n    resource: docs/x.md\n"
        "facts:\n  - id: F1\n    kind: rumour\n    text: x\n    source: doc\n"
        "  - id: F2\n    kind: shown\n    text: y\n    source: nowhere\n---\n", encoding="utf-8")
    errors = product.product_errors("demo", wiki_dir=tmp_path)
    assert any("teleport" in e for e in errors)
    assert any("demo.home.F1 has kind 'rumour'" in e for e in errors)
    assert any("demo.home.F2 cites a source" in e for e in errors)
    assert product.product_errors("nothing", wiki_dir=tmp_path) == ["no Product Overview page with product: nothing"]


def test_a_fact_without_an_id_is_reported(tmp_path):
    (tmp_path / "overview.md").write_text("---\ntype: Product Overview\nproduct: demo\n---\n",
                                          encoding="utf-8")
    (tmp_path / "demo-home.md").write_text(
        "---\ntype: Entity\nproduct: demo\nfacts:\n  - kind: shown\n    text: x\n---\n",
        encoding="utf-8")

    loaded = product.load_product("demo", wiki_dir=tmp_path)
    assert loaded["entities"][0]["facts"][0]["id"] is None
    # Built with the path type, so it matches on Windows (backslashes) as well as Linux.
    assert product.product_errors("demo", wiki_dir=tmp_path) == [f"{tmp_path / 'demo-home.md'}: fact has no id"]


def test_build_oracle_rejects_a_bad_product_page(tmp_path):
    (tmp_path / "overview.md").write_text("---\ntype: Product Overview\nproduct: demo\nsurfaces: [gui]\n---\n",
                                          encoding="utf-8")
    (tmp_path / "demo-home.md").write_text(
        "---\ntype: Entity\nproduct: demo\nfeatures: [teleport]\n"
        "sources:\n  - id: doc\n    resource: docs/x.md\n"
        "facts:\n  - id: F1\n    kind: rumour\n    text: x\n    source: doc\n---\n", encoding="utf-8")

    try:
        seeder.build_oracle("demo", wiki_dir=tmp_path)
    except ValueError as error:
        assert "teleport" in str(error)
        assert "rumour" in str(error)
    else:
        raise AssertionError("invalid product layer was accepted")


def test_every_seed_names_only_heuristics_the_library_has():
    ids = {h["id"] for h in oracle_creator.load_heuristics()}
    for seed in seeder.load_seeds():
        missing = [i for i in seed["draws_on"].get("heuristic_ids", []) if i not in ids]
        assert not missing, (seed["id"], missing)


def test_every_oracle_and_attack_heuristic_has_a_seed():
    # Issue #246: console_and_network_errors matched no seed, so no product's oracle had
    # it, and the milestone run called a real console TypeError a mere finding.
    seeds = seeder.load_seeds()
    unseeded = [h["id"] for h in oracle_creator.load_heuristics()
                if h["kind"] in ("oracle", "attack") and seeder._owner(seeds, h) is None]
    assert unseeded == []


def test_console_errors_and_several_tabs_reach_juice_shops_oracle():
    by_id = {e["id"]: e for e in JUICE_SHOP}
    errors = by_id["oracle:familiarity:product:console_and_network_errors"]
    assert "shouldn't throw uncaught script errors" in errors["claim"]
    assert "oracle:comparable_products:login-page:multiple_tabs" in by_id


def test_the_oracle_lists_the_heuristics_no_seed_draws_on():
    oracle = seeder.build_oracle("juice-shop")
    assert "goldilocks" in oracle["not_drawn_on"] and "console_and_network_errors" not in oracle["not_drawn_on"]


def test_the_built_oracle_has_unique_ids_and_every_seed_contributes():
    ids = [e["id"] for e in JUICE_SHOP]
    assert len(ids) == len(set(ids))
    assert {e["seed"] for e in JUICE_SHOP} == {s["id"] for s in seeder.load_seeds()}


def test_a_shown_fact_becomes_a_self_consistency_expectation_citing_its_source():
    e = next(e for e in JUICE_SHOP if e["id"] == "oracle:self_consistency:juice-shop.product-list.F2")
    assert e["tier"] == "fact" and "1.99" in e["claim"]
    assert e["sources"][0] == "juice-shop.product-list.F2"
    assert e["sources"][1].endswith("S7.png")


def test_a_claim_the_product_makes_is_checked_by_the_claims_seed():
    e = next(e for e in JUICE_SHOP if e["id"] == "oracle:claims_oracle:juice-shop.product-list.F9")
    assert e["tier"] == "fact" and "Only 1 left" in e["claim"]


def test_a_heuristic_goes_on_the_screens_that_share_its_feature_and_under_the_seed_naming_it():
    placed = [e for e in JUICE_SHOP if e["id"].endswith(":monetary_precision")]
    assert {e["entity"] for e in placed} == {"product-list", "product-details-dialog"}   # the two with money
    assert {e["seed"] for e in placed} == {"world"}    # named by World, though Product matches its tags


def test_the_pick_takes_turns_across_seeds():
    ideas = oracle_creator.build_product_ideas("juice-shop", limit=len(seeder.load_seeds()))["ranked_ideas"]
    assert {i["category"] for i in ideas} == {s["id"] for s in seeder.load_seeds()}


def test_an_earlier_result_moves_an_expectation_up_or_down(monkeypatch):
    target = "oracle:self_consistency:juice-shop.product-list.F2"
    monkeypatch.setattr(oracle_creator, "load_context",
                        lambda key: {"test_results": [{"claim_id": target, "verified": False}]})
    ideas = {i["id"]: i for i in oracle_creator.build_product_ideas("juice-shop")["ranked_ideas"]}
    assert ideas[target]["status"] == "refuted"
    assert ideas[target]["score"] == oracle_creator.GROUNDED_BASE_SCORE + oracle_creator.REFUTED_BONUS


def test_feedback_knows_a_products_expectation_ids():
    known = feedback.known_ids("web_gui", product="juice-shop")
    assert "oracle:self_consistency:juice-shop.product-list.F2" in known
    output = {"casting_log": [{"oracle_claim_id": "oracle:self_consistency:juice-shop.product-list.F2",
                               "prediction_matched": True},
                              {"oracle_claim_id": "heuristic:made_up", "prediction_matched": True}]}
    results, dropped = feedback.extract_results(output, known)
    assert [r["claim_id"] for r in results] == ["oracle:self_consistency:juice-shop.product-list.F2"]
    assert dropped == ["heuristic:made_up"]


def test_the_oracle_is_plain_json():
    json.dumps(seeder.build_oracle("juice-shop"))   # the data a separate Oracle service would hand over



# ---- security quality (issue #278) -------------------------------------------------------------

SECURITY_HEURISTICS = ("client_storage_secrets", "third_party_requests", "own_resources_refused",
                       "browser_security_policy", "console_reveals_internals")


def test_the_security_quality_heuristics_go_under_standards():
    seeds = seeder.load_seeds()
    by_id = {h["id"]: h for h in oracle_creator.load_heuristics()}
    for hid in SECURITY_HEURISTICS:
        assert "security" in by_id[hid]["tags"] and "gui" in by_id[hid]["tags"], hid
        assert seeder._owner(seeds, by_id[hid])["id"] == "standards", hid
    placed = {e["id"].rsplit(":", 1)[1] for e in JUICE_SHOP if e["seed"] == "standards"}
    assert set(SECURITY_HEURISTICS) <= placed


def test_a_run_focus_gets_up_to_a_third_of_the_drivers_ideas():
    plain = oracle_creator.build_product_ideas("juice-shop", limit=15)["ranked_ideas"]
    focused = oracle_creator.build_product_ideas("juice-shop", limit=15, focus=("security",))["ranked_ideas"]
    assert len(focused) == 15
    in_focus = [i for i in focused if i.get("focus")]
    assert len(in_focus) == 5 and all(i["focus"] == ["security"] for i in in_focus)
    assert all("(this run's focus: security)" in i["rationale"] for i in in_focus)
    assert len({i["category"] for i in focused}) >= 8              # still rounded across the seeds
    assert not any(i.get("focus") for i in plain)
