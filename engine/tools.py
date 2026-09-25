"""HYPOTHESIS_TOOL, SKEPTIC_TOOL, BUG_REPORT_TOOL: the domain-agnostic core of
the checkpoint loop. These are NOT adapter-overridable: their wording never
references domain nouns (card numbers, credit counts, etc.) - only "test
numbers," "observations," "rival explanations" - so there is no present need
to let a per-SUT adapter drift them.

The Driver's hypothesis is structured (issue #41): short fields with word
limits, test numbers as evidence, and ids the engine assigns after each call
(`C<checkpoint>.O<n>` for observations, `C<checkpoint>.G<n>` for the Skeptic's
gaps), so a later checkpoint can refer to an earlier item by id instead of
quoting it back. The Skeptic's review is structured the same way, and its verdict
has to follow from the objections it raises. BUG_REPORT_TOOL below was ported from
token-purchase-poc's most-evolved version.
"""

OBSERVATION_KINDS = ("finding", "anomaly", "bug")
REPRODUCED = ("consistent", "inconsistent", "once")
SEVERITIES = ("low", "medium", "high")
PRIOR_GAP_STATUSES = ("tested", "untestable", "resolved", "not_attempted")

# Word limits for the short text fields. Each limit is written into the field's
# description. The validator only rejects an answer that runs past twice the
# limit, so a 32-word answer to a 30-word limit doesn't cost a retry, but a
# paragraph where a sentence was asked for does.
WORD_LIMITS = {
    "summary": 30,
    "behavior.claim": 25,
    "observation.claim": 30,
    "observation.violates": 25,
    "observation.mechanism": 25,
    "observation.rival": 25,
    "observation.why": 25,
    "untested.area": 15,
    "prior_gap.reason": 25,
}
MAX_BEHAVIORS = 5
MAX_UNTESTED = 5


def _limit(key: str) -> str:
    return f"At most {WORD_LIMITS[key]} words."


def is_far_too_long(text: str, key: str) -> bool:
    return len(text.split()) > 2 * WORD_LIMITS[key]


_TESTS = {"type": "array", "items": {"type": "integer"}, "description": "The test numbers this rests on."}

HYPOTHESIS_TOOL = {
    "name": "submit_checkpoint_hypothesis",
    "description": "Characterize the system's behavior based on real test results so far, including anything that looks wrong.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": f"One sentence: what you now believe about the system. {_limit('summary')}",
            },
            "behaviors": {
                "type": "array",
                "description": f"Behavior you confirmed as normal. At most {MAX_BEHAVIORS} entries.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": _limit("behavior.claim")},
                        "tests": _TESTS,
                    },
                    "required": ["claim", "tests"],
                },
            },
            "observations": {
                "type": "array",
                "description": (
                    "Everything that looks wrong or worth a closer look, zero or more entries. Leave it "
                    "empty if nothing has turned up - this implementation may have no problems at all. "
                    "Each entry is one specific, falsifiable claim, with a genuine competing explanation "
                    "(not a strawman you'd easily dismiss). For any claim that something did nothing or "
                    "did the wrong thing, the rival 'the input was never accepted at all' is always "
                    "available - rule it out or say why it doesn't apply."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": list(OBSERVATION_KINDS),
                            "description": (
                                "finding: something iffy worth a look, no problem shown yet. "
                                "anomaly: a real problem, but it doesn't clearly contradict a known fact, "
                                "or it doesn't reproduce consistently. "
                                "bug: contradicts a known fact (the spec, the docs, an oracle claim, a value "
                                "the system itself disclosed) or breaks or blocks something, and reproduces "
                                "consistently."
                            ),
                        },
                        "continues": {
                            "type": "string",
                            "description": (
                                "The id of an earlier observation this one refines or repeats, for example "
                                "'C1.O2'. Empty if it's new."
                            ),
                        },
                        "claim": {"type": "string", "description": _limit("observation.claim")},
                        "tests": _TESTS,
                        "violates": {
                            "type": "string",
                            "description": (
                                "Required for a bug: the known fact it contradicts, and where that fact "
                                f"comes from. Empty for a finding or an anomaly. {_limit('observation.violates')}"
                            ),
                        },
                        "reproduced": {
                            "type": "string",
                            "enum": list(REPRODUCED),
                            "description": "How it behaved when repeated. 'once' means it hasn't been repeated yet.",
                        },
                        "mechanism": {"type": "string", "description": f"Your best guess at the cause. {_limit('observation.mechanism')}"},
                        "rival": {"type": "string", "description": f"A genuine competing explanation. {_limit('observation.rival')}"},
                        "rival_ruled_out": {"type": "boolean", "description": "Does your evidence rule the rival out?"},
                        "why": {
                            "type": "string",
                            "description": f"Why the rival is or isn't ruled out, citing tests. {_limit('observation.why')}",
                        },
                        "severity": {"type": "string", "enum": list(SEVERITIES), "description": "How bad it would be if true."},
                    },
                    "required": [
                        "kind", "continues", "claim", "tests", "violates", "reproduced",
                        "mechanism", "rival", "rival_ruled_out", "why", "severity",
                    ],
                },
            },
            "untested": {
                "type": "array",
                "description": f"Things not tried yet that are worth trying next. At most {MAX_UNTESTED} entries.",
                "items": {
                    "type": "object",
                    "properties": {"area": {"type": "string", "description": _limit("untested.area")}},
                    "required": ["area"],
                },
            },
            "prior_gaps": {
                "type": "array",
                "description": (
                    "One entry for EACH gap in 'prior_skeptic_review', if your evidence has one. Empty on "
                    "the first checkpoint."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "gap_id": {"type": "string", "description": "The gap's id, for example 'C1.G2'."},
                        "status": {
                            "type": "string",
                            "enum": list(PRIOR_GAP_STATUSES),
                            "description": (
                                "tested: a test this checkpoint covered it (cite it in tests). untestable: "
                                "the current scenario data can't construct it. resolved: existing evidence "
                                "already settles it. not_attempted: still open."
                            ),
                        },
                        "tests": _TESTS,
                        "reason": {
                            "type": "string",
                            "description": (
                                "Required unless tested. Concrete and checkable (e.g. 'no known account has "
                                f"two cards'), not 'didn't get to it'. {_limit('prior_gap.reason')}"
                            ),
                        },
                    },
                    "required": ["gap_id", "status", "tests", "reason"],
                },
            },
        },
        "required": ["summary", "behaviors", "observations", "untested", "prior_gaps"],
    },
}

