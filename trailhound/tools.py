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

import re

from trailhound import ledger

OBSERVATION_KINDS = ("finding", "anomaly", "bug")
REPRODUCED = ("consistent", "inconsistent", "once")
# The kind of question a Skeptic gap asks about the testing (issue #258). The Skeptic
# stays the critic: it questions what the Driver claims and how it tested, and never
# suggests where to look. A fixed list, so the kinds can be counted across runs and
# the next run's Driver told which ones keep coming up.
OBJECTION_KINDS = {
    "overclaimed": "the claim is stronger than the tests behind it",
    "coverage_overstated": "something is called covered or confirmed that the tests don't show",
    "method_in_doubt": "a test may not have done what was meant: it didn't reach its state, the input "
                       "wasn't accepted, tests weren't independent, or the result came from the test tool",
    "rival_not_tested": "no test tells the claim from its rival explanation",
    "not_reproduced": "it was seen once, or not repeated the same way",
    "not_worth_continuing": "this line gives no new evidence; more of the same won't change anything",
    "other": "none of these",
}
SEVERITIES = ("low", "medium", "high")
# The Driver's testing story (#265, #271), after Michael Bolton's three strands (the
# product's status, how it was tested, how good that testing was) and James Bach's
# low-tech testing dashboard. Coverage levels have meanings, so a claim of coverage can
# be checked, and they are assessments grounded in tests, never counts. Quality is in
# safety language: what has been seen so far, not what is true for always.
COVERAGE_LEVELS = {
    "can_it_work": "it can work at all: the basic path",
    "common_and_critical": "the common and the critical cases",
    "deep": "if there were a bad bug here, we would probably know about it",
}
QUALITY_SEEN = {
    "no_problems_seen_yet": "no problems seen so far, and no definite suspicions",
    "concerns": "something looks wrong, not confirmed",
    "problems_found": "a problem was found and shown",
}
CONFIDENCE = ("high", "medium", "low")
# What an area's coverage is of: coverage only means something against a model (Bolton).
# A fixed list since #285, because free text came back as prose about method.
COVERAGE_DIMENSIONS = ("inputs", "states", "sequences", "timing", "data", "users")
# Who could remove an obstacle (#285): "what would help" mixed the engine up with the product.
HELP_FROM = ("engine", "map", "test_data", "product")
MAX_AREAS = 5
MAX_OBSTACLES = 3
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
    "area.area": 10,
    "area.approach": 15,
    "area.coverage_of": 12,
    "area.oracle": 15,
    "area.not_tested": 20,
    "area.why": 30,
    "obstacle.obstacle": 20,
    "obstacle.would_help": 15,
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
                "description": ("One sentence: what the tests found and what they covered. Not a verdict on "
                                f"the product or a whole area. {_limit('summary')}"),
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
                                "The id of an observation from 'earlier_observations' that this one refines "
                                "or repeats, for example 'C1.O2'. Empty if it's new, and always empty on the "
                                "first checkpoint. Never an observation in this same answer: those get their "
                                "ids only after you submit."
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
            "ideas": {
                "type": "array",
                "description": (
                    "One entry for each idea in 'ideas_to_answer', if your evidence has it: the oracle's ideas "
                    "this checkpoint's tests checked. Empty otherwise."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The idea's id, as in 'ideas_to_answer'."},
                        "verdict": {"type": "string", "enum": ["held", "broke", "cannot_tell"],
                                    "description": "held: the product did what the idea expects. broke: it didn't. "
                                                   "cannot_tell: the tests couldn't show it either way."},
                        "tests": _TESTS,
                    },
                    "required": ["id", "verdict", "tests"],
                },
            },
            "dismissed_errors": {
                "type": "array",
                "description": (
                    "For an error in 'errors_to_account_for' that isn't a problem: the error exactly as listed, "
                    "and why. Every other one there needs an observation citing a test that shows it."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "reason": {"type": "string", "description": _limit("prior_gap.reason")},
                    },
                    "required": ["error", "reason"],
                },
            },
        },
        "required": ["summary", "behaviors", "observations", "untested", "prior_gaps"],
    },
}

