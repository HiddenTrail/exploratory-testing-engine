"""How well the Driver answered the Skeptic, measured from a run's checkpoints (issue #257).

Without numbers, "the Driver got smarter" is a feeling. This counts, from the engine's
own hypothesis and Skeptic schemas and nothing else:

- the gaps the Skeptic raised each checkpoint, and how many blocked the verdict
- how the Driver answered the previous checkpoint's gaps (tested, untestable, resolved,
  not attempted), and how many blocking gaps it didn't even attempt
- how many of its answers the Skeptic accepted
- objections that came back: an observation the Skeptic objected to again in the next
  checkpoint, followed through 'continues' (C1.O2 -> C2.O2 -> C3.O2 is one claim)
- the checkpoint at which the Skeptic was first satisfied, if it ever was

An objection is a gap that blocks the verdict and is about the observation, or an
observation check saying its evidence doesn't tell it from its rival. No model call:
the epic "Driver strategy" (#262) judges every later change by these numbers.
"""

from __future__ import annotations

from trailhound.tools import PRIOR_GAP_STATUSES

SATISFIED = "strong_enough"


def lineages(checkpoints: list[dict]) -> dict[str, str]:
    """Each observation id mapped to the first id of its claim, by following 'continues'."""
    root: dict[str, str] = {}
    for cp in checkpoints:
        for o in (cp.get("hypothesis") or {}).get("observations", []):
            earlier = o.get("continues") or ""
            root[o["id"]] = root.get(earlier, earlier) if earlier else o["id"]
    return root


def objected(cp: dict, root: dict[str, str]) -> set[str]:
    """The claims (by lineage) the Skeptic objected to in this checkpoint."""
    review = cp.get("skeptic_review") or {}
    ids = {oid for g in review.get("gaps", []) if g.get("blocks_verdict") for oid in g.get("about", [])}
    ids |= {c["observation_id"] for c in review.get("observation_checks", [])
            if c.get("discriminates_from_rival") is False}
    return {root.get(i, i) for i in ids}


def _debrief_counts(thread: list[dict]) -> dict:
    """How a checkpoint's debrief went (#266): the Driver's stances, and whether the
    Skeptic was convinced."""
    stances = [((d.get("answer") or {}).get("stance") or "unanswered") for d in thread]
    convinced = [((d.get("judgement") or {}).get("convinced") or "unjudged") for d in thread]
    return {
        "questions": len(thread),
        "defended": stances.count("defend"), "conceded": stances.count("concede"),
        "changed_approach": stances.count("change_approach"),
        "convinced": convinced.count("yes"), "partly": convinced.count("partly"),
        "open_after": sum(1 for d in thread if d.get("outcome") in ("open", "new_approach")),
    }


def measure(checkpoints: list[dict]) -> dict:
    """Per checkpoint and for the whole run. Empty when the run has no checkpoints. A
    checkpoint missing its hypothesis or review (a run cut short) counts as empty."""
    if not checkpoints:
        return {}
    root = lineages(checkpoints)
    rows, streak, longest = [], {}, {}
    previous_blocking: set[str] = set()
    previous_objected: set[str] = set()
    for cp in checkpoints:
        review, hypothesis = cp.get("skeptic_review") or {}, cp.get("hypothesis") or {}
        gaps = review.get("gaps", [])
        answers = hypothesis.get("prior_gaps", [])
        statuses = {s: sum(1 for a in answers if a.get("status") == s) for s in PRIOR_GAP_STATUSES}
        checks = review.get("prior_gaps_check", [])
        objected_now = objected(cp, root)
        for claim in objected_now:
            streak[claim] = streak.get(claim, 0) + 1 if claim in previous_objected else 1
            longest[claim] = max(longest.get(claim, 0), streak[claim])
        rows.append({
            "checkpoint": cp.get("checkpoint", len(rows) + 1),
            "verdict": review.get("verdict", ""),
            "gaps": len(gaps),
            "blocking_gaps": sum(1 for g in gaps if g.get("blocks_verdict")),
            "answered": statuses,
            "blocking_not_attempted": sum(1 for a in answers if a.get("status") == "not_attempted"
                                          and a.get("gap_id") in previous_blocking),
            "answers_accepted": sum(1 for c in checks if c.get("accepted")),
            "answers_judged": len(checks),
            "objections": len(objected_now),
            "objections_again": len(objected_now & previous_objected),
            "debrief": _debrief_counts(cp.get("debrief") or []),
        })
        previous_blocking = {g.get("id") for g in gaps if g.get("blocks_verdict")}
        previous_objected = objected_now

    satisfied_at = next((r["checkpoint"] for r in rows if r["verdict"] == SATISFIED), None)
    debrief = {key: sum(r["debrief"][key] for r in rows) for key in rows[0]["debrief"]}
    last_thread = (checkpoints[-1].get("debrief") or [])
    still_open = [d["gap_id"] for d in last_thread if d.get("outcome") in ("open", "new_approach")]
    stubborn = sorted(((n, claim) for claim, n in longest.items() if n > 1), reverse=True)
    return {
        "checkpoints": rows,
        "run": {
            "checkpoints": len(rows),
            "satisfied_at": satisfied_at,
            "gaps": sum(r["gaps"] for r in rows),
            "blocking_gaps": sum(r["blocking_gaps"] for r in rows),
            "prior_gaps_tested": sum(r["answered"]["tested"] for r in rows),
            "prior_gaps_answered": sum(sum(r["answered"].values()) for r in rows),
            "blocking_not_attempted": sum(r["blocking_not_attempted"] for r in rows),
            "answers_accepted": sum(r["answers_accepted"] for r in rows),
            "answers_judged": sum(r["answers_judged"] for r in rows),
            "objections_again": sum(r["objections_again"] for r in rows),
            # Claims objected to in more than one checkpoint in a row, longest first:
            # [claim's first id, checkpoints in a row].
            "stubborn_objections": [[claim, n] for n, claim in stubborn],
            "debrief": debrief,
            # Questions left open after the last checkpoint's debrief: the run's loose ends.
            "still_open": still_open,
        },
    }


def summary_lines(interplay: dict) -> list[str]:
    """The run-level numbers as short sentences, for the report and the CI summary."""
    run = interplay.get("run")
    if not run:
        return []
    satisfied = (f"satisfied at checkpoint {run['satisfied_at']}" if run["satisfied_at"]
                 else f"never satisfied in {run['checkpoints']} checkpoint(s)")
    lines = [
        f"The Skeptic raised {run['gaps']} gap(s), {run['blocking_gaps']} blocking, and was {satisfied}.",
        f"The Driver tested {run['prior_gaps_tested']} of the {run['prior_gaps_answered']} earlier gap(s) it answered; "
        f"the Skeptic accepted {run['answers_accepted']} of {run['answers_judged']} answers.",
    ]
    if run["blocking_not_attempted"]:
        lines.append(f"{run['blocking_not_attempted']} blocking gap(s) weren't even attempted.")
    d = run.get("debrief") or {}
    if d.get("questions"):
        lines.append(f"In the debriefs the Driver defended {d['defended']}, conceded {d['conceded']} and changed "
                     f"approach on {d['changed_approach']} of {d['questions']} question(s); the Skeptic was convinced "
                     f"by {d['convinced']} and partly by {d['partly']}.")
    if run.get("still_open"):
        lines.append(f"Still open at the end: {', '.join(run['still_open'])}.")
    if run["stubborn_objections"]:
        worst = ", ".join(f"{claim} ({n} checkpoints in a row)" for claim, n in run["stubborn_objections"])
        lines.append(f"Objections that kept coming back: {worst}.")
    return lines