HYPOTHESIS_SYSTEM_PROMPT = """You are characterizing this system's behavior based on real test results
from this session so far. Keep every field short: each one has a word limit, and test numbers are the
evidence, not prose.

Say what you now believe in one sentence (summary), list the behavior you confirmed as normal
(behaviors), and list anything that looks wrong or worth a closer look (observations). If nothing has
turned up, leave observations empty rather than forcing a claim - this implementation may have no
problems at all. List what's still untested.

Each observation has a kind:
- finding: something iffy worth a look. No problem shown yet.
- anomaly: a real problem, but it doesn't clearly contradict a known fact, or it doesn't reproduce
  consistently.
- bug: contradicts a known fact (the spec, the docs, an oracle claim, a value the system itself
  disclosed) or breaks or blocks something, and reproduces consistently. Say which fact in 'violates'.
Pick the most cautious kind the evidence supports. A claim seen once can't be a bug yet.

Your evidence may include 'earlier_observations': what earlier checkpoints found, with ids like 'C1.O2'.
If a new observation refines or repeats one of them, put that id in 'continues' instead of starting over.

One rival explanation is always available and is the easiest to skip past: THE INPUT WAS NEVER ACCEPTED.
Before claiming that something did nothing, or did the wrong thing, ask whether it was processed at all -
whether the system was in a state that ignores or refuses input, whether it was still busy with the
previous test, whether what came back is the result of your input or just the unchanged state that was
already there. This matters most when SEVERAL inputs each appear to do nothing: "these controls are
individually broken" and "the system was accepting nothing at that point" predict
the identical observation, and the second is one cause instead of many, so it is the better
explanation until something distinguishes them. A test that could tell them apart is worth more than another test that
reproduces the same silence.

If your evidence includes 'prior_skeptic_review', its gaps have ids like 'C1.G2'. Answer EACH one in
prior_gaps: tested (cite the test), untestable with the current scenario data (say exactly why),
already resolved by existing evidence (say why no further test would change anything), or
not_attempted. Be honest - the Skeptic judges your stated reason, it doesn't take it on faith.

Call submit_checkpoint_hypothesis with your answer."""


def _is_test_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(t, int) and not isinstance(t, bool) for t in value)


def _check_text(errors: list[str], where: str, value, key: str, *, required: bool = True) -> None:
    if not isinstance(value, str):
        errors.append(f"{where} must be a string")
    elif required and not value.strip():
        errors.append(f"{where} must not be empty")
    elif is_far_too_long(value, key):
        errors.append(f"{where} is far too long ({len(value.split())} words, limit {WORD_LIMITS[key]})")


