"""What each run covered per area, the new areas it reached, and how much each area
matters next (issue #328). No browser, no model calls."""

import json

import pytest

from trailhound import outcome, ledger
from trailhound.adapters.web_gui.adapter import outcome_for
from trailhound.adapters.web_gui.reference import control_token
from trailhound.coverage import value_kinds
from trailhound.ontology import areas, feedback
from trailhound.run_summary import summarize


def test_each_value_sent_to_a_field_has_its_kinds():
    assert value_kinds("") == ["empty"] and value_kinds(None) == ["empty"] and value_kinds("   ") == ["spaces"]
    assert value_kinds("hello") == ["text"] and value_kinds(" hello ") == ["padded", "text"]
    assert value_kinds("-1") == ["number", "negative"] and value_kinds("0") == ["number", "zero"]
    assert value_kinds("2.5") == ["number", "decimal"] and value_kinds(10 ** 12) == ["number", "huge"]
    assert value_kinds("<b>x</b>") == ["markup"]
    assert value_kinds("<script>alert(1)</script>") == ["markup", "script"]
    assert value_kinds("javascript:alert(1)") == ["script"]
    assert value_kinds("' OR 1=1--") == ["quote"]
    assert value_kinds("a@b.co") == ["email"] and value_kinds("ääkkönen") == ["non-ascii"]
    assert value_kinds("x" * 300) == ["long"]
    # Found in review: these are plain values, not scripts, zeros or decimals.
    assert value_kinds("one=1") == ["text"] and value_kinds("Online=yes") == ["text"]
    assert value_kinds("<img src=x onerror=alert(1)>") == ["markup", "script"]
    assert value_kinds("1e5") == ["number"] and value_kinds("1e-400") == ["number"]
    assert value_kinds("10.0") == ["number", "decimal"] and value_kinds("-0") == ["number", "zero"]


def test_a_control_is_the_same_token_in_the_map_and_in_a_test():
    assert control_token("Button", "  Add to  Basket ") == "button:add to basket"
    assert control_token("menuitem", "account_circle trailhound-1@example.test Orders") == "menuitem:account_circle orders"
    assert control_token("button", "Reviews(2)") == control_token("button", "Reviews(3)") == "button:reviews(#)"


def test_a_web_test_says_where_it_started_what_it_used_and_what_it_typed():
    result = {"verdict": "sent", "action": "st05 :: x", "screen_was": "same_screen",
              "same_appearance": True,
              "steps": [{"do": "click", "role": "button", "name": "Add to Basket", "status": "done"},
                        {"do": "fill", "role": "textbox", "name": "Search", "value": "<b>x</b>", "status": "done"},
                        {"do": "fill", "role": "textbox", "name": "Search", "value": "-1", "status": "done"},
                        {"do": "fill", "role": "textbox", "name": "Quantity", "value": "-1", "status": "refused"},
                        {"do": "click", "role": "button", "name": "Pay", "status": "failed"}]}
    o = outcome_for(result)
    assert o.area == "st05"
    assert o.tried == ["button:add to basket", "textbox:search"]       # refused and failed controls weren't tried
    assert o.inputs == [["textbox:search", "markup"], ["textbox:search", "number"], ["textbox:search", "negative"]]
    assert outcome.validate_outcome(o.as_dict()) == []
    # A new-tab test is the same place: the area has no "(as a new tab)".
    assert outcome_for({**result, "started_as": "new_tab"}).area == "st05"
    # The start is the front of the action; a route is "/#/..." without a query.
    assert outcome_for({"verdict": "not_actuated", "action": "#/search?q=x :: button:Log in"}).area == "/#/search"
    # A test that never reached its start tried nothing there: no area, so it isn't counted.
    unreached = outcome_for({"verdict": "not_actuated", "action": "st05 :: x", "reached_target_state": False})
    assert unreached.area == "" and unreached.tried == []
    assert outcome.validate_outcome({**o.as_dict(), "inputs": [["only one"]]}) == [
        "'inputs' must be a list of [field, kind] pairs of strings"]


SCREENS = [
    {"slug": "screen-start-page", "title": "shop start page", "route": "/#/", "states": ["st01"], "path": [],
     "controls": ["button:a", "button:b", "button:c", "button:d"], "fields": [], "changes_data": []},
    {"slug": "screen-dialog", "title": "shop dialog", "route": "/#/", "states": ["st02", "st03"],
     "path": [{"name": "open"}], "controls": ["button:send"], "fields": [], "changes_data": []},
    {"slug": "screen-checkout", "title": "shop checkout", "route": "/#/checkout", "states": ["st09"],
     "path": [{"name": "x"}, {"name": "y"}], "controls": ["textbox:card", "button:pay"],
     "fields": ["textbox:card"], "changes_data": ["button:pay"]},
]


