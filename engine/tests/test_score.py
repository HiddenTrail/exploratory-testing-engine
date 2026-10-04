"""Scoring a web_gui run against a target's known problems (issue #277). No model calls."""

import json
from pathlib import Path

from engine.adapters.web_gui import score

KNOWN = json.loads((Path(__file__).resolve().parents[2] / "test-targets" / "known-problems" / "juice-shop.json")
                   .read_text(encoding="utf-8"))


def _test(n, console=(), failed=(), start_as=None):
    request = {"state": "st01", "control": "button:x", **({"start_as": start_as} if start_as else {})}
    return {"test_number": n, "request": request,
            "result": {"signals": {"console_errors": list(console)}, "signals_weak": {"failed_requests": list(failed)}}}


def _output(tests, observations):
    return {"casting_log": tests, "observations": observations}


def test_the_juice_shop_list_is_well_formed_and_marked_unreviewed():
    ids = [p["id"] for p in KNOWN["problems"]]
    assert len(ids) == len(set(ids)) and all(p["match"]["signal"] in ("console_error", "failed_request")
                                             for p in KNOWN["problems"])
    assert all(p["named_by"] for p in KNOWN["problems"]) and KNOWN["review"]["status"] == "proposed"


def test_an_observation_finds_a_problem_when_its_test_shows_it_and_its_claim_names_it():
    out = _output([_test(1, console=["ERROR TypeError: Cannot read properties of undefined (reading 'nativeElement')"])],
                  [{"id": "C1.O1", "kind": "finding", "status": "inconclusive", "tests": [1],
                    "claim": "The About page throws a TypeError on load"}])
    result = score.score(KNOWN, out)
    assert [f["id"] for f in result["found"]] == ["JS02"]
    assert result["found"][0]["by"] == [{"observation": "C1.O1", "kind": "finding", "status": "inconclusive", "replay": ""}]


def test_evidence_alone_doesnt_count_when_the_claim_is_about_something_else():
    # One observation about a 403 had "found" the failing CDN too, from the same test.
    out = _output([_test(6, console=["Failed to load resource: the server responded with a status of 403 ()"],
                         failed=["GET /1.3.0/material.min.css -> net::ERR_ABORTED"])],
                  [{"id": "C3.O3", "kind": "finding", "tests": [6], "claim": "Profile page gets a 403 on load"}])
    result = score.score(KNOWN, out)
    assert [f["id"] for f in result["found"]] == ["JS03"]
    assert result["seen_not_reported"] == [{"id": "JS05", "title": KNOWN["problems"][4]["title"], "tests": [6]}]


def test_a_new_tab_problem_only_counts_from_a_new_tab_test():
    error = "ERROR TypeError: Cannot read properties of null (reading 'Products')"
    claim = {"id": "C1.O1", "kind": "anomaly", "tests": [1], "claim": "Opening the basket throws a TypeError"}
    assert score.score(KNOWN, _output([_test(1, console=[error])], [claim]))["found"] == []
    found = score.score(KNOWN, _output([_test(1, console=[error], start_as="new_tab")], [claim]))["found"]
    assert [f["id"] for f in found] == ["JS01"]


def test_the_summary_says_found_x_of_y_and_what_was_missed():
    text = score.summary(score.score(KNOWN, _output([], [])))
    assert text.startswith("**Known problems found: 0 of 5** (juice-shop, list proposed).")
    assert "- missed JS01:" in text and "Out of the harness's reach, not counted: JS-X1." in text