def validate_hypothesis_response(data, *, known_observation_ids=(), open_gap_ids=()) -> list[str]:
    """known_observation_ids: ids a 'continues' may point at (every earlier
    checkpoint's observations). open_gap_ids: the prior Skeptic review's gap ids,
    each of which prior_gaps must answer exactly once."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    for key in HYPOTHESIS_TOOL["input_schema"]["required"]:
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if errors:
        return errors

    _check_text(errors, "'summary'", data["summary"], "summary")

    behaviors = data["behaviors"]
    if not isinstance(behaviors, list):
        errors.append("'behaviors' must be a list")
    else:
        if len(behaviors) > 2 * MAX_BEHAVIORS:
            errors.append(f"'behaviors' has {len(behaviors)} entries, limit {MAX_BEHAVIORS}")
        for i, b in enumerate(behaviors):
            if not isinstance(b, dict):
                errors.append(f"behaviors[{i}] must be an object")
                continue
            _check_text(errors, f"behaviors[{i}].claim", b.get("claim"), "behavior.claim")
            if not _is_test_list(b.get("tests")):
                errors.append(f"behaviors[{i}].tests must be a list of test numbers")

    observations = data["observations"]
    if not isinstance(observations, list):
        errors.append("'observations' must be a list (may be empty)")
    else:
        for i, o in enumerate(observations):
            if not isinstance(o, dict):
                errors.append(f"observations[{i}] must be an object")
                continue
            errors.extend(_observation_errors(i, o, known_observation_ids))

    untested = data["untested"]
    if not isinstance(untested, list):
        errors.append("'untested' must be a list")
    else:
        if len(untested) > 2 * MAX_UNTESTED:
            errors.append(f"'untested' has {len(untested)} entries, limit {MAX_UNTESTED}")
        for i, u in enumerate(untested):
            if not isinstance(u, dict):
                errors.append(f"untested[{i}] must be an object")
                continue
            _check_text(errors, f"untested[{i}].area", u.get("area"), "untested.area")

    prior_gaps = data["prior_gaps"]
    if not isinstance(prior_gaps, list):
        errors.append("'prior_gaps' must be a list (empty on the first checkpoint)")
    else:
        errors.extend(_prior_gaps_errors(prior_gaps, open_gap_ids))
    return errors


def _observation_errors(i: int, o: dict, known_observation_ids) -> list[str]:
    errors = []
    where = f"observations[{i}]"
    kind = o.get("kind")
    if kind not in OBSERVATION_KINDS:
        errors.append(f"{where}.kind must be one of {', '.join(OBSERVATION_KINDS)}")
    continues = o.get("continues")
    if not isinstance(continues, str):
        errors.append(f"{where}.continues must be a string (empty if new)")
    elif continues and continues not in known_observation_ids:
        known = ", ".join(known_observation_ids) or "none yet"
        errors.append(f"{where}.continues is '{continues}', which isn't an earlier observation id (known: {known})")
    _check_text(errors, f"{where}.claim", o.get("claim"), "observation.claim")
    if not _is_test_list(o.get("tests")) or not o.get("tests"):
        errors.append(f"{where}.tests must be a non-empty list of test numbers")
    reproduced = o.get("reproduced")
    if reproduced not in REPRODUCED:
        errors.append(f"{where}.reproduced must be one of {', '.join(REPRODUCED)}")
    _check_text(errors, f"{where}.violates", o.get("violates"), "observation.violates", required=False)
    if kind == "bug":
        if isinstance(o.get("violates"), str) and not o["violates"].strip():
            errors.append(f"{where} is a bug, so 'violates' must say which known fact it contradicts")
        if reproduced in REPRODUCED and reproduced != "consistent":
            errors.append(f"{where} is a bug, but reproduced is '{reproduced}': a bug must reproduce consistently "
                          "(call it an anomaly or a finding instead)")
    for field in ("mechanism", "rival", "why"):
        _check_text(errors, f"{where}.{field}", o.get(field), f"observation.{field}")
    if not isinstance(o.get("rival_ruled_out"), bool):
        errors.append(f"{where}.rival_ruled_out must be a boolean")
    if o.get("severity") not in SEVERITIES:
        errors.append(f"{where}.severity must be one of {', '.join(SEVERITIES)}")
    return errors


def _prior_gaps_errors(prior_gaps: list, open_gap_ids) -> list[str]:
    errors = []
    answered = []
    for i, g in enumerate(prior_gaps):
        where = f"prior_gaps[{i}]"
        if not isinstance(g, dict):
            errors.append(f"{where} must be an object")
            continue
        gap_id = g.get("gap_id")
        if gap_id not in open_gap_ids:
            known = ", ".join(open_gap_ids) or "none, this is the first checkpoint"
            errors.append(f"{where}.gap_id is '{gap_id}', which isn't a gap from the prior review (gaps: {known})")
        answered.append(gap_id)
        status = g.get("status")
        if status not in PRIOR_GAP_STATUSES:
            errors.append(f"{where}.status must be one of {', '.join(PRIOR_GAP_STATUSES)}")
        if not _is_test_list(g.get("tests")):
            errors.append(f"{where}.tests must be a list of test numbers")
        elif status == "tested" and not g["tests"]:
            errors.append(f"{where} says tested, so 'tests' must cite the test numbers")
        _check_text(errors, f"{where}.reason", g.get("reason"), "prior_gap.reason", required=status != "tested")
    missing = [gap_id for gap_id in open_gap_ids if gap_id not in answered]
    if missing:
        errors.append(f"'prior_gaps' doesn't answer {', '.join(missing)}: answer every gap from the prior review")
    duplicated = sorted({gap_id for gap_id in answered if answered.count(gap_id) > 1})
    if duplicated:
        errors.append(f"'prior_gaps' answers {', '.join(duplicated)} more than once")
    return errors


def stamp_observation_ids(checkpoint_num: int, hypothesis: dict) -> None:
    """Gives each observation its id, 'C<checkpoint>.O<n>'. The engine assigns
    ids, not the model, so they are unique and stable across the run."""
    for n, observation in enumerate(hypothesis["observations"], start=1):
        observation["id"] = f"C{checkpoint_num}.O{n}"


def stamp_gap_ids(checkpoint_num: int, skeptic_review: dict) -> None:
    """Gives each of the Skeptic's gaps its id, 'C<checkpoint>.G<n>', so the next
    checkpoint's hypothesis can answer it by id."""
    for n, gap in enumerate(skeptic_review["gaps"], start=1):
        gap["id"] = f"C{checkpoint_num}.G{n}"