def test_a_tests_start_is_the_screen_it_belongs_to():
    assert areas.area_key("st03", SCREENS) == "screen-dialog"
    assert areas.area_key("/#/", SCREENS) == "screen-start-page"        # the route's screen with the shortest path
    assert areas.area_key("/#/checkout", SCREENS) == "screen-checkout"
    assert areas.area_key("/#/profile", SCREENS) == "/#/profile"         # no screen has it


def _entry(n, area, tried=(), inputs=(), idea="", problems=(), checkpoint=1, skipped=False):
    return outcome.attach({"test_number": n, "checkpoint": checkpoint, "oracle_claim_id": idea,
                           **({"skipped": True} if skipped else {})},
                          outcome.Outcome(area=area, tried=list(tried), inputs=[list(i) for i in inputs],
                                          problems=list(problems)))


def _run(*entries, answers=()):
    return {"casting_log": list(entries),
            "checkpoints": [{"hypothesis": {"ideas": [{"id": i, "verdict": v, "tests": [1]} for i, v in answers]}}]}


def test_coverage_adds_up_by_area_across_runs():
    context = {"screens": SCREENS}
    first = _run(_entry(1, "st01", ["button:a"], idea="oracle:x", problems=["request: GET /x -> 500"]),
                 _entry(2, "/#/", ["button:b"], [("textbox:q", "text")]),
                 _entry(3, "st02", ["button:send"]),
                 _entry(4, "st09", ["button:pay"], skipped=True),                   # never ran
                 answers=[("oracle:x", "broke")])
    assert areas.merge(context, areas.extract(first), run="r1", day="2026-10-07") == {
        "screen-start-page": True, "screen-dialog": True}
    second = _run(_entry(1, "st01", ["button:c"], [("textbox:q", "empty")], problems=["request: GET /x -> 500"]),
                  _entry(2, "/#/profile", ["button:save"]))
    assert areas.merge(context, areas.extract(second), run="r2", day="2026-10-08") == {
        "screen-start-page": False, "/#/profile": True}
    start = context["coverage"]["screen-start-page"]
    assert start["tests"] == 3 and start["runs"] == ["r1", "r2"] and start["last_tested"] == "2026-10-08"
    assert start["tried"] == ["button:a", "button:b", "button:c"]
    assert start["inputs"] == {"textbox:q": ["empty", "text"]}
    assert start["ideas"] == {"oracle:x": "broke"} and start["problems"] == {"request: GET /x -> 500": 2}
    assert "screen-checkout" not in context["coverage"]


def test_learning_from_the_same_run_twice_counts_it_once_and_made_up_ideas_are_left_out():
    context = {"screens": SCREENS}
    run = _run(_entry(1, "st01", ["button:a"], idea="oracle:real"), _entry(2, "st01", idea="C1.G2"))
    found = areas.extract(run, known_ideas={"oracle:real"})
    assert found["st01"]["ideas"] == {"oracle:real": ""}
    areas.merge(context, found, run="r1")
    areas.merge(context, found, run="r1")
    assert context["coverage"]["screen-start-page"]["tests"] == 2 and context["coverage"]["screen-start-page"]["runs"] == ["r1"]


def test_a_route_tested_before_the_map_had_it_moves_onto_its_screen():
    # Found in the second review: learn a run, write the screens, learn it again; the
    # route's coverage must join the screen, counted once, with no "not mapped".
    context = {"screens": SCREENS[:2]}
    found = areas.extract(_run(_entry(1, "/#/checkout", ["button:pay"])))
    areas.merge(context, found, run="r1")
    assert list(context["coverage"]) == ["/#/checkout"]
    context["screens"] = SCREENS                                  # a new map has the checkout screen
    areas.merge(context, found, run="r1")
    assert list(context["coverage"]) == ["screen-checkout"]
    assert context["coverage"]["screen-checkout"]["tests"] == 1
    assert not any(a["key"] == "/#/checkout" for a in areas.rank(context))


