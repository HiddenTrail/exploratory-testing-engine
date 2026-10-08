"""Most of each round goes to new ground, and what can't be shown gets parked (issue #305).

The Skeptic doesn't stop reports, but it took over the testing after checkpoint 1: in
the lean Juice Shop run on 2026-10-06 every test of checkpoint 2 repeated an earlier one,
and no later checkpoint reached a new state. Some of its questions can't be answered
with this harness at all, so they came back checkpoint after checkpoint. Two rules:

1. In each round after the first, at most a third of the budget may follow up an earlier
   observation or question. Each cast test says which one in 'follows_up'. The engine
   runs only that many and drops the rest with the reason, so going over never costs a
   retry.
2. A claim the Skeptic objects to in PARK_AFTER checkpoints in a row is parked: its
   questions drop out of what the next checkpoint must answer, tests that follow it up
   are dropped, and it stays in the run's conclusion as inconclusive even if the Driver
   stops repeating it. "In a row" is followed through 'continues', with the same rule
   as interplay's objections that kept coming back.

A third rule came with #340. In the #330 benchmark all 15 checkpoints were weak, and the
same blocking question came back checkpoint after checkpoint ("About Us TypeError not
isolated from third-party scripts" at C1, C2 and C3), while each round opened new claims:

3. While questions from the last review block the verdict, a round answers them first:
   one test per blocking question, up to half the round, each with 'follows_up' set to
   the question's id and 'rules_out_if' saying what result would settle it. A round that
   answers too few is sent back once; after that it's accepted and the shortfall is
   recorded, so the rule never stops a run (the last-attempt salvage of #288 checks the
   tests one by one, without the count). The first test on each question doesn't count
   against the follow-up limit; they come out of the new ground. A question that still
   won't settle is parked with its claim by rule 2. Only questions about a claim's rival
   count: not one the debrief settled or the Driver conceded, not "not worth continuing",
   and not a coverage question about no claim, which is new ground anyway.

A fourth came with #352. In the full run runs/full340/F1 none of the 13 debrief answers
came with a test, and 9 were plans ("next round I'll open the basket in a new tab"). The
new-tab test was promised at C1, C2 and C3 and never ran: it wasn't blocking, so rule 3
didn't hold the Driver to it, and the oracle and new claims took each round.

4. A question the Driver answered in the debrief with change_approach is a promise. The
   next round answers it first, like a blocking question and in the same share of the
   round: rule 3's count and retry apply to both, and only as many as must be answered
   (half the round at most) skip the follow-up cap, since F1's 9 plans would otherwise
   take a whole round. Unlike rule 3, a promise needn't be about a claim. The checkpoint
   records which promises were kept: a test following it up ran. A promise it can't keep here is said in the round's reasoning
   once, as for rule 3, and a claim whose question keeps coming back is parked by rule 2.
   Running the promised test inside the debrief would need a round of its own there; the
   next round is where tests already run, so it's held to it there.

Generic: it reads the hypothesis and Skeptic schemas, and the outcome envelope's
action_id for repeats, nothing adapter-specific.
"""

from __future__ import annotations

import copy

from trailhound import outcome
from trailhound.interplay import lineages, objected

FOLLOW_UP_SHARE = 3       # at most 1/FOLLOW_UP_SHARE of a later round's budget
PARK_AFTER = 2            # objected to in this many checkpoints in a row

FOLLOW_UP_FIELD = {
    "type": "string",
    "description": ("The id of the earlier observation (like 'C1.O2') or open question (like 'C1.G3') this "
                    "test follows up. Empty when it tests something new. Always empty in the first round."),
}
RULES_OUT_FIELD = {
    "type": "string",
    "description": ("For a test that answers a question blocking the verdict: the result that would settle it "
                    "(for a rival explanation, the result that would rule it out), in one sentence. Empty otherwise."),
}
BLOCKING_SHARE = 2        # blocking questions get at most 1/BLOCKING_SHARE of a round


def with_follow_up_field(tool: dict) -> dict:
    """The adapter's casting tool with 'follows_up' added to each test, so no adapter
    has to declare it. Optional, so an answer without it is still valid. A schema of
    another shape is left as it is, and its tests are then all new ground."""
    tool = copy.deepcopy(tool)
    tests = tool.get("input_schema", {}).get("properties", {}).get("candidate_tests", {})
    if isinstance(tests.get("items", {}).get("properties"), dict):
        tests["items"]["properties"]["follows_up"] = FOLLOW_UP_FIELD
        tests["items"]["properties"]["rules_out_if"] = RULES_OUT_FIELD
    return tool