SKEPTIC_WORD_LIMITS = {
    "verdict_reason": 30,
    "check.note": 30,
    "coverage.area": 15,
    "coverage.note": 30,
    "gap.gap": 20,
    "gap.next_test": 30,
    "prior_gap_check.note": 20,
}
WORD_LIMITS.update(SKEPTIC_WORD_LIMITS)
MAX_GAPS = 5

# Most cautious first. When the Driver and the Skeptic disagree on an
# observation's kind, the engine keeps the more cautious one.
_KIND_CAUTION = {kind: rank for rank, kind in enumerate(("finding", "anomaly", "bug"))}

SKEPTIC_TOOL = {
    "name": "submit_skeptic_review",
    "description": "Cold-review a checkpoint hypothesis - you have NOT seen the underlying test data. Poke holes in it; don't rubber-stamp it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["weak", "strong_enough"],
                "description": (
                    "'weak' only if you raise at least one objection (see below), and 'strong_enough' only "
                    "if you raise none. Naming an untested corner is not an objection."
                ),
            },
            "verdict_reason": {
                "type": "string",
                "description": f"One sentence: the main objection, or why none applies. {_limit('verdict_reason')}",
            },
            "observation_checks": {
                "type": "array",
                "description": (
                    "Exactly one entry per observation in the hypothesis, by id. Does the cited evidence "
                    "DISCRIMINATE the claim from its own stated rival - would the evidence have come out "
                    "differently if the rival were true - or would the same observations show up under "
                    "either explanation? Evidence that is merely consistent with a claim (and equally "
                    "consistent with a real rival) does not support it, however many data points there are. "
                    "One rival is always available and the one most often skipped: THE INPUT WAS NEVER "
                    "ACCEPTED. If a claim is that something did nothing or did the wrong thing, check the "
                    "hypothesis established that the input was processed at all; if it rests on several "
                    "inputs each appearing to do nothing, one cause (nothing was being accepted) explains "
                    "all of them and is the better explanation until a test distinguishes it."
                    # NOTE: a known, accepted limitation lives here - this check does not
                    # account for realistic value rounding/precision when deciding whether
                    # cited evidence "discriminates" a claim from its rival. Verified case:
                    # a claim that 101 credits costing $1.82 instead of $1.818 proves
                    # "marginal pricing" is actually just ordinary cent-rounding of a flat
                    # rate, but the Skeptic accepted it as discriminating evidence anyway.
                    # Deliberately not fixed here - carried forward as documented, known
                    # scope, not something to patch incidentally while touching this file.
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "observation_id": {"type": "string", "description": "The observation's id, for example 'C1.O2'."},
                        "discriminates_from_rival": {
                            "type": "boolean",
                            "description": "False means the evidence is only consistent with the claim, not evidence for it over its rival.",
                        },
                        "rival_is_genuine": {
                            "type": "boolean",
                            "description": "Is the claim's rival a real, plausible alternative, or a strawman easily dismissed?",
                        },
                        "kind": {
                            "type": "string",
                            "enum": list(OBSERVATION_KINDS),
                            "description": (
                                "Your own view of the kind: finding (iffy, no problem shown), anomaly (a real "
                                "problem that doesn't clearly contradict a known fact or doesn't reproduce "
                                "consistently), bug (contradicts a known fact or breaks something, and "
                                "reproduces consistently). If you disagree with the Driver, the more cautious "
                                "kind is kept."
                            ),
                        },
                        "note": {
                            "type": "string",
                            "description": (
                                "Your own alternative explanation, or what a genuinely discriminating test "
                                f"would have to show. {_limit('check.note')}"
                            ),
                        },
                    },
                    "required": ["observation_id", "discriminates_from_rival", "rival_is_genuine", "kind", "note"],
                },
            },
            "coverage": {
                "type": "object",
                "description": (
                    "Look at the untested areas and your gaps as a SET: how many distinct, documented "
                    "behaviors or paths - not parameter variations within a path already tested - have no "
                    "test at all?"
                ),
                "properties": {
                    "material": {
                        "type": "boolean",
                        "description": (
                            "True if the untested part is large enough, on its own, to make the current "
                            "characterization or a 'nothing wrong' conclusion unsupported."
                        ),
                    },
                    "untouched": {
                        "type": "array",
                        "description": "The distinct behaviors or paths with no test yet.",
                        "items": {"type": "string", "description": _limit("coverage.area")},
                    },
                    "note": {"type": "string", "description": f"Why that is or isn't material. {_limit('coverage.note')}"},
                },
                "required": ["material", "untouched", "note"],
            },
            "gaps": {
                "type": "array",
                "description": (
                    f"Up to {MAX_GAPS} gaps or weak assumptions, each with the test that would close it. These "
                    "feed the next checkpoint's planning. Only mark blocks_verdict for a gap that is a material "
                    "reason for 'weak'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "gap": {"type": "string", "description": _limit("gap.gap")},
                        "next_test": {
                            "type": "string",
                            "description": f"A concrete test: what inputs, what outcome would be informative. {_limit('gap.next_test')}",
                        },
                        "blocks_verdict": {"type": "boolean", "description": "Is this gap a reason for 'weak'?"},
                        "about": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ids of the observations this gap is about. Empty if it's about coverage in general.",
                        },
                    },
                    "required": ["gap", "next_test", "blocks_verdict", "about"],
                },
            },
            "prior_gaps_check": {
                "type": "array",
                "description": (
                    "Only if your evidence includes 'your_own_prior_review': one entry per gap you named last "
                    "time, by id. Empty on the first checkpoint."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "gap_id": {"type": "string", "description": "The gap's id, for example 'C1.G2'."},
                        "accepted": {
                            "type": "boolean",
                            "description": (
                                "Is the Driver's answer for this gap credible? A real test, or a concrete and "
                                "checkable reason it can't be tested or is already resolved: true. No answer, or "
                                "a vague reason: false."
                            ),
                        },
                        "note": {"type": "string", "description": _limit("prior_gap_check.note")},
                    },
                    "required": ["gap_id", "accepted", "note"],
                },
            },
        },
        "required": ["verdict", "verdict_reason", "observation_checks", "coverage", "gaps", "prior_gaps_check"],
    },
}

