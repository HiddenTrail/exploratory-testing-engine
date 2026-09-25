"""HYPOTHESIS_TOOL, SKEPTIC_TOOL, BUG_REPORT_TOOL: the domain-agnostic core of
the checkpoint loop. These are NOT adapter-overridable: their wording never
references domain nouns (card numbers, credit counts, etc.) - only "test
numbers," "observations," "rival explanations" - so there is no present need
to let a per-SUT adapter drift them.

The Driver's hypothesis is structured (issue #41): short fields with word
limits, test numbers as evidence, and ids the engine assigns after each call
(`C<checkpoint>.O<n>` for observations, `C<checkpoint>.G<n>` for the Skeptic's
gaps), so a later checkpoint can refer to an earlier item by id instead of
quoting it back. The SKEPTIC_TOOL and BUG_REPORT_TOOL below were ported from
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
    checkpoint's hypothesis can answer it by id. A plain-string gap becomes
    {'id', 'gap'}."""
    stamped = []
    for n, gap in enumerate(skeptic_review["gaps"], start=1):
        gap = dict(gap) if isinstance(gap, dict) else {"gap": gap}
        gap["id"] = f"C{checkpoint_num}.G{n}"
        stamped.append(gap)
    skeptic_review["gaps"] = stamped


SKEPTIC_TOOL = {
    "name": "submit_skeptic_review",
    "description": "Cold-review a checkpoint hypothesis - you have NOT seen the underlying test data. Poke holes in it; don't rubber-stamp it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["weak", "strong_enough"],
                "description": "'weak' only for a MATERIAL reason: an overconfident behavior characterization, an anomaly claim that isn't well justified, a suspicious absence of any anomaly claim given what's been tested, an anomaly_checks entry with discriminates_from_rival=false, a previously-raised gap that still hasn't been addressed, or coverage_breadth.material=true. 'strong_enough' whenever none of those apply - routine, low-stakes untested corners in 'gaps' do NOT by themselves require 'weak'; there's always something more you could test in open-ended exploration, and naming it is not the same as having a material objection. But a coverage-breadth problem IS material: concluding 'no anomaly found' or a general behavior characterization from a small slice of the interface, while whole documented behaviors or paths remain completely untouched, is not adequately supported no matter how clean that small slice looks.",
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "At least 2 concrete gaps, untested areas, or weak assumptions - things that, if tested, might change the picture. These are for the next checkpoint's planning; listing them does not by itself imply 'weak'.",
                "minItems": 2,
            },
            "coverage_breadth": {
                "type": "object",
                "description": (
                    "Look at gaps/untested as a SET, not one at a time: roughly how many genuinely "
                    "distinct, documented behaviors or paths - not just parameter variations within a path "
                    "that's already been tested - have zero test coverage so far? Testing a handful of "
                    "easy, narrow checks and concluding the system is fine is not the same as testing "
                    "broadly across the documented surface and finding nothing - don't let the former "
                    "stand in for the latter."
                ),
                "properties": {
                    "material": {
                        "type": "boolean",
                        "description": (
                            "True if the untested fraction is large enough, on its own, to make the "
                            "current characterization or a 'no anomaly found' conclusion unsupported - "
                            "independent of how solid the small, already-tested slice looks."
                        ),
                    },
                    "note": {
                        "type": "string",
                        "description": "1-2 sentences: which distinct behaviors/paths have zero coverage, and why that is or isn't material. Specific, not generic.",
                    },
                },
                "required": ["material", "note"],
            },
            "anomaly_checks": {
                "type": "array",
                "description": (
                    "One entry per observation in the hypothesis (whatever its kind), in the same order - empty list if there are none. Set anomaly_ref to the observation's id. "
                    "For each: does the cited evidence actually DISCRIMINATE the claimed mechanism from "
                    "its own stated rival explanation - i.e. would the evidence have come out differently "
                    "if the rival were true instead - or would the exact same observations show up under "
                    "either explanation? Evidence that is merely CONSISTENT with a claim (but equally "
                    "consistent with a real rival) does not actually support that claim, no matter how "
                    "many data points there are. Concretely check: restate the claimed mechanism, restate "
                    "the rival, and ask whether the specific numbers/outcomes cited would differ between "
                    "them. One rival is always available and is the one Drivers most often skip: THE INPUT "
                    "WAS NEVER ACCEPTED. If a claim is that something did nothing, or did the wrong thing, "
                    "check whether the hypothesis established that the input was processed at all - and if "
                    "the claim rests on several inputs each appearing to do nothing, note that one cause "
                    "(nothing was being accepted at that point) explains all of them and is therefore the "
                    "better explanation until a test distinguishes it."
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
                        "anomaly_ref": {
                            "type": "string",
                            "description": "The id of the observation this is about, for example 'C1.O2'.",
                        },
                        "discriminates_from_rival": {
                            "type": "boolean",
                            "description": "False means the cited evidence is merely consistent with the claim, not evidence for it over its own stated rival.",
                        },
                        "rival_is_genuine": {
                            "type": "boolean",
                            "description": "Is the claim's own competing explanation a real, plausible alternative, or a strawman easily dismissed?",
                        },
                        "note": {
                            "type": "string",
                            "description": "1-2 sentences: your own independent alternative explanation, and/or what a genuinely discriminating test would need to show instead.",
                        },
                    },
                    "required": ["anomaly_ref", "discriminates_from_rival", "rival_is_genuine", "note"],
                },
            },
            "recommended_next_tests": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "At least 2 concrete, actionable test ideas the Driver should try next - specific "
                    "enough to run directly (what inputs, what outcome would be informative). Prioritize "
                    "tests that would resolve a discriminates_from_rival=false finding or close a named "
                    "gap over generic 'test more' suggestions."
                ),
                "minItems": 2,
            },
            "prior_critique_addressed": {
                "type": "string",
                "description": (
                    "Only meaningful if 'your_own_prior_review' is present in the evidence you were given "
                    "(your own critique from the previous checkpoint). Check explicitly, using the Driver's "
                    "'prior_gaps' (its own stated status for each gap you named): were the "
                    "gaps/recommended_next_tests you named last time actually acted on with new tests, "
                    "and for anything the Driver instead marked as untestable-with-current-data or "
                    "already-resolved, is that stated reason actually credible - or is it hand-wavy, "
                    "unsupported, or a way to dodge an inconvenient test? A credible untestable/resolved "
                    "claim should NOT count against the hypothesis. An incredible one, or a gap with no "
                    "response at all, is a material reason for 'weak' on its own. If there was no prior "
                    "review, write 'n/a'."
                ),
            },
        },
        "required": ["verdict", "gaps", "coverage_breadth", "anomaly_checks", "recommended_next_tests", "prior_critique_addressed"],
    },
}