TESTING_STORY_TOOL = {
    "name": "submit_testing_story",
    "description": "Tell the testing story behind the hypothesis you just formed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "areas": {
                "type": "array",
                "description": (
                    "Your testing story, one entry per part of the system you tested (at most "
                    f"{MAX_AREAS}): where you were, how you tested it and how you'd recognize a problem, "
                    "how much you covered and of what, what you didn't, what you've seen of its quality "
                    "and how sure you are. Assessments grounded in the tests, never counts: the Skeptic "
                    "will check them against the tests. An honest 'can_it_work' with a clear "
                    "'not_tested' beats a 'deep' you can't show."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "description": f"The part of the system. {_limit('area.area')}"},
                        "approach": {
                            "type": "string",
                            "description": f"How you tested it: the layer and the technique. {_limit('area.approach')}",
                        },
                        "coverage": {
                            "type": "string",
                            "enum": list(COVERAGE_LEVELS),
                            "description": "How deep your testing of this area went: " + "; ".join(
                                f"{k}: {v}" for k, v in COVERAGE_LEVELS.items()) + ".",
                        },
                        "coverage_of": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(COVERAGE_DIMENSIONS)},
                            "description": ("What that coverage is of, one or more: the inputs tried, the states "
                                            "it was in, the sequences of actions, timing, the data, the kinds of "
                                            "user. Coverage only means something against a model."),
                        },
                        "oracle": {
                            "type": "string",
                            "description": f"How you'd recognize a problem here. {_limit('area.oracle')}",
                        },
                        "not_tested": {
                            "type": "string",
                            "description": f"What's left untested in this area, or empty. {_limit('area.not_tested')}",
                        },
                        "tests": _TESTS,
                        "quality": {
                            "type": "string",
                            "enum": list(QUALITY_SEEN),
                            "description": "What you've seen of this area's quality, so far: " + "; ".join(
                                f"{k}: {v}" for k, v in QUALITY_SEEN.items()) + ".",
                        },
                        "confidence": {"type": "string", "enum": list(CONFIDENCE),
                                       "description": "How sure you are of that estimate."},
                        "why": {
                            "type": "string",
                            "description": f"Why you estimate coverage and quality so, citing tests. {_limit('area.why')}",
                        },
                    },
                    "required": ["area", "approach", "coverage", "coverage_of", "oracle", "not_tested", "tests",
                                 "quality", "confidence", "why"],
                },
            },
            "obstacles": {
                "type": "array",
                "description": (
                    f"How good your testing could be, at most {MAX_OBSTACLES}: what made it harder, slower or "
                    "impossible (the system's testability, the tools, missing data or access), and what would "
                    "help. Empty if nothing got in the way."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "obstacle": {"type": "string", "description": _limit("obstacle.obstacle")},
                        "would_help": {"type": "string", "description": _limit("obstacle.would_help")},
                        "help_from": {
                            "type": "string", "enum": list(HELP_FROM),
                            "description": ("Who could remove it: the engine (what the test tool can do), the map "
                                            "(which screens and controls tests can reach), test_data (accounts, "
                                            "records), or the product itself (its testability)."),
                        },
                    },
                    "required": ["obstacle", "would_help", "help_from"],
                },
            },
        },
        "required": ["areas", "obstacles"],
    },
}

TESTING_STORY_SYSTEM_PROMPT = """You just formed this checkpoint's hypothesis about the system (it's in
your evidence). An area is a part of the product a user would recognize (a page, a feature, a flow), not a
control you clicked or an overlay that got in the way: if 'product_areas' is in your evidence, name each area
after one of them. Unrelated parts are separate areas, even if you tested them the same way. If 'parked' is
in your evidence, list each parked claim as an obstacle: a question the tests couldn't settle. Now tell the testing story behind it, the way a tester reports to a test lead: three strands,
braided together. What you've seen of each area so far. How you tested it, how you'd recognize a problem,
how deep that went and what it was of, and what you didn't test. And how good your testing could be: what
got in the way. These are assessments, not counts, and each rests on the tests you cite: the Skeptic will
check them against those tests. Say what you have seen, not what is true for always: "no problems seen yet"
is a claim about your testing. Keep every field short: each one has a word limit."""