SKEPTIC_SYSTEM_PROMPT = """You are cold-reviewing a checkpoint hypothesis. You have NOT seen the raw test
data, only the hypothesis: its summary, the behavior it confirmed, its observations (each a finding, an
anomaly or a bug, with an id) and what's still untested. Your job is to poke holes, not confirm. Keep
every field short: each one has a word limit.

Beyond "is there enough evidence," check whether it is the RIGHT KIND of evidence. A claim can cite
several real, correctly-observed data points and still be unsupported, if those same data points would
have looked identical under its rival. Evidence only supports a claim over its rival if it would have come
out DIFFERENTLY had the rival been true.

For example: if a claim is "capacity resets per-transaction, not cumulatively" and the evidence is "a
large purchase was declined, then smaller purchases after it were approved", check whether that would
look any different under the rival "capacity is cumulative, and the smaller purchases simply fit within
whatever headroom remained." If the numbers involved are consistent with the cumulative story too, the
evidence does not discriminate, and the claim is unsupported however confidently it's stated. That is what
each observation check's discriminates_from_rival is for.

One rival is available against almost any claim and is the one most often left unaddressed: THE INPUT WAS
NEVER ACCEPTED. Whenever a claim says something did nothing, or produced the wrong result, check whether
the hypothesis established that the input was processed at all rather than ignored, refused, or arriving
while the system was still busy. Apply this hardest when a claim rests on SEVERAL inputs each appearing to
do nothing: "each of these is individually broken" and "nothing was being accepted at that point" predict
the same observations, and the second is one cause rather than several coincidences. That is a
discriminates_from_rival=false finding even if the hypothesis dealt properly with some other rival.

Check each observation's kind too. A bug must contradict a known fact (it names which in 'violates') and
reproduce consistently. If you'd call it something more cautious, say so in 'kind'; the engine keeps the
more cautious of the two.

Your verdict follows from your objections. There are four kinds of objection:
- an observation check with discriminates_from_rival=false
- coverage.material=true: most of the documented interface has never been exercised, so a characterization
  or a "nothing wrong" conclusion isn't supported, however clean the small tested slice looks
- a gap with blocks_verdict=true: a specific, material reason to doubt the hypothesis or an observation
- a prior gap with accepted=false
Say "weak" only if you raise at least one of these, and "strong_enough" only if you raise none. Do not
conflate "I can name an untested corner" with "I have an objection": exploratory testing always has more
to try, and that's what gaps are for, without blocks_verdict. But don't confuse a few narrow corners with
most of the interface never being touched: five tests that each confirm one easy error path is a small
slice, not a well-tested system with loose ends.

If your evidence includes 'your_own_prior_review', check continuity. For each gap you named last time, the
hypothesis's 'prior_gaps' gives the Driver's answer. Judge whether it holds up: a real test, or a concrete,
checkable reason ("no known account has two cards") is credible; "didn't get to it" or silence is not. A
credible answer closes the gap fairly - don't keep penalizing what genuinely can't be tested further.

This implementation may genuinely have no bugs. Don't manufacture doubt to have something to say, but don't
rubber-stamp a thin absence of problems, or a thin slice of the interface as if it were the whole thing.

Call submit_skeptic_review with your answer."""