def test_a_later_runs_answer_to_an_idea_wins_whichever_area_its_test_started_in():
    context = {"screens": SCREENS}
    areas.merge(context, areas.extract(_run(_entry(1, "st02"))), run="r0")
    areas.merge(context, areas.extract(_run(_entry(1, "st01", idea="i"), answers=[("i", "held")])), run="r1")
    areas.merge(context, areas.extract(_run(_entry(1, "st02", idea="i"), answers=[("i", "broke")])), run="r2")
    start = next(a for a in areas.rank(context, [{"id": "i", "entity": "screen-start-page"}])
                 if a["key"] == "screen-start-page")
    assert "1 oracle idea(s) broke here" in start["why"]


def test_an_answer_isnt_lost_to_a_later_run_that_only_cited_the_idea():
    context = {"screens": SCREENS}
    areas.merge(context, areas.extract(_run(_entry(1, "st01", idea="i"), answers=[("i", "broke")])), run="r1")
    areas.merge(context, areas.extract(_run(_entry(1, "st01", idea="i"))), run="r2")
    assert context["coverage"]["screen-start-page"]["ideas"] == {"i": "broke"}


def test_tests_already_spent_lower_a_score_by_at_most_3_and_it_stops_at_0():
    context = {"screens": [{"slug": "s", "title": "s", "route": "/#/s", "states": ["st1"], "controls": ["button:a"]}]}
    areas.merge(context, areas.extract(_run(*[_entry(n, "st1", ["button:a"]) for n in range(1, 51)])), run="r1")
    [area] = areas.rank(context)
    assert area["importance"] == 0.0 and area["why"] == ["tested 50 time(s) already"]
    context["coverage"]["s"]["problems"] = {"console: E": 1}
    assert areas.rank(context)[0]["importance"] == 0.0             # 2 for the error, 3 off for the tests


def test_an_untouched_screen_with_a_form_ranks_above_a_tested_start_page():
    # The issue's own check: after a run, the scores put a screen nobody touched that has a
    # form above the start page that was tested.
    context = {"screens": SCREENS}
    run = _run(*[_entry(n, "st01", ["button:a", "button:b"]) for n in range(1, 11)])
    areas.merge(context, areas.extract(run), run="r1")
    ranked = areas.rank(context, [{"id": "i1", "entity": "screen-checkout"}, {"id": "i2", "entity": "screen-start-page"}])
    order = [a["key"] for a in ranked]
    assert order.index("screen-checkout") < order.index("screen-start-page")
    checkout = next(a for a in ranked if a["key"] == "screen-checkout")
    assert checkout["why"] == ["never tested", "1 of 1 oracle ideas not checked", "1 field(s)", "1 control(s) change data"]
    start = next(a for a in ranked if a["key"] == "screen-start-page")
    assert "2 of 4 controls never tried" in start["why"] and "tested 10 time(s) already" in start["why"]


def test_an_idea_counts_as_checked_wherever_its_test_started_and_breaks_where_it_is_about():
    context = {"screens": SCREENS}
    areas.merge(context, areas.extract(_run(_entry(1, "st01", idea="i-dialog"), answers=[("i-dialog", "broke")])),
                run="r1")
    dialog = next(a for a in areas.rank(context, [{"id": "i-dialog", "entity": "screen-dialog"}])
                  if a["key"] == "screen-dialog")
    assert "oracle ideas not checked" not in " ".join(dialog["why"])
    assert "1 oracle idea(s) broke here" in dialog["why"] and "never tested" in dialog["why"]


def test_places_the_map_lacks_are_areas_too_and_named_by_how_they_were_reached():
    context = {"screens": SCREENS, "discoveries": [
        {"id": "d1", "url": "http://shop/#/profile", "title": "Shop", "via": "menuitem:Go to user profile",
         "controls": ["button:upload"], "fields": ["textbox:username"], "changes_data": ["button:upload"]}]}
    areas.merge(context, areas.extract(_run(_entry(1, "/#/orders"))), run="r1")
    by_key = {a["key"]: a for a in areas.rank(context)}
    profile = by_key["d1"]
    assert profile["title"] == "/#/profile, reached by menuitem:Go to user profile" and not profile["mapped"]
    assert "reached by the Driver, not mapped" in profile["why"] and "1 field(s)" in profile["why"]
    assert by_key["/#/orders"]["route"] == "/#/orders" and "reached by the Driver, not mapped" in by_key["/#/orders"]["why"]
    # A leftover key that isn't a place (a slug a new map renamed) has no screen, and gets no bonus for it.
    context["coverage"]["screen-old-name"] = {"tests": 1, "runs": ["r0"], "tried": [], "inputs": {}, "ideas": {},
                                              "problems": {}}
    old = next(a for a in areas.rank(context) if a["key"] == "screen-old-name")
    assert old["why"] == ["no screen in the context for it", "tested 1 time(s) already"] and old["importance"] == 0.0
    long = {"id": "d2", "url": "http://shop/#/x", "via": "button:" + "y" * 100}
    assert len(next(a for a in areas.rank({"discoveries": [long]}) if a["key"] == "d2")["title"]) == 70


