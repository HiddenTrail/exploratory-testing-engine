"""The Skeptic knows what a test here can do, and an untestable doubt doesn't block (issue
#379). No model calls."""

import json

from trailhound import loop, steering
from trailhound.adapters.web_gui import adapter as web_gui
from trailhound.config import RunConfig
from trailhound.tools import (OBJECTION_KINDS, SKEPTIC_SYSTEM_PROMPT, claim_results, stamp_gap_ids,
                              validate_skeptic_response)


def _review(*gaps):
    return {"verdict": "weak", "verdict_reason": "v", "coverage": {"material": False, "untouched": [], "note": "n"},
            "prior_gaps_check": [],
            "observation_checks": [{"observation_id": "C1.O1", "discriminates_from_rival": True,
                                    "rival_is_genuine": True, "kind": "anomaly", "note": "n"}],
            "gaps": [{"gap": "g", "next_test": "t", "blocks_verdict": blocks, "kind": kind, "about": ["C1.O1"]}
                     for kind, blocks in gaps]}


def test_an_untestable_doubt_never_blocks_but_holds_its_claim_back():
    review = _review(("harness_limit", True), ("rival_not_tested", False))
    stamp_gap_ids(1, review)
    limit = review["gaps"][0]
    assert limit["blocks_verdict"] is False and limit["asked_to_block"] is True
    [result] = claim_results({"observations": [{"id": "C1.O1"}]}, review)
    assert result == {"id": "C1.O1", "status": "inconclusive", "held_back": ["a doubt this harness can't settle, C1.G1"]}
    # Without it the same claim holds up: the rule didn't loosen anything else.
    review["gaps"] = review["gaps"][1:]
    assert claim_results({"observations": [{"id": "C1.O1"}]}, review)[0]["status"] == "corroborated"


def test_it_is_a_kind_the_skeptic_may_use_and_never_comes_first():
    assert "harness_limit" in OBJECTION_KINDS
    review = _review(("harness_limit", False))
    # Not one of the four objections: with only such doubts left the verdict can be strong_enough.
    review["verdict"] = "strong_enough"
    assert validate_skeptic_response(review, observations=[{"id": "C1.O1", "kind": "anomaly"}]) == []
    stamp_gap_ids(1, review)
    review["gaps"][0]["blocks_verdict"] = True           # even if something set it again
    assert steering.blocking_ids({"skeptic_review": review}) == ()
    debrief = [{"gap_id": "C1.G1", "kind": "harness_limit", "outcome": "new_approach", "answer": {"argument": "a"}}]
    assert steering.promises({"skeptic_review": review}, debrief) == []


def test_the_skeptic_is_told_what_a_test_can_do(monkeypatch):
    assert "A blocking question needs a next_test this harness can run" in SKEPTIC_SYSTEM_PROMPT
    assert "read the DOM, CSS, styles or\na screenshot" in web_gui.TEST_CAPABILITIES
    assert web_gui.ADAPTER.test_capabilities == web_gui.TEST_CAPABILITIES
    sent = {}

    def fake(client, **kw):
        sent.update(json.loads(kw["user_message"]))
        return _review()
    monkeypatch.setattr(loop, "call_tool_with_retry", fake)
    hypothesis = {"summary": "s", "observations": [{"id": "C1.O1", "kind": "anomaly", "claim": "c"}], "prior_gaps": []}
    loop.get_skeptic_review(None, RunConfig(lean=True), hypothesis, test_capabilities="steps: click")
    assert sent["what_a_test_can_do"] == "steps: click"
    sent.clear()
    loop.get_skeptic_review(None, RunConfig(lean=True), hypothesis)
    assert "what_a_test_can_do" not in sent
