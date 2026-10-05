"""The readable report (issue #285): the headline, the score, the glossary, what came of
the oracle's ideas, and what the Driver is no longer shown. No model calls."""

from engine import loop
from engine.adapters.web_gui import score as score_mod
from engine.adapters.web_gui import session as live_session
from engine.glossary import glossary_for
from engine.report import _headline, _render_glossary, _render_oracle_outcomes

COUNTS = {"bug": 0, "anomaly": 1, "finding": 2}


def _obs(oid, kind, status, severity, claim, tests=()):
    return {"id": oid, "kind": kind, "status": status, "severity": severity, "claim": claim, "tests": list(tests)}


def test_the_headline_is_the_most_serious_confirmed_thing_never_just_the_first():
    observations = [_obs("C3.O1", "finding", "inconclusive", "low", "An overlay covers the sidenav"),
                    _obs("C3.O2", "anomaly", "corroborated", "medium", "The About page throws a TypeError")]
    assert _headline(observations, [], COUNTS, None) == "The About page throws a TypeError"
    assert _headline(observations, [{"title": "Low one", "severity": "low"}, {"title": "Big one", "severity": "high"}],
                     COUNTS, None) == "Big one"
    unconfirmed = [_obs("C3.O1", "finding", "inconclusive", "low", "An overlay covers the sidenav")]
    assert _headline(unconfirmed, [], {"bug": 0, "anomaly": 0, "finding": 1}, {"found": [{}, {}], "known": 5}) == (
        "No confirmed problem · found 2 of 5 known problems")
    assert _headline(unconfirmed, [], {"bug": 0, "anomaly": 0, "finding": 1}, None) == "No confirmed problem"


def test_the_glossary_explains_only_the_tags_the_run_used():
    output = {"observations": [{"kind": "finding", "status": "inconclusive"}],
              "checkpoints": [{"hypothesis": {"areas": [{"coverage": "can_it_work", "quality": "concerns",
                                                         "confidence": "low"}]},
                               "debrief": [{"answer": {"stance": "change_approach"}, "outcome": "new_approach",
                                            "judgement": {"convinced": "partly"}}]}]}
    terms = [t for _, ts in glossary_for(output) for t, _ in ts]
    assert terms == ["finding", "inconclusive", "L1 (can it work)", "Concerns", "low", "change approach",
                     "convinced: partly", "new approach"]
    assert "anomaly" not in terms and "settled" not in terms
    html = _render_glossary(output)
    assert "Glossary of the tags used here" in html and "the Driver will test it differently next round" in html


def test_what_came_of_each_oracle_idea():
    ranked = [{"id": "oracle:a", "claim": "Prices add up"}, {"id": "oracle:b", "claim": "Pages load cleanly"}]
    log = [{"test_number": 1, "oracle_claim_id": "oracle:a", "prediction_matched": True},
           {"test_number": 2, "oracle_claim_id": "oracle:a", "prediction_matched": False},
           {"test_number": 3, "oracle_claim_id": ""}]
    html = _render_oracle_outcomes(ranked, log, [_obs("C1.O1", "anomaly", "inconclusive", "low", "c", tests=[2])])
    assert "The oracle's ideas: 1 of 2 tested" in html
    assert "<td>Prices add up</td><td>2</td><td>1 of 2</td><td>C1.O1</td>" in html
    assert "<td>Pages load cleanly</td><td>-</td><td>-</td><td>-</td>" in html


def test_a_web_run_scores_itself_from_its_products_known_problems(monkeypatch):
    monkeypatch.delenv("WEB_GUI_KNOWN_PROBLEMS", raising=False)
    monkeypatch.setenv("WEB_GUI_PRODUCT", "juice-shop")
    result = score_mod.score_run({"casting_log": [], "observations": []})
    assert result["known"] == 5 and result["target"] == "juice-shop"
    monkeypatch.setenv("WEB_GUI_PRODUCT", "no-such-product")
    assert score_mod.score_run({"casting_log": [], "observations": []}) is None


def test_the_driver_names_areas_after_parts_of_the_product():
    reference = type("R", (), {"states": [{"url": "http://h/#/"}, {"url": "http://h/#/basket"},
                                          {"url": "http://h/#/privacy-security/privacy-policy"},
                                          {"url": "http://h/#/basket"}]})()
    assert live_session.product_areas(reference) == ["start page", "basket", "privacy security / privacy policy"]
    assert live_session.product_areas(reference, "juice-shop")[0] == "Juice Shop login page"


def test_an_empty_happy_day_example_is_left_out_of_the_evidence():
    adapter = type("A", (), {"api_schema_doc": "doc", "onboarding_extra": {}})()
    assert "happy_day_example" not in loop._base_evidence(adapter, {"request": {}, "response": {}})
    assert loop._base_evidence(adapter, {"request": {"x": 1}, "response": {}})["happy_day_example"]["request"] == {"x": 1}
