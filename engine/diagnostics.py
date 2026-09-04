"""Domain-free detectors over the outcome envelopes in a casting log.

What these are for
------------------
The Driver reasons about the SUT. Nobody was reasoning about *the run* - whether
the tests it executed were the independent batch the casting prompt promised, and
whether the actions it spent budget on were capable of doing anything. A live run
against a game client made that gap concrete: after the fifth test the client was
behind a modal dialog, three of five actions were physically inert, the return-to-
baseline action was one of them, and the run cheerfully spent eight more tests and
two more checkpoints on it. Every fact needed to notice was already in the log.

So: pure arithmetic over `engine/outcome.py` envelopes. No LLM call, no I/O, no
adapter import, and nothing here knows what a modal, an HTTP status or a rate
limiter is. Each detector is a claim about the *shape* of the log:

- `degenerate_state`  - most of the actions tried from one state did nothing
- `batch_not_independent` - one checkpoint's tests started from different states
- `reset_failing`     - the SUT could not be returned to its baseline
- `prior_yield`       - how often the adapter's supplied prior actually matched
- `inputs_rejected`   - a run of inputs the SUT refused outright

Different SUTs trip different ones, which is the point: a detector that only ever
fires for one adapter is that adapter's feature wearing a generic costume.

Thresholds, and why they are not round numbers
----------------------------------------------
Every threshold here exists to separate a real degeneracy from a SUT behaving
normally, and each is argued at its use site rather than tuned to make a
particular run look interesting. The one worth reading is `degenerate_state`'s: a
count alone would fire on a healthy screen where two controls are *supposed* to do
nothing, and a fraction alone would fire on a state visited once. It needs both.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine import outcome as oc

# A state must have been probed with at least this many distinct actions before
# "most of them did nothing" means anything. At two, a single deliberate no-op
# alongside one dead control reads as a collapsed action space.
MIN_ACTIONS_PROBED = 3

# ...and at least this fraction of them must have done nothing. Chosen above a
# half so that a state where the actions split evenly - which is what an ordinary
# screen with some inert controls looks like - does not qualify.
INERT_FRACTION = 0.6

# Consecutive failed resets before the run is considered unable to return to its
# baseline. One failure can be a slow transition; two in a row means the escape
# route itself is broken, and every test after that point starts somewhere nobody
# chose. Deliberately small: the cost of continuing is a contaminated run.
RESET_FAILURES_TO_STOP = 2

# Consecutive refused inputs before that is worth reporting as a state rather than
# as an event. A single rejection is usually the answer to the question the test
# asked; three in a row means the SUT has stopped accepting input.
REJECTION_RUN = 3

# How many observations must have been compared against a prior before its yield is
# worth a verdict. Below this, "it never matched" is a small-sample statement.
MIN_PRIOR_SAMPLES = 5


@dataclass(frozen=True)
class Finding:
    """One thing true about the run rather than about the SUT.

    `severity` is `info` (worth reporting), `warn` (the run's own results are
    qualified by this) or `stop` (continuing produces data nobody can interpret).
    """
    code: str
    severity: str
    headline: str
    detail: str
    tests: tuple[int, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "severity": self.severity, "headline": self.headline,
            "detail": self.detail, "tests": list(self.tests),
        }


def _numbers(rows: list[dict]) -> tuple[int, ...]:
    return tuple(r["test_number"] for r in rows if r.get("test_number") is not None)


def degenerate_state(rows: list[dict]) -> list[Finding]:
    """States where most of the distinct actions tried produced no observable effect.

    Grouped by `state_before`, so this is a claim about a *place* in the SUT rather
    than about an action: the same tap that does nothing here may work perfectly one
    screen over, and that asymmetry is the whole signal. Rows whose effect is
    `unknown` are excluded from both sides of the fraction - counting an unmeasurable
    result as "did nothing" would let a blind adapter report a broken SUT.
    """
    by_state: dict[str, list[dict]] = {}
    for row in rows:
        state = row.get("state_before") or ""
        if not state or row.get("effect") == oc.UNKNOWN:
            continue
        by_state.setdefault(state, []).append(row)

    findings = []
    for state, group in sorted(by_state.items()):
        tried = {r.get("action_id") for r in group if r.get("action_id")}
        inert = {r.get("action_id") for r in group
                 if r.get("action_id") and r.get("effect") == oc.NONE}
        if len(tried) < MIN_ACTIONS_PROBED or not inert:
            continue
        if len(inert) / len(tried) < INERT_FRACTION:
            continue
        worked = sorted(tried - inert)
        inert_rows = [r for r in group if r.get("action_id") in inert]
        findings.append(Finding(
            code="degenerate_state",
            severity="warn",
            headline=(f"{len(inert)} of {len(tried)} actions tried from state "
                      f"{state!r} did nothing at all"),
            detail=(
                f"From {state!r}, these produced no observable change: "
                f"{', '.join(sorted(inert))}. "
                + (f"Only {', '.join(worked)} had any effect there. "
                   if worked else "Nothing tried there had any effect. ")
                + "Budget spent on the inert actions bought no information. Before "
                  "concluding these controls are broken, consider that the SUT may "
                  "not have been accepting input in this state at all - a single "
                  "cause that looks identical to several independently dead controls."
            ),
            tests=_numbers(inert_rows),
        ))
    return findings


def batch_not_independent(rows: list[dict]) -> list[Finding]:
    """Checkpoints whose tests did not all start from the same state.

    The casting prompt tells the Driver every test in a batch is an independent
    check and that order within the batch does not matter. That promise is only kept
    if each test starts where the others did. When it is broken the Driver is
    comparing results that are not comparable, and it has no way to know - so this
    says so rather than leaving it to be inferred from a prose recovery note.
    """
    by_checkpoint: dict[int, list[dict]] = {}
    for row in rows:
        if not row.get("state_before"):
            continue
        by_checkpoint.setdefault(row.get("checkpoint"), []).append(row)

    findings = []
    for checkpoint, group in sorted(by_checkpoint.items(), key=lambda kv: (kv[0] is None, kv[0])):
        starts = {r["state_before"] for r in group}
        if len(starts) < 2:
            continue
        findings.append(Finding(
            code="batch_not_independent",
            severity="warn",
            headline=(f"checkpoint {checkpoint}'s {len(group)} tests started from "
                      f"{len(starts)} different states"),
            detail=(
                f"Start states seen: {', '.join(sorted(starts))}. The batch was cast as a "
                f"set of independent checks, so any comparison between these tests is "
                f"confounded by where each one happened to begin. Results from the batch "
                f"support claims about individual transitions, not about which action is "
                f"more effective than another."
            ),
            tests=_numbers(group),
        ))
    return findings


def reset_failing(rows: list[dict]) -> list[Finding]:
    """Attempts to return the SUT to its baseline that did not work.

    Reported with the longest consecutive run, because that is the number that
    decides whether the run is recoverable: isolated failures mean some tests were
    contaminated, while a run of them means the escape route is broken and every
    later test starts somewhere nobody chose.

    "Consecutive" counts consecutive ATTEMPTS, not consecutive tests, so a test that
    did not try to reset does not break the run. That is deliberate and it is the
    conservative reading: a failed reset leaves the SUT off its baseline, and a later
    test that never tried to return did nothing to fix it. Requiring the failures to
    be adjacent in test order would let a broken escape route hide behind whichever
    tests happened not to need one.
    """
    attempted = [r for r in rows if r.get("reset_attempted") and r.get("reset_ok") is not None]
    failed = [r for r in attempted if r.get("reset_ok") is False]
    if not failed:
        return []

    longest, current = 0, 0
    for row in attempted:
        current = current + 1 if row.get("reset_ok") is False else 0
        longest = max(longest, current)

    stopping = longest >= RESET_FAILURES_TO_STOP
    return [Finding(
        code="reset_failing",
        severity="stop" if stopping else "warn",
        headline=(f"{len(failed)} of {len(attempted)} attempts to return to baseline failed"
                  + (f" ({longest} in a row)" if longest > 1 else "")),
        detail=(
            f"The SUT could not be put back into the state each test is supposed to start "
            f"from. "
            + (f"With {longest} consecutive failures the run is no longer sampling the SUT "
               f"from a known state, so further tests cost budget and produce results that "
               f"cannot be attributed to the action that was sent. "
               if stopping else
               f"Tests immediately after a failure did not start where they were cast to. ")
            + "Whatever the SUT was left in is not somewhere the run chose to be."
        ),
        tests=_numbers(failed),
    )]


def prior_yield(rows: list[dict]) -> list[Finding]:
    """How often the adapter's supplied prior actually matched an observation.

    A prior that never matches is not neutral. It means every affordance built on it
    - a carried classification, a documented field, an expected status - contributed
    nothing to this run, including any safety check that depended on recognising
    something. That is a fact about the run's instruments and belongs in its report,
    because a report that omits it reads exactly like a report from a run whose
    instruments worked.
    """
    compared = [r for r in rows if r.get("matched_prior") is not None]
    if len(compared) < MIN_PRIOR_SAMPLES:
        return []
    matched = [r for r in compared if r.get("matched_prior")]
    fraction = len(matched) / len(compared)
    if fraction > 0:
        return [Finding(
            code="prior_yield",
            severity="info",
            headline=f"the supplied prior matched {len(matched)} of {len(compared)} observations",
            detail=(f"{fraction:.0%} of observations were recognised from the prior the adapter "
                    f"was given. The rest were new ground."),
            tests=(),
        )]
    return [Finding(
        code="prior_yield",
        severity="warn",
        headline=f"the supplied prior matched NONE of {len(compared)} observations",
        detail=(
            "Every observation this run was somewhere the prior does not describe, so the "
            "prior contributed nothing - including anything built on top of it, such as "
            "recognising a state the run was supposed to avoid. Either the SUT has changed "
            "since the prior was recorded, or the run never reached the part of it the prior "
            "covers. Findings that lean on state identity are qualified by this."
        ),
        tests=(),
    )]


def inputs_rejected(rows: list[dict]) -> list[Finding]:
    """Runs of inputs the SUT refused to accept at all.

    Distinct from `degenerate_state`: there, an input was accepted and changed
    nothing; here it was not accepted. Only adapters that can actually tell the
    difference report `accepted`, so this stays silent rather than guessing for the
    ones that cannot.
    """
    answered = [r for r in rows if r.get("accepted") is not None]
    if not answered:
        return []
    refused = [r for r in answered if r.get("accepted") is False]
    if not refused:
        return []

    longest, current, run_rows, best_rows = 0, 0, [], []
    for row in answered:
        if row.get("accepted") is False:
            current += 1
            run_rows.append(row)
        else:
            current, run_rows = 0, []
        if current > longest:
            longest, best_rows = current, list(run_rows)

    if longest < REJECTION_RUN:
        return [Finding(
            code="inputs_rejected",
            severity="info",
            headline=f"{len(refused)} of {len(answered)} inputs were refused outright",
            detail=("Refusals were scattered rather than consecutive, so they look like "
                    "answers to the individual tests rather than a SUT that stopped "
                    "accepting input."),
            tests=_numbers(refused),
        )]
    return [Finding(
        code="inputs_rejected",
        severity="warn",
        headline=f"{longest} consecutive inputs were refused outright",
        detail=(
            f"{len(refused)} of {len(answered)} inputs were not accepted, {longest} of them in "
            f"an unbroken run. A run of refusals is a property of the SUT's state rather than "
            f"of the individual inputs, so tests inside it were not testing what they were cast "
            f"to test - they were all measuring the same refusal."
        ),
        tests=_numbers(best_rows),
    )]


_DETECTORS = (
    degenerate_state,
    batch_not_independent,
    reset_failing,
    prior_yield,
    inputs_rejected,
)

_SEVERITY_ORDER = {"stop": 0, "warn": 1, "info": 2}


def diagnose(casting_log: list[dict]) -> list[Finding]:
    """Every finding across the whole log, most serious first.

    Returns the "no envelope" finding rather than an empty list when the adapter
    supplies no outcome data, because "nothing was detected" and "nothing could be
    detected" are the two readings a run report must never blur.
    """
    rows = oc.rows(casting_log)
    if not rows:
        if not casting_log:
            return []
        return [Finding(
            code="diagnostics_unavailable",
            severity="info",
            headline="this adapter supplies no outcome envelopes, so no run diagnostics ran",
            detail=("None of the executed tests carried an engine/outcome.py envelope. The "
                    "checks for a collapsed action space, a non-independent batch, a failing "
                    "reset and an unmatched prior were not performed - they did not come back "
                    "clean."),
            tests=(),
        )]

    findings: list[Finding] = []
    for detector in _DETECTORS:
        findings.extend(detector(rows))
    return sorted(findings, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.code))


def should_stop(findings: list[Finding]) -> Finding | None:
    """The first finding, if any, that makes further testing uninterpretable."""
    for finding in findings:
        if finding.severity == "stop":
            return finding
    return None


def as_dicts(findings: list[Finding]) -> list[dict]:
    """The findings as plain data, for storing in a run's output and report."""
    return [f.as_dict() for f in findings]