SKEPTIC_SYSTEM_PROMPT = """You are cold-reviewing a checkpoint hypothesis - you have NOT seen the raw
test data, only the hypothesis itself (its behavior characterization and any anomaly claims). Your
job is to poke holes, not confirm.

Beyond "is there enough evidence," check whether the evidence is the RIGHT KIND of evidence - this is
a distinct failure mode from insufficient evidence, and it's easy to miss. A claim can cite several
real, correctly-observed data points and still be unsupported, if those same data points would have
looked identical under a rival explanation. Evidence only supports a claim over its rival if it would
have come out DIFFERENTLY had the rival been true instead - evidence that's merely consistent with
(but doesn't rule out) an alternative is not actually evidence for the claim, regardless of volume.

For example: if a claim is "capacity resets per-transaction, not cumulatively" and the cited evidence
is "a large purchase was declined, then smaller purchases after it were approved" - check whether that
observation would look any different under the rival "capacity is cumulative, and the smaller purchases
simply fit within whatever headroom remained." If the numbers involved (the decline amount, the prior
spend, the smaller amounts) are consistent with the cumulative story too, the cited evidence does not
actually discriminate between the two, and the claim is unsupported regardless of how confidently it's
stated. This is exactly what each anomaly_checks entry's discriminates_from_rival exists to catch -
work through it explicitly rather than treating "some evidence exists" as sufficient.

There is one rival that is available against almost any anomaly claim and is the one most often left
unaddressed: THE INPUT WAS NEVER ACCEPTED. Whenever a claim says something did nothing, or produced
the wrong result, check whether the hypothesis established that the input was processed at all rather
than ignored, refused, or arriving while the system was still busy. Apply this hardest when a claim
rests on SEVERAL inputs each appearing to do nothing: "each of these is individually broken" and
"nothing was being accepted at that point" predict the same observations, and the second is a single
cause rather than several coincidences, so a hypothesis that has not ruled it out has not earned the
first. That is a discriminates_from_rival=false finding even if the hypothesis named some other rival
and dealt with it properly.

Do not conflate "I can name an untested corner" with "I have a material objection." Exploratory testing
always has more you could try - that's what 'gaps' and 'recommended_next_tests' are for, feeding the
next checkpoint's planning - but naming them is not itself a reason for "weak". Reserve "weak" for a
genuine, specific reason to doubt the current hypothesis or a named anomaly claim: a discriminates_from_rival=false
finding, an overconfident characterization the evidence doesn't support, a suspicious absence of any
anomaly claim given what's actually been tested, a coverage-breadth problem (see below), or (see further
below) a previously-raised objection that was never addressed. If the strongest thing you can say is
"there's always more to test," that is consistent with "strong_enough", not evidence against it.

But do not confuse "a few narrow untested corners" with "most of the documented interface has never
been exercised" - these look similar in isolation but are not the same thing, and only the second is
material on its own. Look at gaps/untested as a SET: if they name genuinely distinct documented
behaviors or paths - not just parameter variations within a path that's already been tested - and that
set covers a large fraction of what the interface actually offers, a "no anomaly found, everything
looks clean" conclusion is not adequately supported, no matter how solid the small tested slice is. For
example: five tests that each cleanly confirm one narrow, easy error path (wrong credential, invalid
quantity, wrong secret) plus one single data point about pricing is not "a well-tested system with a
couple of loose ends" - it's a small, easy fraction of the interface with almost everything else,
including the paths most likely to hide a real bug, never touched even once. Say this explicitly in
coverage_breadth and let it drive the verdict; don't let "the tested claims all held up" quietly
stand in for "the interface has actually been tested."

If the evidence you're given includes 'your_own_prior_review' (your own critique from the checkpoint
before this one), check continuity: did the new hypothesis actually respond to what you flagged last
time, or does it just repeat the same kind of evidence in a different direction while ignoring your
critique? The Driver's 'prior_gaps' gives its own stated status for each gap you named - don't
just take it at face value. If it claims something is untestable with the current scenario data or
already conclusively resolved, judge whether that specific stated reason actually holds up (e.g. "no
known account has two cards" is a real, checkable reason; "didn't get to it" or a vague gesture is not).
A credible claim closes that gap fairly - don't keep penalizing something that genuinely cannot be
tested further. An incredible claim, or silence on a gap you named, is itself a material reason for
"weak", independent of anything else.

Give a verdict: "weak" only for one of the material reasons above, or "strong_enough" if none apply.
Identify at least 2 concrete gaps, fill in coverage_breadth honestly, and give at least 2 concrete
recommended_next_tests specific enough to run directly. For EACH observation in the hypothesis, add one entry to
anomaly_checks with your own independent alternative explanation and whether that claim's own competing
explanation is genuine or a strawman - you propose what's worth investigating further, the Driver
decides what to actually test. If there are no observations, leave anomaly_checks empty. Remember this
implementation may genuinely have no bugs - don't manufacture doubt just to have something to say, but
don't rubber-stamp a thin absence-of-anomalies claim either, and don't rubber-stamp a thin slice of the
interface as if it were the whole thing.

Call submit_skeptic_review with your answer."""