def validate_testing_story(data) -> list[str]:
    """The testing story (#265, #271), asked for in its own call: in the hypothesis call,
    the bigger answer broke too often (fields lost, or written in another tool format)."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = [f"missing required field '{key}'" for key in TESTING_STORY_TOOL["input_schema"]["required"]
              if key not in data]
    if errors:
        return errors
    areas = data["areas"]
    if not isinstance(areas, list) or not areas:
        errors.append("'areas' must be a non-empty list: your testing story, one entry per area you tested")
    else:
        if len(areas) > 2 * MAX_AREAS:
            errors.append(f"'areas' has {len(areas)} entries, limit {MAX_AREAS}")
        for i, a in enumerate(areas):
            if not isinstance(a, dict):
                errors.append(f"areas[{i}] must be an object")
                continue
            where = f"areas[{i}]"
            _check_text(errors, f"{where}.area", a.get("area"), "area.area")
            _check_text(errors, f"{where}.approach", a.get("approach"), "area.approach")
            dims = a.get("coverage_of")
            if not isinstance(dims, list) or not dims or any(d not in COVERAGE_DIMENSIONS for d in dims):
                errors.append(f"{where}.coverage_of must list one or more of {', '.join(COVERAGE_DIMENSIONS)}")
            _check_text(errors, f"{where}.oracle", a.get("oracle"), "area.oracle")
            _check_text(errors, f"{where}.not_tested", a.get("not_tested"), "area.not_tested", required=False)
            _check_text(errors, f"{where}.why", a.get("why"), "area.why")
            for field, allowed in (("coverage", tuple(COVERAGE_LEVELS)), ("quality", tuple(QUALITY_SEEN)),
                                   ("confidence", CONFIDENCE)):
                if a.get(field) not in allowed:
                    errors.append(f"{where}.{field} must be one of {', '.join(allowed)}")
            if not _is_test_list(a.get("tests")) or not a.get("tests"):
                errors.append(f"{where}.tests must cite the test numbers behind it; an area with no tests "
                              "belongs in 'untested'")

    obstacles = data["obstacles"]
    if not isinstance(obstacles, list):
        errors.append("'obstacles' must be a list (empty if nothing got in the way)")
    else:
        if len(obstacles) > 2 * MAX_OBSTACLES:
            errors.append(f"'obstacles' has {len(obstacles)} entries, limit {MAX_OBSTACLES}")
        for i, o in enumerate(obstacles):
            if not isinstance(o, dict):
                errors.append(f"obstacles[{i}] must be an object")
                continue
            _check_text(errors, f"obstacles[{i}].obstacle", o.get("obstacle"), "obstacle.obstacle")
            _check_text(errors, f"obstacles[{i}].would_help", o.get("would_help"), "obstacle.would_help", required=False)
            if o.get("help_from") not in HELP_FROM:
                errors.append(f"obstacles[{i}].help_from must be one of {', '.join(HELP_FROM)}")

    return errors


HYPOTHESIS_SYSTEM_PROMPT = """You are characterizing this system's behavior based on real test results
from this session so far. Keep every field short: each one has a word limit, and test numbers are the
evidence, not prose.

Say in one sentence what the tests found and what they covered (summary), list the behavior you
confirmed as normal (behaviors), and list anything that looks wrong or worth a closer look
(observations). The summary is never a verdict on the product or a whole area ("works as expected",
"behaves normally", "no bugs found"): a checkpoint's tests can't show that, so name what they did show. If nothing has
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
'continues' only ever takes an id from 'earlier_observations', so it is always empty on the first
checkpoint. The observations in this answer don't have ids yet. Fill in every field of the answer,
including observations, untested and prior_gaps, even when some are empty lists.

One rival explanation is always available and is the easiest to skip past: THE INPUT WAS NEVER ACCEPTED.
Before claiming that something did nothing, or did the wrong thing, ask whether it was processed at all -
whether the system was in a state that ignores or refuses input, whether it was still busy with the
previous test, whether what came back is the result of your input or just the unchanged state that was
already there. This matters most when SEVERAL inputs each appear to do nothing: "these controls are
individually broken" and "the system was accepting nothing at that point" predict
the identical observation, and the second is one cause instead of many, so it is the better
explanation until something distinguishes them. A test that could tell them apart is worth more than another test that
reproduces the same silence.

If your evidence includes 'ideas_to_answer', those are the oracle's ideas your tests checked this
checkpoint. Answer each one in 'ideas': held, broke, or cannot_tell, citing the tests.