def blocking_ids(prior_feedback: dict | None) -> tuple[str, ...]:
    """The questions in the last review that block the verdict and are about a claim, so a
    test can settle them (parked claims' are already stripped by the loop). Left out: one
    the debrief settled or the Driver conceded, one the Skeptic says isn't worth continuing,
    and a coverage question about no claim."""
    review = (prior_feedback or {}).get("skeptic_review") or {}
    return tuple(g["id"] for g in review.get("gaps") or []
                 if g.get("blocks_verdict") and g.get("id") and g.get("about")
                 and g.get("kind") != "not_worth_continuing" and g.get("outcome") not in ("settled", "conceded"))


def promises(prior_feedback: dict | None, debrief: list[dict] | None) -> list[dict]:
    """The debrief's promises (#352): each question the Driver answered with change_approach
    that's still in the review the next round answers (so not parked), with what it said it
    would do. Not one the Skeptic says isn't worth continuing. A coverage question about no
    claim is kept, unlike rule 3: F1's never-run new-tab test was one."""
    open_ids = {g.get("id") for g in ((prior_feedback or {}).get("skeptic_review") or {}).get("gaps") or []}
    return [{"id": d["gap_id"], "promise": (d.get("answer") or {}).get("argument", "")}
            for d in debrief or [] if d.get("outcome") == "new_approach" and d.get("gap_id") in open_ids
            and d.get("kind") != "not_worth_continuing"]