def validate_skeptic_response(data, *, expected_anomaly_count=None) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    required = ("verdict", "gaps", "coverage_breadth", "anomaly_checks", "recommended_next_tests", "prior_critique_addressed")
    for key in required:
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if data.get("verdict") not in ("weak", "strong_enough"):
        errors.append("'verdict' must be 'weak' or 'strong_enough'")
    gaps = data.get("gaps")
    if not isinstance(gaps, list) or len(gaps) < 2 or not all(isinstance(g, str) for g in gaps):
        errors.append("'gaps' must be a list of at least 2 strings")

    coverage_breadth = data.get("coverage_breadth")
    if not isinstance(coverage_breadth, dict) or not isinstance(coverage_breadth.get("material"), bool) or not isinstance(coverage_breadth.get("note"), str):
        errors.append("'coverage_breadth' must be an object with a boolean 'material' and a string 'note'")

    anomaly_checks = data.get("anomaly_checks")
    if not isinstance(anomaly_checks, list):
        errors.append("'anomaly_checks' must be a list (empty if no anomalies were claimed)")
    else:
        for i, check in enumerate(anomaly_checks):
            if not isinstance(check, dict):
                errors.append(f"anomaly_checks[{i}] must be an object")
                continue
            for field in ("anomaly_ref", "note"):
                if not isinstance(check.get(field), str):
                    errors.append(f"anomaly_checks[{i}].{field} must be a string")
            for field in ("discriminates_from_rival", "rival_is_genuine"):
                if not isinstance(check.get(field), bool):
                    errors.append(f"anomaly_checks[{i}].{field} must be a boolean")
        if expected_anomaly_count is not None and len(anomaly_checks) != expected_anomaly_count:
            errors.append(
                f"'anomaly_checks' must have exactly one entry per observation "
                f"({expected_anomaly_count} observations, got {len(anomaly_checks)})"
            )

    next_tests = data.get("recommended_next_tests")
    if not isinstance(next_tests, list) or len(next_tests) < 2 or not all(isinstance(t, str) for t in next_tests):
        errors.append("'recommended_next_tests' must be a list of at least 2 strings")
    if not isinstance(data.get("prior_critique_addressed"), str):
        errors.append("'prior_critique_addressed' must be a string")
    return errors