def validate_skeptic_response(data, *, observations=(), open_gap_ids=()) -> list[str]:
    """observations: this checkpoint's observations (with ids), each of which needs
    exactly one check. open_gap_ids: the gaps from the Skeptic's own prior review,
    each of which prior_gaps_check must answer exactly once."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    for key in SKEPTIC_TOOL["input_schema"]["required"]:
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if errors:
        return errors

    if data["verdict"] not in ("weak", "strong_enough"):
        errors.append("'verdict' must be 'weak' or 'strong_enough'")
    _check_text(errors, "'verdict_reason'", data["verdict_reason"], "verdict_reason")

    observation_ids = [o["id"] for o in observations]
    objections = 0

    checks = data["observation_checks"]
    if not isinstance(checks, list):
        errors.append("'observation_checks' must be a list")
        checks = []
    checked = []
    for i, check in enumerate(checks):
        where = f"observation_checks[{i}]"
        if not isinstance(check, dict):
            errors.append(f"{where} must be an object")
            continue
        observation_id = check.get("observation_id")
        if observation_id not in observation_ids:
            known = ", ".join(observation_ids) or "none, this hypothesis has no observations"
            errors.append(f"{where}.observation_id is '{observation_id}', which isn't in the hypothesis (ids: {known})")
        checked.append(observation_id)
        for field in ("discriminates_from_rival", "rival_is_genuine"):
            if not isinstance(check.get(field), bool):
                errors.append(f"{where}.{field} must be a boolean")
        if check.get("kind") not in OBSERVATION_KINDS:
            errors.append(f"{where}.kind must be one of {', '.join(OBSERVATION_KINDS)}")
        _check_text(errors, f"{where}.note", check.get("note"), "check.note")
        if check.get("discriminates_from_rival") is False:
            objections += 1
    errors.extend(_once_each("observation_checks", "observation", checked, observation_ids))

    coverage = data["coverage"]
    if not isinstance(coverage, dict):
        errors.append("'coverage' must be an object")
    else:
        if not isinstance(coverage.get("material"), bool):
            errors.append("coverage.material must be a boolean")
        untouched = coverage.get("untouched")
        if not isinstance(untouched, list):
            errors.append("coverage.untouched must be a list")
        else:
            for i, area in enumerate(untouched):
                _check_text(errors, f"coverage.untouched[{i}]", area, "coverage.area")
        _check_text(errors, "coverage.note", coverage.get("note"), "coverage.note")
        if coverage.get("material") is True:
            objections += 1

    gaps = data["gaps"]
    if not isinstance(gaps, list):
        errors.append("'gaps' must be a list")
        gaps = []
    if len(gaps) > 2 * MAX_GAPS:
        errors.append(f"'gaps' has {len(gaps)} entries, limit {MAX_GAPS}")
    for i, gap in enumerate(gaps):
        where = f"gaps[{i}]"
        if not isinstance(gap, dict):
            errors.append(f"{where} must be an object")
            continue
        _check_text(errors, f"{where}.gap", gap.get("gap"), "gap.gap")
        _check_text(errors, f"{where}.next_test", gap.get("next_test"), "gap.next_test")
        if not isinstance(gap.get("blocks_verdict"), bool):
            errors.append(f"{where}.blocks_verdict must be a boolean")
        about = gap.get("about")
        if not isinstance(about, list) or not all(isinstance(a, str) for a in about):
            errors.append(f"{where}.about must be a list of observation ids")
        else:
            unknown = [a for a in about if a not in observation_ids]
            if unknown:
                errors.append(f"{where}.about names {', '.join(unknown)}, which isn't in the hypothesis")
        if gap.get("blocks_verdict") is True:
            objections += 1

    prior_checks = data["prior_gaps_check"]
    if not isinstance(prior_checks, list):
        errors.append("'prior_gaps_check' must be a list (empty on the first checkpoint)")
        prior_checks = []
    answered = []
    for i, check in enumerate(prior_checks):
        where = f"prior_gaps_check[{i}]"
        if not isinstance(check, dict):
            errors.append(f"{where} must be an object")
            continue
        gap_id = check.get("gap_id")
        if gap_id not in open_gap_ids:
            known = ", ".join(open_gap_ids) or "none, this is the first checkpoint"
            errors.append(f"{where}.gap_id is '{gap_id}', which isn't a gap from your prior review (gaps: {known})")
        answered.append(gap_id)
        if not isinstance(check.get("accepted"), bool):
            errors.append(f"{where}.accepted must be a boolean")
        _check_text(errors, f"{where}.note", check.get("note"), "prior_gap_check.note")
        if check.get("accepted") is False:
            objections += 1
    errors.extend(_once_each("prior_gaps_check", "gap from your prior review", answered, open_gap_ids))

    # "Weak needs reasoning": the verdict has to follow from the objections raised.
    if data["verdict"] == "weak" and objections == 0:
        errors.append(
            "verdict is 'weak' but no objection was raised: mark the observation check, coverage, gap "
            "(blocks_verdict) or prior gap that makes it weak, or say 'strong_enough'"
        )
    if data["verdict"] == "strong_enough" and objections > 0:
        errors.append(
            f"verdict is 'strong_enough' but {objections} objection(s) were raised: either drop them or say 'weak'"
        )
    return errors


def _once_each(field: str, what: str, given: list, expected) -> list[str]:
    errors = []
    missing = [x for x in expected if x not in given]
    if missing:
        errors.append(f"'{field}' has no entry for {', '.join(missing)}: give one per {what}")
    duplicated = sorted({x for x in given if x is not None and given.count(x) > 1})
    if duplicated:
        errors.append(f"'{field}' has more than one entry for {', '.join(duplicated)}")
    return errors


def reconcile_kinds(hypothesis: dict, skeptic_review: dict) -> None:
    """Where the Skeptic's view of an observation's kind is more cautious than the
    Driver's, keep the Skeptic's, and record the Driver's as 'driver_kind'. The
    Skeptic can't upgrade a kind, only lower it: a bug needs both to agree."""
    skeptic_kinds = {c["observation_id"]: c["kind"] for c in skeptic_review["observation_checks"]}
    for observation in hypothesis["observations"]:
        skeptic_kind = skeptic_kinds.get(observation["id"])
        if skeptic_kind and _KIND_CAUTION[skeptic_kind] < _KIND_CAUTION[observation["kind"]]:
            observation["driver_kind"] = observation["kind"]
            observation["kind"] = skeptic_kind