# What the model is told `run_diagnostics` means. It travels WITH the payload
# rather than living in a system prompt, because there are three adapters and a
# bootstrap template, each of which writes its own casting prompt: a sentence added
# to all four is a sentence that the fifth adapter, written next month, will not
# have. Self-describing evidence needs no prompt to be added anywhere.
PREAMBLE = (
    "Facts about THIS RUN's own mechanics, computed arithmetically by the engine from what "
    "the executed tests actually did - not inferred by a model, and not a claim about the "
    "SUT being buggy. Their use is that they can invalidate your reasoning: if a state's "
    "actions were nearly all inert, a single cause (the SUT was not accepting input there) "
    "is a better explanation than several independently broken controls, and if the baseline "
    "reset failed, tests after that point did not start where they were cast to. Treat a "
    "finding as a constraint on which hypotheses are still available, and say so when one "
    "changes what you propose or conclude."
)


def for_model(findings: list[Finding]) -> dict | None:
    """The findings plus their own explanation, or None when there is nothing to say."""
    if not findings:
        return None
    return {"what_this_is": PREAMBLE, "findings": as_dicts(findings)}


def console_lines(findings: list[Finding]) -> list[str]:
    marks = {"stop": "STOP", "warn": "WARN", "info": "info"}
    lines = []
    for finding in findings:
        where = f" (tests {', '.join(str(t) for t in finding.tests)})" if finding.tests else ""
        lines.append(f"  [{marks.get(finding.severity, '?')}] {finding.headline}{where}")
    return lines