If your evidence includes 'errors_to_account_for', those are errors your tests recorded that passed every
trust check: an error in the console, or a request on the product's own site that failed. Every one needs
an answer: an observation that cites a test showing it, or a line in 'dismissed_errors' saying why it isn't
a problem. A test that recorded one isn't normal behaviour. An error like this that reproduces is a bug,
whatever caused it: quote it in the claim, and name what it violates (the product's own requests should
succeed in ordinary use; a page shouldn't throw while you use it).

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


# A summary that judges the whole product (#341). In 25 of 28 checkpoints where the Skeptic
# objected to coverage with no claim to point at, the summary read like "Juice Shop behaves
# largely as expected ... no obvious new bugs found", after 10 to 20 tests. Only these
# phrases: "Checkout works from a reliable state" names what a test showed, and is fine.
# Accepted limit: a phrase can also fit a narrow finding ("the total updates as expected"),
# and an overclaim can be worded around them. That costs one retry or one miss, never a
# run: the call asks about it once and never on the last try (nudge_fn).
_PRODUCT_VERDICT = re.compile(
    r"\bas (?:expected|intended)\b"
    r"|\b(?:behaves|behaving|behave)\s+(?:\w+\s+)?(?:normally|correctly|fine|properly|sensibly)\b"
    r"|\b(?:works?|working|functions?)\s+(?:\w+\s+)?(?:normally|correctly|fine|properly|mechanically)\b"
    r"|\beverything\s+works\b|\ball\s+good\b|\bfine\s+overall\b"
    r"|\bnothing\s+(?:\w+\s+)?(?:wrong|unexpected|broken)\b"
    r"|\bno\s+(?:\w+\s+){0,2}(?:bugs?|issues|problems|defects|regressions)\b",
    re.IGNORECASE)


def summary_verdict_errors(data) -> list[str]:
    """A summary that gives a verdict on the product or a whole area (#341). The hypothesis
    call asks it as a nudge_fn: once, and never on the last try, so wording never costs
    more than one retry or stops a run."""
    summary = data.get("summary") if isinstance(data, dict) else None
    found = _PRODUCT_VERDICT.search(summary) if isinstance(summary, str) else None
    if not found:
        return []
    return [f"'summary' gives a verdict on the product (\"{found.group(0)}\"): this checkpoint's tests can't show "
            "that. Say what they found and which areas they covered instead; this is asked once."]


def validate_hypothesis_response(data, *, known_observation_ids=(), open_gap_ids=(), lean=False,
                                 ideas_to_answer=(), errors_to_account=None, test_problems=None) -> list[str]:
    """known_observation_ids: ids a 'continues' may point at (every earlier
    checkpoint's observations). open_gap_ids: the prior Skeptic review's gap ids,
    each of which prior_gaps must answer exactly once. lean: a lean run (#295), which
    doesn't ask for the fields in trailhound/lean.py's HYPOTHESIS_DROPS."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    lean_skips = {"behaviors", "untested"} if lean else set()
    for key in HYPOTHESIS_TOOL["input_schema"]["required"]:
        if key not in data and key not in lean_skips:
            errors.append(f"missing required field '{key}'")
    if errors:
        return errors

    _check_text(errors, "'summary'", data["summary"], "summary")

    behaviors = data.get("behaviors", [])
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
            errors.extend(_observation_errors(i, o, known_observation_ids, lean=lean))

    untested = data.get("untested", [])
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
        errors.extend(_prior_gaps_errors(prior_gaps, open_gap_ids, lean=lean))
    # Every idea checked and every error recorded gets an answer (#312).
    errors.extend(ledger.errors(data, ideas_to_answer=ideas_to_answer, errors_to_account=errors_to_account,
                                test_problems=test_problems))
    return errors


def _observation_errors(i: int, o: dict, known_observation_ids, *, lean=False) -> list[str]:
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
    # A bug without a violated fact, or not reproduced consistently, isn't rejected
    # here: lower_unsupported_bugs turns it into an anomaly without a retry.
    for field in ("rival",) if lean else ("mechanism", "rival", "why"):
        _check_text(errors, f"{where}.{field}", o.get(field), f"observation.{field}")
    if not isinstance(o.get("rival_ruled_out"), bool):
        errors.append(f"{where}.rival_ruled_out must be a boolean")
    if o.get("severity") not in SEVERITIES:
        errors.append(f"{where}.severity must be one of {', '.join(SEVERITIES)}")
    return errors


def _prior_gaps_errors(prior_gaps: list, open_gap_ids, *, lean=False) -> list[str]:
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
        if not lean:
            _check_text(errors, f"{where}.reason", g.get("reason"), "prior_gap.reason", required=status != "tested")
    missing = [gap_id for gap_id in open_gap_ids if gap_id not in answered]
    if missing:
        errors.append(f"'prior_gaps' doesn't answer {', '.join(missing)}: answer every gap from the prior review")
    duplicated = sorted({gap_id for gap_id in answered if answered.count(gap_id) > 1})
    if duplicated:
        errors.append(f"'prior_gaps' answers {', '.join(duplicated)} more than once")
    return errors


def lower_unsupported_bugs(hypothesis: dict) -> None:
    """A bug has to name the known fact it violates and reproduce consistently.
    One that doesn't is, by those same rules, an anomaly, so the engine lowers it
    instead of rejecting the whole answer and paying for a retry (issue #99). The
    Driver's kind is kept as 'driver_kind' and the reason as 'lowered_because'."""
    for observation in hypothesis["observations"]:
        if observation["kind"] != "bug":
            continue
        reasons = []
        if not observation["violates"].strip():
            reasons.append("it names no violated fact")
        if observation["reproduced"] != "consistent":
            reasons.append(f"it reproduced '{observation['reproduced']}', not consistently")
        if reasons:
            observation["driver_kind"] = "bug"
            observation["kind"] = "anomaly"
            observation["lowered_because"] = " and ".join(reasons)


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
                    "test at all? 'test_coverage' in your evidence is the engine's record of what the tests "
                    "actually sent. Go by it, not by the hypothesis's wording."
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
                        "description": (
                            "The distinct behaviors or paths with no test yet. Never list something "
                            "'test_coverage' shows was sent."
                        ),
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
                    "reason for 'weak'. A gap is a question about the testing (see 'kind'), not a list of what "
                    "nobody has tried yet: an untested area is a gap only if the Driver called it covered or it "
                    "bears on one of its claims."
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
                        "kind": {
                            "type": "string",
                            "enum": list(OBJECTION_KINDS),
                            "description": "What kind of objection this is: " + "; ".join(
                                f"{k}: {v}" for k, v in OBJECTION_KINDS.items()) + ".",
                        },
                        "about": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ids of the observations this gap is about. Empty if it's about coverage in general.",
                        },
                    },
                    "required": ["gap", "next_test", "blocks_verdict", "kind", "about"],
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
anomaly or a bug, with an id) and what's still untested. You also get 'test_coverage', which the engine
works out from the test log: for each input field, the values the tests sent so far, and for a field with
fixed choices, the ones never tried. It lists inputs, not results. Your job is to poke holes, not confirm.
Keep every field short: each one has a word limit.

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