BUG_REPORT_WORD_LIMITS = {
    "bug.title": 15,
    "bug.description": 60,
    "bug.step": 30,
    "bug.expected": 30,
    "bug.actual": 30,
    "bug.caveats": 50,
}
WORD_LIMITS.update(BUG_REPORT_WORD_LIMITS)
MAX_STEPS = 8

BUG_REPORT_TOOL = {
    "name": "submit_bug_reports",
    "description": (
        "Write the final bug reports - deliberately NOT redacted, since they need real repro steps. "
        "One entry per bug in the evidence, by id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bugs": {
                "type": "array",
                "description": "Exactly one entry per bug in the evidence.",
                "items": {
                    "type": "object",
                    "properties": {
                        "observation_id": {"type": "string", "description": "The bug's id, for example 'C2.O1'."},
                        "title": {"type": "string", "description": _limit("bug.title")},
                        "description": {"type": "string", "description": _limit("bug.description")},
                        "steps_to_reproduce": {
                            "type": "array",
                            "description": f"Literal steps with the real values that reproduced it. At most {MAX_STEPS} steps.",
                            "items": {"type": "string", "description": _limit("bug.step")},
                        },
                        "expected_behavior": {"type": "string", "description": _limit("bug.expected")},
                        "actual_behavior": {"type": "string", "description": _limit("bug.actual")},
                        "caveats": {
                            "type": "string",
                            "description": f"What wasn't resolved or verified, stated honestly. {_limit('bug.caveats')}",
                        },
                    },
                    "required": [
                        "observation_id", "title", "description", "steps_to_reproduce",
                        "expected_behavior", "actual_behavior", "caveats",
                    ],
                },
            },
        },
        "required": ["bugs"],
    },
}

BUG_REPORT_SYSTEM_PROMPT = """Write one bug report for each bug in the evidence, by its id. Each bug comes
with its observation (claim, tests, the fact it violates, mechanism, rival), its status, and the Skeptic's
last check of it. The full test history is there for the real values.

Include literal, concrete repro steps: the real values that actually reproduced the issue, referencing
real test numbers. Each report must be independently actionable, not a redacted summary. Keep every field
short: each one has a word limit.

The engine has already decided each bug's status and severity, so don't argue with them. Be honest in
caveats about anything that wasn't resolved. If a bug's status is 'inconclusive', say why, from the
Skeptic's check and any gap that blocks it.

Call submit_bug_reports with your answer."""


