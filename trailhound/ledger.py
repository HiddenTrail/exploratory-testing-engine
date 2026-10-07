"""Every idea and every error gets an answer (issue #312).

The oracle exists to guide the testing, and the harness records the errors behind what
a tester would report. In the four lean runs on 2026-10-06, the Driver cited at most one
of 15 ideas a run, and every run saw 4 or 5 of Juice Shop's 5 known problems in its
tests' signals but reported 0 to 2. This holds the Driver to both:

- Each oracle idea a checkpoint's tests checked needs an answer in that checkpoint's
  hypothesis: held, broke, or couldn't tell, with the tests.
- Each trusted problem a test recorded (the outcome envelope's `problems`, #312) needs
  an observation that cites a test showing it, or a dismissal with a reason. Once
  answered, it stays answered for the rest of the run.

Generic: it reads the casting log's oracle ids and the outcome envelopes' problem
tokens, never an adapter's prose.
"""

from __future__ import annotations

from trailhound import outcome

VERDICTS = ("held", "broke", "cannot_tell")
_SHOWN = 12          # how many open errors a validation message lists


def problems_by_test(casting_log: list[dict]) -> dict[int, list[str]]:
    return {r["test_number"]: list(r.get("problems") or []) for r in outcome.rows(casting_log)
            if r.get("problems")}


def ideas_checked(casting_log: list[dict], checkpoint: int) -> dict[str, list[int]]:
    """The oracle ideas this checkpoint's tests cited, with the tests."""
    ideas: dict[str, list[int]] = {}
    for e in casting_log:
        if e.get("checkpoint") == checkpoint and e.get("oracle_claim_id") and not e.get("skipped"):
            ideas.setdefault(e["oracle_claim_id"], []).append(e["test_number"])
    return ideas


def idea_answers(checkpoints: list[dict]) -> dict[str, str]:
    """Each idea's latest answer in the run's hypotheses: held, broke or cannot_tell."""
    answers: dict[str, str] = {}
    for cp in checkpoints:
        for a in (cp.get("hypothesis") or {}).get("ideas") or []:
            if isinstance(a, dict) and a.get("id") and a.get("verdict") in VERDICTS:
                answers[a["id"]] = a["verdict"]
    return answers


def accounted(checkpoints: list[dict], test_problems: dict[int, list[str]]) -> set[str]:
    """The problems earlier checkpoints answered: shown by a test an observation cites,
    or dismissed."""
    done: set[str] = set()
    for cp in checkpoints:
        hypothesis = cp.get("hypothesis") or {}
        for o in hypothesis.get("observations", []):
            for n in o.get("tests", []):
                done.update(test_problems.get(n, []))
        done.update(d.get("error", "") for d in hypothesis.get("dismissed_errors", []))
    return done


def open_errors(test_problems: dict[int, list[str]], done: set[str]) -> dict[str, list[int]]:
    """Each problem not answered yet, with the tests that showed it."""
    open_: dict[str, list[int]] = {}
    for n, problems in sorted(test_problems.items()):
        for p in problems:
            if p not in done:
                open_.setdefault(p, []).append(n)
    return open_


def errors(hypothesis: dict, *, ideas_to_answer=(), errors_to_account=None, test_problems=None) -> list[str]:
    """What the hypothesis still owes: an answer per idea checked, an answer per open
    error, and no "normal" behaviour on a test with an error."""
    found = []
    answered = []
    for i, a in enumerate(hypothesis.get("ideas") or []):
        where = f"ideas[{i}]"
        if not isinstance(a, dict):
            found.append(f"{where} must be an object")
            continue
        if a.get("id") not in ideas_to_answer:
            found.append(f"{where}.id is '{a.get('id')}', which isn't an idea this checkpoint's tests checked "
                         f"(they checked: {', '.join(ideas_to_answer) or 'none'})")
        if a.get("verdict") not in VERDICTS:
            found.append(f"{where}.verdict must be one of {', '.join(VERDICTS)}")
        if not isinstance(a.get("tests"), list) or not all(isinstance(t, int) for t in a["tests"]):
            found.append(f"{where}.tests must be a list of test numbers")
        answered.append(a.get("id"))
    missing = [i for i in ideas_to_answer if i not in answered]
    if missing:
        found.append(f"'ideas' doesn't answer {', '.join(missing)}: say for each idea your tests checked whether "
                     "it held, broke, or you couldn't tell")
    test_problems = test_problems or {}
    covered = {p for o in hypothesis.get("observations") or [] if isinstance(o, dict)
               for n in o.get("tests") or [] for p in test_problems.get(n, [])}
    for i, d in enumerate(hypothesis.get("dismissed_errors") or []):
        if not isinstance(d, dict) or not str(d.get("reason", "")).strip():
            found.append(f"dismissed_errors[{i}] needs the error, as listed, and a reason")
        else:
            covered.add(d.get("error"))
    owed = [p for p in (errors_to_account or {}) if p not in covered]
    if owed:
        listed = "; ".join(f"{p} (tests {', '.join(map(str, errors_to_account[p]))})" for p in owed[:_SHOWN])
        found.append(f"{len(owed)} recorded error(s) have no answer. Each needs an observation that cites a test "
                     f"showing it, or a line in dismissed_errors saying why it isn't a problem: {listed}"
                     + (" ..." if len(owed) > _SHOWN else ""))
    for i, b in enumerate(hypothesis.get("behaviors") or []):
        bad = [(n, p) for n in (b.get("tests") or []) if isinstance(b, dict) for p in test_problems.get(n, [])]
        if bad:
            n, p = bad[0]
            found.append(f"behaviors[{i}] cites test {n}, which recorded \"{p}\": a test with an error isn't "
                         "normal behaviour. Make it an observation, or cite other tests")
    return found


def rests_on_reproduced_error(observation: dict, test_problems: dict[int, list[str]]) -> bool:
    """Whether an observation rests on a trusted problem that more than one of its tests
    recorded: then it is a bug, whatever caused it (#312)."""
    seen: dict[str, int] = {}
    for n in observation.get("tests") or []:
        for p in set(test_problems.get(n, [])):
            seen[p] = seen.get(p, 0) + 1
    return any(count >= 2 for count in seen.values())