The hypothesis also tells its testing story: 'areas', the Driver's account of each part it tested (how, how
it would recognize a problem, how deep its coverage went and of what, what it didn't test, what it has seen
of the quality and how sure it is), and 'obstacles', what made the testing harder or impossible. Debrief it
the way a test lead debriefs a tester. Ask "how do you know?" of every claim: proof of how it was tested, not
just of the outcome.
- Coverage levels have meanings. "deep" claims that a bad bug there would probably have been found; check that
  against the cited tests and test_coverage. Coverage is only ever of something: inputs say nothing about
  sequences, timing, data or different users. When the tests don't back the level, that's
  "coverage_overstated".
- A quality call or a confidence more sure than the testing behind it is "overclaimed". "no_problems_seen_yet"
  is a claim too.
- An approach or an oracle that couldn't have shown the problem it claims to have looked for is
  "method_in_doubt".
- Distrust a clean story: every area fine and nothing in the way is less believable than a realistic mix.
- If 'previous_story' is in your evidence, compare: an area whose coverage and evidence didn't move since the
  last checkpoint, though it was worked on, is a line that gives no new evidence ("not_worth_continuing").

Check each observation's kind too. A bug must contradict a known fact (it names which in 'violates') and
reproduce consistently. If you'd call it something more cautious, say so in 'kind'; the engine keeps the
more cautious of the two. Except: a bug that rests on a recorded error (a console error, a failed request
on the product's own site) that more than one test showed stays a bug, because the error happened
whatever caused it. Question its cause or its impact instead, and ask for the test that would show the
impact (for example: reload and check whether the data was really saved).

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


def validate_skeptic_response(data, *, observations=(), open_gap_ids=(), lean=False) -> list[str]:
    """observations: this checkpoint's observations (with ids), each of which needs
    exactly one check. open_gap_ids: the gaps from the Skeptic's own prior review,
    each of which prior_gaps_check must answer exactly once. lean: a lean run (#295),
    which doesn't ask for the notes or the untouched list (trailhound/lean.py's SKEPTIC_DROPS)."""
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
        if not lean:
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
        if not lean:
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
        if gap.get("kind") not in OBJECTION_KINDS:
            errors.append(f"{where}.kind must be one of {', '.join(OBJECTION_KINDS)}")
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
        if not lean:
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


def reconcile_kinds(hypothesis: dict, skeptic_review: dict, test_problems: dict | None = None) -> None:
    """Where the Skeptic's view of an observation's kind is more cautious than the
    Driver's, keep the Skeptic's, and record the Driver's as 'driver_kind'. The
    Skeptic can't upgrade a kind, only lower it: a bug needs both to agree.

    Except a bug that rests on a trusted error more than one of its tests recorded
    (#312): the error is in the recording whatever caused it, so a rival explanation
    can't make it less of a bug. The Skeptic questions its cause and impact instead."""
    skeptic_kinds = {c["observation_id"]: c["kind"] for c in skeptic_review["observation_checks"]}
    for observation in hypothesis["observations"]:
        skeptic_kind = skeptic_kinds.get(observation["id"])
        if (observation["kind"] == "bug" and test_problems
                and ledger.rests_on_reproduced_error(observation, test_problems)):
            if skeptic_kind and skeptic_kind != "bug":
                observation["kept_as_bug_because"] = "it rests on a trusted error that more than one test recorded"
            continue
        if skeptic_kind and _KIND_CAUTION[skeptic_kind] < _KIND_CAUTION[observation["kind"]]:
            observation.setdefault("driver_kind", observation["kind"])
            observation["kind"] = skeptic_kind
            observation["lowered_because"] = "the Skeptic judged it more cautiously"



# --- The checkpoint debrief (issue #266) ----------------------------------
# After the Skeptic's first review, the Driver answers each of its questions (its gaps)
# with argument and evidence, or concedes a point, or changes approach; the engine
# attaches what the cited tests recorded; and the Skeptic reconsiders. One exchange per
# checkpoint, and only when there are questions. The Skeptic stays the critic: it judges
# answers against the attached evidence, not against how they're worded.

STANCES = ("defend", "concede", "change_approach")
CONVINCED = ("yes", "partly", "no")
MAX_CITED_TESTS = 8
DEBRIEF_WORD_LIMITS = {"answer.argument": 45, "judgement.why": 30, "verdict_reason": 30, "check.note": 30}
WORD_LIMITS.update({k: v for k, v in DEBRIEF_WORD_LIMITS.items() if k not in WORD_LIMITS})

DEBRIEF_ANSWER_TOOL = {
    "name": "submit_debrief_answers",
    "description": "Answer each of the Skeptic's questions about your testing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "description": "One answer per question in 'skeptic_questions', by its id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "gap_id": {"type": "string", "description": "The question's id, for example 'C2.G1'."},
                        "stance": {
                            "type": "string",
                            "enum": list(STANCES),
                            "description": (
                                "defend: your tests show you're right, and you cite them. concede: you accept "
                                "the point, and say exactly what you withdraw or lower. change_approach: more of "
                                "the same won't settle it, and you say what you'll test differently next round; "
                                "the next round is asked to run it first."
                            ),
                        },
                        "argument": {
                            "type": "string",
                            "description": f"Your answer, in your own words. {_limit('answer.argument')}",
                        },
                        "tests": {
                            "type": "array", "items": {"type": "integer"},
                            "description": (f"The tests that show it, at most {MAX_CITED_TESTS}. The engine attaches "
                                            "what they recorded. Empty when you concede or change approach."),
                        },
                    },
                    "required": ["gap_id", "stance", "argument", "tests"],
                },
            },
        },
        "required": ["answers"],
    },
}