def blocking_needed(blocking: tuple[str, ...], test_budget: int) -> int:
    """How many of a round's tests must answer blocking questions (#340): one per question,
    up to half the round."""
    return min(len(blocking), max(1, test_budget // BLOCKING_SHARE)) if blocking else 0


def _tests(data) -> list[dict]:
    tests = data.get("candidate_tests") if isinstance(data, dict) else None
    return [t for t in (tests if isinstance(tests, list) else []) if isinstance(t, dict)]


def blocking_answered(tests: list[dict], blocking: tuple[str, ...]) -> list[str]:
    """The blocking questions these tests answer, in the review's order."""
    asked = {t.get("follows_up") for t in tests if isinstance(t.get("follows_up"), str)}
    return [b for b in blocking if b in asked]


def rules_out_errors(data, blocking: tuple[str, ...], promised: tuple[str, ...] = ()) -> list[str]:
    """A test answering a blocking question must say what would settle it (#340). Checked on
    each test, so the last-attempt salvage (#288) can keep the others."""
    errors = []
    for i, test in enumerate(_tests(data)):
        if not isinstance(test.get("follows_up"), str) or test["follows_up"] not in blocking:
            continue
        said = test.get("rules_out_if")
        if not isinstance(said, str) or not said.strip():
            why = "you promised it in the debrief" if test["follows_up"] in promised else "it blocks the verdict"
            errors.append(f"candidate_tests[{i}] answers {test['follows_up']}, which comes first because {why}: say "
                          "in 'rules_out_if' (a string) what result would settle it.")
    return errors


def blocking_shortfall(data, blocking: tuple[str, ...], test_budget: int, promised: tuple[str, ...] = ()) -> list[str]:
    """A round that answers too few of the questions that come first: those blocking the
    verdict (#340), and the debrief's promises among them (#352). The loop sends it back
    once only (once()), so a question the Driver can't answer here never stops a run."""
    needed = blocking_needed(blocking, test_budget)
    answered = blocking_answered(_tests(data), blocking)
    if len(answered) >= needed or (isinstance(data, dict) and data.get("give_up")):
        return []
    left = [b for b in blocking if b not in answered]
    why = ("come first (they block the verdict, or you promised them in the debrief)" if promised
           else "block the verdict")
    return [f"{len(blocking)} question(s) from the last review {why}, and this round answers "
            f"{len(answered)}. Answer at least {needed} of them, one test each: set 'follows_up' to the question's "
            f"id and 'rules_out_if' to the result that would settle it, starting from its next_test"
            f"{' or your promise' if promised else ''}. Not answered "
            f"yet: {', '.join(left)}. If one can't be tested here, say why in the round's reasoning; this is "
            f"asked once."]


def once(check):
    """The check's errors the first time it finds any, and none after: a rule worth one
    retry, not a run."""
    said = []

    def checked(data):
        if said:
            return []
        errors = check(data)
        if errors:
            said.append(True)
        return errors
    return checked


def follow_up_cap(test_budget: int) -> int:
    return max(1, test_budget // FOLLOW_UP_SHARE)


# Tests that check no oracle idea and follow up nothing (#312): at most this share of a
# round, so most of the testing follows the oracle.
FREE_SHARE = 3


def free_cap(test_budget: int) -> int:
    return max(1, test_budget // FREE_SHARE)


def casting_note(cap: int, first_round: bool, free: int | None = None, blocking: tuple[str, ...] = (),
                 needed: int = 0, promised: tuple[str, ...] = ()) -> str:
    """blocking: every question that comes first, the debrief's promises (#352) included."""
    oracle = ("" if free is None else
              f"\n\n{'Of the other tests, most' if blocking else 'Most tests'} should check an idea from "
              f"'oracle_ranked': put its id in oracle_claim_id; its "
              f"'where' says where to start. 'oracle_progress' shows which ideas no test has checked yet. At most "
              f"{free} test(s) may check something no idea covers and follow up nothing; more are dropped "
              f"without running.")
    if first_round:
        return "\n\nThis is the first round: leave 'follows_up' empty on every test." + oracle
    held = [b for b in blocking if b not in promised]
    which = ", and ".join(part for part in (
        f"the questions that block the verdict: {', '.join(held)}" if held else "",
        f"what you promised in the debrief: {', '.join(promised)} (your words are in 'promises')" if promised else "")
        if part)
    start = "each question's next_test" + (" or your promise" if promised else "")
    first = (f"\n\nFirst, {which}. At least {needed} test(s) "
             f"must answer them, one per question, starting from {start}: set 'follows_up' to the "
             f"question's id and 'rules_out_if' to the result that would settle it (for a rival explanation, the "
             f"result that would rule it out). The first test on each, up to {needed}, doesn't count against the "
             f"limit below."
             if blocking else "")
    return (first + f"\n\nAt most {cap} of this round's tests may follow up an earlier observation or question: "
            f"set 'follows_up' to its id. Leave it empty on the rest and use them on something not tested yet. A "
            f"follow-up over the limit, or on a claim in 'parked', is dropped without running." + oracle)


def oracle_id_errors(data, idea_ids) -> list[str]:
    """An oracle_claim_id that isn't one of the ranked ideas is sent back (#312): a made-up
    id can't be answered or learned from (#107)."""
    tests = data.get("candidate_tests") if isinstance(data, dict) else None
    errors = []
    for i, test in enumerate(tests if isinstance(tests, list) else []):
        claim = test.get("oracle_claim_id") if isinstance(test, dict) else None
        if isinstance(claim, str) and claim and claim not in idea_ids:
            errors.append(f"candidate_tests[{i}].oracle_claim_id is '{claim}', which isn't an idea in "
                          "'oracle_ranked'. Copy an id exactly as shown there, or leave it empty.")
    return errors


def follow_up_errors(data, known_ids) -> list[str]:
    """Only a follows_up naming nothing known is sent back. Too many follow-ups, or
    ones on parked claims, are dropped by limit() instead, which costs no retry."""
    tests = data.get("candidate_tests") if isinstance(data, dict) else None
    errors = []
    for i, test in enumerate(tests if isinstance(tests, list) else []):
        if not isinstance(test, dict):
            continue
        follows = test.get("follows_up", "")
        if not isinstance(follows, str):
            errors.append(f"candidate_tests[{i}].follows_up must be a string (empty for new ground)")
        elif follows and follows not in known_ids:
            known = ", ".join(sorted(known_ids)) or "none, this is the first round"
            errors.append(f"candidate_tests[{i}].follows_up is '{follows}', which isn't an earlier observation or "
                          f"question (ids: {known}). Leave it empty for new ground.")
    return errors


def limit(tests: list[dict], cap: int, parked_ids, free: int | None = None,
          blocking: tuple[str, ...] = (), exempt: int | None = None) -> tuple[list[dict], list[dict]]:
    """The tests to run, and the ones dropped with why, in the dropped_tests shape (#288).
    free: how many tests may check no oracle idea and follow up nothing (#312); None for
    a run without an oracle. blocking: the questions that come first, whose first test
    each doesn't count against the follow-up cap (#340), up to `exempt` of them
    (blocking_needed): with many promises (#352) they would otherwise take the whole round."""
    kept, dropped, follow_ups, frees = [], [], 0, 0
    answered: set[str] = set()
    for test in tests:
        follows = test.get("follows_up") or ""
        unguided = not follows and not test.get("oracle_claim_id")
        if (follows in blocking and follows not in answered and follows not in parked_ids
                and (exempt is None or len(answered) < exempt)):
            answered.add(follows)
            kept.append(test)
        elif follows in parked_ids:
            dropped.append({"test": test, "errors": [f"follows up {follows}, which is parked: the tests couldn't "
                                                    "settle it, so it gets no more of them"]})
        elif follows and follow_ups >= cap:
            dropped.append({"test": test, "errors": [f"over the limit of {cap} follow-up test(s) a round"]})
        elif unguided and free is not None and frees >= free:
            dropped.append({"test": test, "errors": [f"over the limit of {free} test(s) a round that check no "
                                                    "oracle idea"]})
        else:
            follow_ups += bool(follows)
            frees += unguided
            kept.append(test)
    return kept, dropped


def oracle_progress(ranked: list[dict], casting_log: list[dict], checkpoints: list[dict]) -> dict:
    """What the Driver is told about the oracle so far (#312): the ideas no test has
    checked yet, and the latest answer for each one that was."""
    cited = {e.get("oracle_claim_id") for e in casting_log if e.get("oracle_claim_id")}
    answers: dict[str, str] = {}
    for cp in checkpoints:
        for a in (cp.get("hypothesis") or {}).get("ideas") or []:
            if isinstance(a, dict) and a.get("id"):
                answers[a["id"]] = a.get("verdict", "")
    return {"not_checked_yet": [i["id"] for i in ranked if i.get("id") not in cited],
            "answered": [{"id": k, "verdict": v} for k, v in answers.items()]}


def repeats(casting_log: list[dict], checkpoint: int) -> int:
    """How many of a checkpoint's tests repeated an action from an earlier checkpoint,
    declared as a follow-up or not. Compared by the outcome envelope's action_id."""
    earlier = {r["action_id"] for r in outcome.rows(casting_log) if r.get("checkpoint", 0) < checkpoint}
    return sum(1 for r in outcome.rows(casting_log) if r.get("checkpoint") == checkpoint and r["action_id"] in earlier)


def parked_claims(checkpoints: list[dict]) -> dict[str, int]:
    """Each claim (by its first observation id) the Skeptic objected to in PARK_AFTER or
    more checkpoints in a row, with the longest run. Once parked, a claim stays parked."""
    root = lineages(checkpoints)
    streak, parked, previous = {}, {}, set()
    for cp in checkpoints:
        now = objected(cp, root)
        for claim in now:
            streak[claim] = streak.get(claim, 0) + 1 if claim in previous else 1
            if streak[claim] >= PARK_AFTER:
                parked[claim] = max(parked.get(claim, 0), streak[claim])
        previous = now
    return parked


def parked_ids(checkpoints: list[dict], parked: dict[str, int]) -> set[str]:
    """Every observation id on a parked claim's line, and every question only about them."""
    root = lineages(checkpoints)
    ids = {oid for oid, first in root.items() if first in parked}
    for cp in checkpoints:
        for gap in (cp.get("skeptic_review") or {}).get("gaps", []):
            about = gap.get("about") or []
            if about and all(root.get(a, a) in parked for a in about):
                ids.add(gap.get("id"))
    return ids


def without_parked(review: dict, ids: set[str]) -> dict:
    """The review without the questions about parked claims."""
    return {**review, "gaps": [g for g in review.get("gaps", []) if g.get("id") not in ids]}


def for_driver(checkpoints: list[dict], parked: dict[str, int]) -> list[dict]:
    """What the Driver is told about each parked claim: its latest id and why."""
    root = lineages(checkpoints)
    latest = {}
    for oid, first in root.items():
        if first in parked:
            latest[first] = oid
    return [{"claim": latest.get(first, first), "first_seen_as": first,
             "why": f"The Skeptic objected to it in {n} checkpoints in a row and the tests couldn't settle it. "
                    "Spend no more tests on it, keep reporting it if it still holds, and list it as an obstacle."}
            for first, n in parked.items()]


def keep_parked(observations: list[dict], checkpoints: list[dict], parked: dict[str, int]) -> list[dict]:
    """The run's conclusion with each parked claim kept, even if the Driver stopped
    repeating it: its latest version, inconclusive, marked parked."""
    root = lineages(checkpoints)
    present = {root.get(o["id"], o["id"]) for o in observations}
    for o in observations:
        if root.get(o["id"], o["id"]) in parked:
            o["parked"] = True
    latest = {}
    for cp in checkpoints:
        for o in (cp.get("hypothesis") or {}).get("observations", []):
            first = root.get(o["id"], o["id"])
            if first in parked and first not in present:
                latest[first] = o
    return observations + [{**o, "status": "inconclusive", "parked": True, "skeptic_note": ""} for o in latest.values()]