def validate_bug_reports(data, *, bug_ids=()) -> list[str]:
    """bug_ids: the ids of the bugs that each need exactly one report."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    bugs = data.get("bugs")
    if not isinstance(bugs, list):
        return ["'bugs' must be a list"]
    errors = []
    reported = []
    for i, bug in enumerate(bugs):
        where = f"bugs[{i}]"
        if not isinstance(bug, dict):
            errors.append(f"{where} must be an object")
            continue
        observation_id = bug.get("observation_id")
        if observation_id not in bug_ids:
            errors.append(f"{where}.observation_id is '{observation_id}', which isn't a bug in the evidence "
                          f"(bugs: {', '.join(bug_ids)})")
        reported.append(observation_id)
        for field, key in (("title", "bug.title"), ("description", "bug.description"),
                           ("expected_behavior", "bug.expected"), ("actual_behavior", "bug.actual"),
                           ("caveats", "bug.caveats")):
            _check_text(errors, f"{where}.{field}", bug.get(field), key)
        steps = bug.get("steps_to_reproduce")
        if not isinstance(steps, list) or not steps:
            errors.append(f"{where}.steps_to_reproduce must be a non-empty list of steps")
        else:
            if len(steps) > 2 * MAX_STEPS:
                errors.append(f"{where}.steps_to_reproduce has {len(steps)} steps, limit {MAX_STEPS}")
            for n, step in enumerate(steps):
                _check_text(errors, f"{where}.steps_to_reproduce[{n}]", step, "bug.step")
    errors.extend(_once_each("bugs", "bug", reported, bug_ids))
    return errors


def final_observations(hypothesis: dict, skeptic_review: dict) -> list[dict]:
    """The run's conclusion: every observation of the final checkpoint with its
    status, decided by the engine rather than by a model. An observation is
    'corroborated' when the Skeptic's last check says its evidence discriminates
    it from its rival and no blocking gap is about it; otherwise 'inconclusive'."""
    checks = {c["observation_id"]: c for c in skeptic_review["observation_checks"]}
    blocked = {oid for gap in skeptic_review["gaps"] if gap["blocks_verdict"] for oid in gap["about"]}
    concluded = []
    for observation in hypothesis["observations"]:
        check = checks.get(observation["id"], {})
        corroborated = check.get("discriminates_from_rival") is True and observation["id"] not in blocked
        concluded.append({
            **observation,
            "status": "corroborated" if corroborated else "inconclusive",
            "skeptic_note": check.get("note", ""),
        })
    return concluded


# --- The casting round (issue #96) ---------------------------------------
# Casting schemas are per adapter, but three things are the same for all of them
# and live here so they can't drift apart: what the Driver is told about the
# previous checkpoint's feedback, the length of the round's reasoning, and the
# checks on the answer's envelope (give_up, reasoning, candidate_tests).

CASTING_REASONING_WORDS = 60
CASTING_REASONING_DESCRIPTION = (
    f"What this round tests and why, at most {CASTING_REASONING_WORDS} words. Name the observation "
    "and gap ids it targets."
)

PRIOR_FEEDBACK_GUIDE = """prior_checkpoint_feedback holds the previous checkpoint's hypothesis and the
Skeptic's cold review of it, both structured. The hypothesis has observations (each a finding, an anomaly
or a bug, with an id like 'C1.O2'). The review has observation_checks (whether each observation's evidence
discriminates it from its rival), gaps (each with an id like 'C1.G3', a next_test and blocks_verdict) and a
verdict_reason. Plan this round from that: first the next_test of every gap with blocks_verdict=true, then
tests that could confirm OR refute an observation whose check says it doesn't discriminate. Turn those into
literal tests, not unrelated new exploration. The next hypothesis has to answer every gap by id, so a test
aimed at a gap is worth more than one that isn't."""


def casting_envelope_errors(data) -> tuple[list[str], object]:
    """The checks every adapter's casting validator starts with. give_up may be
    left out when the answer has tests: that already says the Driver didn't give
    up, and a missing give_up was the most common casting retry after #41 (4 of
    12 calls). Returns the errors and the candidate_tests value for the adapter's
    own per-test checks."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"], None
    errors = []
    tests = data.get("candidate_tests")
    if "candidate_tests" not in data:
        errors.append("missing required field 'candidate_tests'")
    elif not isinstance(tests, list):
        errors.append("'candidate_tests' must be a list")

    give_up = data.get("give_up")
    if "give_up" not in data:
        if not tests:
            errors.append("missing required field 'give_up' (it can only be left out when there are tests)")
    elif not isinstance(give_up, bool):
        errors.append("'give_up' must be a boolean")
    if isinstance(tests, list) and not tests and give_up is not True:
        errors.append("'candidate_tests' must be non-empty unless give_up is true")

    reasoning = data.get("reasoning")
    if "reasoning" not in data:
        errors.append("missing required field 'reasoning'")
    elif not isinstance(reasoning, str):
        errors.append("'reasoning' must be a string")
    elif len(reasoning.split()) > 2 * CASTING_REASONING_WORDS:
        errors.append(f"'reasoning' is far too long ({len(reasoning.split())} words, limit {CASTING_REASONING_WORDS})")
    return errors, tests