BUG_REPORT_TOOL = {
    "name": "submit_bug_reports",
    "description": "Write the final bug report(s) - deliberately NOT redacted, since this needs real repro steps. One entry per distinct anomaly.",
    "input_schema": {
        "type": "object",
        "properties": {
            "bugs": {
                "type": "array",
                "description": "One entry per distinct anomaly in the final hypothesis.",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "steps_to_reproduce": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "expected_behavior": {"type": "string"},
                        "actual_behavior": {"type": "string"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "status": {
                            "type": "string",
                            "enum": ["corroborated", "inconclusive"],
                            "description": "'corroborated' if Skeptic was satisfied; 'inconclusive' if the checkpoint budget ran out while Skeptic still had objections.",
                        },
                        "caveats": {"type": "string", "description": "Honest caveats about what wasn't resolved or verified."},
                    },
                    "required": ["title", "description", "steps_to_reproduce", "expected_behavior", "actual_behavior", "severity", "status", "caveats"],
                },
            },
        },
        "required": ["bugs"],
    },
}

BUG_REPORT_SYSTEM_PROMPT = """Write the final bug report(s) based on everything in the evidence: the
final checkpoint hypothesis (including its anomaly claims), Skeptic's critique, stopped_reason, and
the full test history. Write ONE entry per distinct anomaly claimed in the final hypothesis. Include
literal, concrete repro steps (real values that actually reproduced the issue, referencing real test
numbers) - each report needs to be independently actionable, not a redacted summary. Be honest in
caveats about anything that wasn't fully resolved - if the checkpoint budget ran out while Skeptic
still had objections (stopped_reason is "checkpoints_exhausted"), say so explicitly rather than
overstating confidence, and set status to "inconclusive" rather than "corroborated".

Call submit_bug_reports with your answer."""


def validate_bug_reports(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    bugs = data.get("bugs")
    if not isinstance(bugs, list) or not bugs:
        errors.append("'bugs' must be a non-empty list")
        return errors
    for i, bug in enumerate(bugs):
        if not isinstance(bug, dict):
            errors.append(f"bugs[{i}] must be an object")
            continue
        for key in ("title", "description", "steps_to_reproduce", "expected_behavior", "actual_behavior", "severity", "status", "caveats"):
            if key not in bug:
                errors.append(f"bugs[{i}] missing '{key}'")
        steps = bug.get("steps_to_reproduce")
        if not isinstance(steps, list) or not steps or not all(isinstance(s, str) for s in steps):
            errors.append(f"bugs[{i}].steps_to_reproduce must be a non-empty list of strings")
        if bug.get("severity") not in ("low", "medium", "high"):
            errors.append(f"bugs[{i}].severity must be low/medium/high")
        if bug.get("status") not in ("corroborated", "inconclusive"):
            errors.append(f"bugs[{i}].status must be 'corroborated' or 'inconclusive'")
    return errors
