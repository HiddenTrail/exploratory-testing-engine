"""The report and the summary lead with each claim's result, not the checkpoint verdict
(issue #342). No model calls."""

import html
import re

from trailhound.report import _render_checkpoint, claims_line
from trailhound.run_summary import summarize
from trailhound.tools import claim_results, final_observations


def _obs(oid):
    return {"id": oid, "kind": "finding", "severity": "low", "claim": f"claim {oid}", "tests": [1],
            "mechanism": "m", "rival": "r", "why": "w", "continues": ""}


def _checkpoint(n, telling, blocked=()):
    """A checkpoint whose observations' rival checks say `telling` (id -> bool), with
    blocking gaps about the ids in `blocked`."""
    hypothesis = {"summary": "s", "behaviors": [], "untested": [], "prior_gaps": [],
                  "observations": [_obs(oid) for oid in telling]}
    review = {"verdict": "weak" if blocked or not all(telling.values()) else "strong_enough",
              "verdict_reason": "because", "coverage": {"material": False, "note": "", "untouched": []},
              "prior_gaps_check": [],
              "observation_checks": [{"observation_id": oid, "discriminates_from_rival": ok, "note": ""}
                                     for oid, ok in telling.items()],
              "gaps": [{"id": f"C{n}.G{i}", "gap": "g", "next_test": "t", "blocks_verdict": True, "about": [oid],
                        "kind": "rival_not_tested"} for i, oid in enumerate(blocked, start=1)]}
    return {"hypothesis": hypothesis, "skeptic_review": review}


def test_each_claim_says_what_holds_it_back():
    cp = _checkpoint(1, {"C1.O1": True, "C1.O2": False, "C1.O3": True}, blocked=["C1.O3"])
    results = {r["id"]: r for r in claim_results(cp["hypothesis"], cp["skeptic_review"])}
    assert results["C1.O1"] == {"id": "C1.O1", "status": "corroborated", "held_back": []}
    assert results["C1.O2"]["held_back"] == ["its tests don't tell it from its rival"]
    assert results["C1.O3"]["held_back"] == ["open blocking question C1.G1"]
    assert claims_line(list(results.values())) == "1 of 3 claim(s) hold up, 2 inconclusive"
    assert claims_line([]) == "No claims"


def test_the_checkpoint_header_leads_with_the_claims_and_the_verdict_follows():
    cp = _checkpoint(2, {"C2.O1": True, "C2.O2": False})
    page = html.unescape(_render_checkpoint(2, cp, {}, lambda entry: ""))
    visible = re.sub(r"<details.*?</details>", " ", page, flags=re.S)
    assert "Checkpoint 2: 1 of 2 claim(s) hold up, 1 inconclusive</h3>" in visible
    assert "weak" in visible.split("Skeptic:")[1]                      # the verdict is in the Skeptic's line
    assert "badge" not in page.split("</h3>")[0]                       # and no longer in the heading
    assert "(held back: its tests don't tell it from its rival)" in visible


def test_the_summary_says_how_the_claims_came_out_before_the_table():
    # One checkpoint weak with 2 of 3 claims holding up: the verdict alone says little.
    checkpoints = [_checkpoint(1, {"C1.O1": False, "C1.O2": False}),
                   _checkpoint(2, {"C2.O1": True, "C2.O2": True, "C2.O3": False}, blocked=["C2.O3"])]
    observations = [{**o, "status": s} for o, s in zip(final_observations(checkpoints[1]["hypothesis"],
                                                                         checkpoints[1]["skeptic_review"]),
                                                       ("corroborated", "corroborated", "inconclusive"))]
    observations[0]["parked"] = True                                   # parked, and still corroborated
    observations.append({**_obs("C1.O2"), "status": "inconclusive", "parked": True})
    text = summarize({"checkpoints": checkpoints, "observations": observations, "casting_log": []})
    assert ("**Claims:** 2 of 4 claim(s) hold up at the end of the run (the last checkpoint's 3, plus 1 parked "
            "earlier); by checkpoint C1 0 of 2, C2 2 of 3. The Skeptic's verdicts: weak, weak.") in text
    assert text.index("**Claims:**") < text.index("| Id |")
    # The summary doesn't list the gaps, so a blocking question comes with its text.
    assert ("| C2.O3 | finding | inconclusive | its tests don't tell it from its rival; open blocking question "
            "C2.G1 (g) |") in text
    assert "| C1.O2 | finding | inconclusive | parked: objected to in checkpoints in a row" in text
    assert "| C2.O1 | finding | corroborated |  |" in text                # a corroborated claim isn't held back


def test_a_run_that_stopped_before_its_conclusion_says_so():
    # Found in review: runs that stopped with an error said "0 of 0 hold up".
    text = summarize({"checkpoints": [_checkpoint(1, {"C1.O1": True, "C1.O2": False})], "casting_log": [],
                      "stopped_reason": "error", "error": "boom"})
    assert "**Claims:** the run stopped before its conclusion; by checkpoint C1 1 of 2." in text