DEBRIEF_ANSWER_SYSTEM_PROMPT = """The Skeptic has reviewed your hypothesis and testing story, and has
questions about your testing (in 'skeptic_questions'). Answer each one, once, by its id, the way a tester
answers a test lead in a debrief.
- defend: when your tests show you're right. Argue it, and cite the tests that show it. The engine attaches
  what those tests actually recorded, so cite the ones whose results make your case, not the ones you
  remember as related.
- concede: when the point is fair. Say exactly what you withdraw or lower.
- change_approach: when more tests of the same kind won't settle it. Say what you'll test differently
  next round (another technique, another starting state, a contrast case) and why that would give new
  evidence. It's a promise: the next round is asked to run that test first, so only promise what you
  can run.
Don't concede to please the Skeptic: if your tests support you, defend. Don't defend what your tests don't
show. Keep every argument short: it has a word limit."""

RECONSIDER_TOOL = {
    "name": "submit_reconsideration",
    "description": "Judge the Driver's answers to your questions, and give this checkpoint's verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgements": {
                "type": "array",
                "description": "One per question you asked, by its id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "gap_id": {"type": "string"},
                        "convinced": {"type": "string", "enum": list(CONVINCED),
                                      "description": "Did the answer, and the evidence attached to it, convince you?"},
                        "why": {"type": "string", "description": _limit("judgement.why")},
                    },
                    "required": ["gap_id", "convinced", "why"],
                },
            },
            "revised_checks": {
                "type": "array",
                "description": ("Only for observations whose check the answers changed: the revised check. "
                                "Empty if none changed."),
                "items": {
                    "type": "object",
                    "properties": {
                        "observation_id": {"type": "string"},
                        "discriminates_from_rival": {"type": "boolean"},
                        "note": {"type": "string", "description": _limit("check.note")},
                    },
                    "required": ["observation_id", "discriminates_from_rival", "note"],
                },
            },
            "verdict": {"type": "string", "enum": ["weak", "strong_enough"],
                        "description": "This checkpoint's verdict, after the debrief."},
            "verdict_reason": {"type": "string", "description": _limit("verdict_reason")},
        },
        "required": ["judgements", "revised_checks", "verdict", "verdict_reason"],
    },
}

RECONSIDER_SYSTEM_PROMPT = """You asked the Driver questions about its testing, and it has answered (in
'answers'). Under each answer is 'evidence': what the tests it cites actually recorded, attached by the
engine, not the Driver's account of them. Judge each answer against that evidence, not against how it's
worded.
- convinced "yes": the evidence shows what the answer claims, and it would have come out differently had
  your concern been right. "partly": some of it holds. "no": it doesn't show it, or the evidence would look
  the same either way.
- A concession settles nothing about the product: the observation it concerns stays unproven. Judge only
  whether the concession is honest and specific.
- A change of approach is judged next round, by its results. Here, say whether the new approach could
  give evidence the old one couldn't.
If an answer changes your view of an observation's evidence, give its revised check. Then give the
checkpoint's verdict: "strong_enough" only if no objection remains: every question that blocked your
verdict convinced you ("yes"), and no observation check says its evidence doesn't tell it from its
rival. Being argued at is not being convinced. Keep every field short."""