def test_learning_keeps_coverage_ranks_the_areas_and_tells_the_run_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path))
    monkeypatch.setattr(feedback, "ideas_for", lambda sut, product=None: [{"id": "i1", "entity": "screen-checkout"}])
    (tmp_path / "context_shop.json").write_text(json.dumps({"screens": SCREENS}), encoding="utf-8")
    run = tmp_path / "r1" / "output.json"
    run.parent.mkdir()
    run.write_text(json.dumps(_run(_entry(1, "st01", ["button:a"]), _entry(2, "/#/orders"))), encoding="utf-8")
    lines = feedback.learn("web_gui", run, "shop")
    context = json.loads((tmp_path / "context_shop.json").read_text(encoding="utf-8"))
    assert context["coverage"]["screen-start-page"]["tests"] == 1
    assert context["areas"][0]["key"] == "screen-checkout"
    assert "Covered: 2 area(s) tested this run, 2 for the first time: shop start page; /#/orders" in lines
    assert "Tested where the map has no screen: /#/orders" in lines
    assert lines[-1].startswith("Most important areas for the next run: shop checkout (")
    saved = json.loads(run.read_text(encoding="utf-8"))
    assert saved["learned"] == lines
    text = summarize(saved)
    assert "**Learned for the next run:**\n- Merged 0 test result(s)" in text
    assert "\n- Covered: 2 area(s) tested this run" in text


def test_a_discovered_screen_keeps_its_fields_in_the_context_and_they_count(tmp_path, monkeypatch):
    # Found in the live check: the profile page was reached with 4 fields and 3 controls
    # that change data, but the context kept none of it, so its score said only
    # "never tested; reached by the Driver, not mapped".
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path))
    monkeypatch.setattr(feedback, "ideas_for", lambda sut, product=None: [])
    profile = {"id": "d1", "signature": "/profile|", "url": "http://shop/profile", "title": "Shop",
               "from_state": "st01", "via": "menuitem:Go to user profile", "path": [], "elements": [],
               "controls_offered": 2, "controls": ["button:save", "textbox:username"],
               "fields": ["textbox:username"], "changes_data": ["button:save"], "features": ["text-field", "account"]}
    run = tmp_path / "r1" / "output.json"
    run.parent.mkdir()
    run.write_text(json.dumps({"casting_log": [{"test_number": 1, "result": {"discovered": profile}}]}),
                   encoding="utf-8")
    feedback.learn("web_gui", run, "shop")
    context = json.loads((tmp_path / "context_shop.json").read_text(encoding="utf-8"))
    assert context["discoveries"][0]["fields"] == ["textbox:username"]
    assert context["discoveries"][0]["features"] == ["text-field", "account"]          # for the oracle (#330)
    [area] = [a for a in context["areas"] if a["key"] == "d1"]
    assert area["why"] == ["never tested", "1 field(s)", "1 control(s) change data", "reached by the Driver, not mapped"]


def test_a_run_with_no_places_leaves_the_context_without_coverage(tmp_path, monkeypatch):
    # An API adapter's tests have no area: learning from them mustn't add empty coverage
    # or areas to its context, which for token_purchase is a committed file.
    monkeypatch.setenv("TRAILHOUND_CONTEXT_DIR", str(tmp_path))
    monkeypatch.setattr(feedback, "ideas_for", lambda sut, product=None: [])
    run = tmp_path / "r1" / "output.json"
    run.parent.mkdir()
    run.write_text(json.dumps(_run(_entry(1, ""))), encoding="utf-8")
    feedback.learn("token_purchase", run)
    context = json.loads((tmp_path / "context_token_purchase.json").read_text(encoding="utf-8"))
    assert "coverage" not in context and "areas" not in context


def test_idea_answers_are_the_latest_per_idea():
    checkpoints = [{"hypothesis": {"ideas": [{"id": "a", "verdict": "held"}, {"id": "b", "verdict": "maybe"}]}},
                   {"hypothesis": {"ideas": [{"id": "a", "verdict": "broke"}]}}]
    assert ledger.idea_answers(checkpoints) == {"a": "broke"}