def validate_debrief_answers(data, *, gap_ids=()) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("answers"), list):
        return ["'answers' must be a list, one answer per question"]
    errors, answered = [], []
    for i, a in enumerate(data["answers"]):
        if not isinstance(a, dict):
            errors.append(f"answers[{i}] must be an object")
            continue
        where = f"answers[{i}]"
        if a.get("gap_id") not in gap_ids:
            errors.append(f"{where}.gap_id is '{a.get('gap_id')}', which isn't one of the questions ({', '.join(gap_ids)})")
        answered.append(a.get("gap_id"))
        if a.get("stance") not in STANCES:
            errors.append(f"{where}.stance must be one of {', '.join(STANCES)}")
        _check_text(errors, f"{where}.argument", a.get("argument"), "answer.argument")
        if not _is_test_list(a.get("tests")):
            errors.append(f"{where}.tests must be a list of test numbers")
        elif a.get("stance") == "defend" and not a["tests"]:
            errors.append(f"{where} defends, so it must cite the tests that show it")
        elif len(a["tests"]) > MAX_CITED_TESTS:
            errors.append(f"{where}.tests cites {len(a['tests'])} tests, limit {MAX_CITED_TESTS}")
    errors.extend(_once_each("answers", "question", answered, list(gap_ids)))
    return errors


def validate_reconsideration(data, *, gap_ids=(), blocking_ids=(), observation_ids=(), failing_checks=(),
                             defended_ids=None) -> list[str]:
    """failing_checks: observation ids whose first-review check said the evidence doesn't
    tell them from their rival. defended_ids: the questions the Driver defended (None:
    all). A "strong_enough" verdict needs every blocking question defended and judged
    "yes", and every such check revised to true: a promised approach proves nothing yet."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = [f"missing required field '{k}'" for k in RECONSIDER_TOOL["input_schema"]["required"] if k not in data]
    if errors:
        return errors
    judged, convinced = [], {}
    for i, j in enumerate(data["judgements"] if isinstance(data["judgements"], list) else []):
        if not isinstance(j, dict):
            errors.append(f"judgements[{i}] must be an object")
            continue
        if j.get("gap_id") not in gap_ids:
            errors.append(f"judgements[{i}].gap_id is '{j.get('gap_id')}', which isn't one of your questions")
        judged.append(j.get("gap_id"))
        convinced[j.get("gap_id")] = j.get("convinced")
        if j.get("convinced") not in CONVINCED:
            errors.append(f"judgements[{i}].convinced must be one of {', '.join(CONVINCED)}")
        _check_text(errors, f"judgements[{i}].why", j.get("why"), "judgement.why")
    errors.extend(_once_each("judgements", "question", judged, list(gap_ids)))
    revised = {}
    for i, c in enumerate(data["revised_checks"] if isinstance(data["revised_checks"], list) else []):
        if not isinstance(c, dict) or c.get("observation_id") not in observation_ids:
            errors.append(f"revised_checks[{i}] must name an observation in the hypothesis")
            continue
        if not isinstance(c.get("discriminates_from_rival"), bool):
            errors.append(f"revised_checks[{i}].discriminates_from_rival must be a boolean")
        revised[c["observation_id"]] = c.get("discriminates_from_rival")
        _check_text(errors, f"revised_checks[{i}].note", c.get("note"), "check.note")
    if data["verdict"] not in ("weak", "strong_enough"):
        errors.append("'verdict' must be weak or strong_enough")
    elif data["verdict"] == "strong_enough":
        still_blocking = [g for g in blocking_ids
                          if convinced.get(g) != "yes" or (defended_ids is not None and g not in defended_ids)]
        still_failing = [o for o in failing_checks if revised.get(o) is not True]
        if still_blocking or still_failing:
            errors.append("'strong_enough' needs no objection left: "
                          + ", ".join([f"{g} didn't convince you" for g in still_blocking]
                                      + [f"{o}'s check still says it doesn't discriminate" for o in still_failing]))
    _check_text(errors, "verdict_reason", data.get("verdict_reason"), "verdict_reason")
    return errors


def merge_debrief(review: dict, questions: list[dict], answers: dict, reconsideration: dict, evidence: dict) -> list[dict]:
    """Apply the debrief to the checkpoint's review, in place, and return the debrief
    thread: one record per question. A question the Skeptic was convinced on stops
    blocking. A conceded one needs no further answer, but its observation stays
    unproven. The rest stay open, for the next checkpoint. The first review's verdict is
    kept as 'first_verdict'."""
    by_answer = {a["gap_id"]: a for a in (answers or {}).get("answers", [])}
    by_judgement = {j["gap_id"]: j for j in (reconsideration or {}).get("judgements", [])}
    thread = []
    for gap in questions:
        answer, judgement = by_answer.get(gap["id"]), by_judgement.get(gap["id"])
        convinced = (judgement or {}).get("convinced")
        stance = (answer or {}).get("stance")
        # Only a defence that convinced the Skeptic settles a question. "yes" to a change of
        # approach means the approach could work, not that anything was shown: in #266's
        # benchmark, mapping any "yes" to settled cleared blocking questions on a promise.
        if stance == "concede":
            outcome = "conceded"
        elif stance == "change_approach":
            outcome = "new_approach"
        elif stance == "defend" and convinced == "yes":
            outcome = "settled"
        else:
            outcome = "open"
        gap["outcome"] = outcome
        if outcome == "settled" and gap.get("blocks_verdict"):
            gap["blocked_before_debrief"] = True
            gap["blocks_verdict"] = False
        thread.append({
            "gap_id": gap["id"], "kind": gap.get("kind", ""), "question": gap.get("gap", ""),
            "about": gap.get("about", []), "blocked": bool(gap.get("blocked_before_debrief") or gap.get("blocks_verdict")),
            "answer": answer, "evidence": {str(n): evidence.get(n) for n in (answer or {}).get("tests", [])
                                          if n in evidence},
            "judgement": judgement, "outcome": outcome,
        })
    revised = {c["observation_id"]: c for c in (reconsideration or {}).get("revised_checks", [])}
    for check in review.get("observation_checks", []):
        if check["observation_id"] in revised:
            new = revised[check["observation_id"]]
            check["first_discriminates_from_rival"] = check["discriminates_from_rival"]
            check["discriminates_from_rival"] = new["discriminates_from_rival"]
            check["note"] = new["note"]
    if reconsideration:
        review["first_verdict"], review["first_verdict_reason"] = review["verdict"], review["verdict_reason"]
        review["verdict"], review["verdict_reason"] = reconsideration["verdict"], reconsideration["verdict_reason"]
    return thread


def open_part(review: dict) -> dict:
    """The review as the next checkpoint must answer it: without the questions the
    debrief settled or the Driver conceded."""
    return {**review, "gaps": [g for g in review["gaps"] if g.get("outcome") not in ("settled", "conceded")]}

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
    held = {r["id"]: r for r in claim_results(hypothesis, skeptic_review)}
    return [{**observation, "status": held[observation["id"]]["status"],
             "skeptic_note": checks.get(observation["id"], {}).get("note", "")}
            for observation in hypothesis["observations"]]


def claim_results(hypothesis: dict, skeptic_review: dict) -> list[dict]:
    """Each claim of a checkpoint with its status by final_observations' rule, and for an
    inconclusive one what holds it back (#342): its tests don't tell it from its rival,
    and each open blocking question about it. The checkpoint's verdict is all or nothing,
    one blocking question on any claim makes it weak, so the claims say more."""
    checks = {c["observation_id"]: c for c in skeptic_review["observation_checks"]}
    blocking: dict[str, list[str]] = {}
    for gap in skeptic_review["gaps"]:
        if gap["blocks_verdict"]:
            for oid in gap["about"]:
                blocking.setdefault(oid, []).append(gap.get("id", ""))
    results = []
    for observation in hypothesis["observations"]:
        oid = observation["id"]
        tells = checks.get(oid, {}).get("discriminates_from_rival") is True
        held_back = ([] if tells else ["its tests don't tell it from its rival"]) + [
            f"open blocking question {g}".rstrip() for g in blocking.get(oid, [])]
        results.append({"id": oid, "status": "inconclusive" if held_back else "corroborated", "held_back": held_back})
    return results


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


def salvage_casting(validate_fn):
    """The casting round's salvage_fn for call_tool_with_retry (issue #288). On the last
    attempt, a round where most tests are fine shouldn't end the run because of one bad
    one: CI run 37297715890 died after $1.07 when one test of four named a control the map
    doesn't have, three times over. Each test is checked on its own with the adapter's own
    validator, so this needs no knowledge of what the errors mean. It keeps the round only
    if at least half of the tests pass, so a prompt that is badly wrong still fails loudly.
    The dropped tests and why go in 'dropped_tests'."""
    def salvage(answer):
        tests = answer.get("candidate_tests") if isinstance(answer, dict) else None
        if not isinstance(tests, list) or not tests:
            return None
        kept, dropped = [], []
        for test in tests:
            errors = validate_fn({**answer, "candidate_tests": [test]})
            if errors:
                dropped.append({"test": test, "errors": errors})
            else:
                kept.append(test)
        if not kept or 2 * len(kept) < len(tests):
            return None
        return {**answer, "candidate_tests": kept, "dropped_tests": dropped}
    return salvage


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


# Asking a finished run for something it didn't write (#295): a lean run skips the
# story and the debrief, and this answers one question about it afterwards.
ASK_TOOL = {
    "name": "submit_answer",
    "description": "Answer one question about a finished test run, from its record.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The answer in a few plain sentences. If the record can't tell, say so.",
            },
            "tests": _TESTS,
        },
        "required": ["answer", "tests"],
    },
}

ASK_SYSTEM_PROMPT = """You are answering a question about a finished exploratory test run. Your evidence is its
record: every test it ran, and 'run', what the Driver and the Skeptic wrote at each checkpoint. Answer only from
that record, and cite the tests your answer rests on. If the record can't tell, say so instead of guessing. Keep
it short.

Call submit_answer with your answer."""


def validate_answer(data) -> list[str]:
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    if not isinstance(data.get("answer"), str) or not data["answer"].strip():
        errors.append("'answer' must be non-empty text")
    if not _is_test_list(data.get("tests")):
        errors.append("'tests' must be a list of test numbers (empty if none)")
    return errors
