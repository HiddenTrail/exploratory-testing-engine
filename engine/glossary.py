"""The terms a run report uses, with what they mean (issue #285).

A report is full of short tags: kinds, statuses, coverage levels, debrief stances and
outcomes. A reader shouldn't need the source code to read them, so the report ends with
a glossary of the terms that appear in it. The meanings come from the same definitions
the engine and its prompts use, so the glossary can't drift from what the model was told.
"""

from __future__ import annotations

import json

from engine.tools import CONVINCED, COVERAGE_LEVELS, OBJECTION_KINDS, QUALITY_SEEN

# Bach's dashboard levels, as the short tags the report shows.
LEVEL_TAGS = {"can_it_work": "L1", "common_and_critical": "L2", "deep": "L3"}
# The status tag "Where it stands" shows for each quality, short enough not to wrap.
QUALITY_TAGS = {"no_problems_seen_yet": "OK so far", "concerns": "Concerns", "problems_found": "Problems"}

def _label(tag: str, raw: str) -> str:
    plain = raw.replace("_", " ")
    return tag if tag.lower() == plain or plain in tag else f"{tag} ({plain})"


# Each group: its title, the output.json field its terms appear in, and term -> meaning,
# keyed by the raw value so a term counts as used only when that field holds it.
GROUPS = [
    ("Observations", "kind", {
        "finding": "something iffy worth a look; no problem shown yet",
        "anomaly": "a real problem that doesn't clearly break a known fact, or doesn't reproduce consistently",
        "bug": "breaks a named known fact and reproduces consistently",
    }),
    ("Status", "status", {
        "corroborated": "the Skeptic's last check says the evidence tells the claim from its rival, and no "
                        "blocking question is left about it",
        "inconclusive": "not corroborated: the evidence doesn't yet tell the claim from its rival",
    }),
    ("Where it stands: coverage", "coverage", dict(COVERAGE_LEVELS)),
    ("Where it stands: what's been seen", "quality", dict(QUALITY_SEEN)),
    ("Confidence", "confidence", {"high": "the testing behind the estimate is solid", "medium": "some of it is",
                                  "low": "little of it is"}),
    ("The Skeptic's questions", "kind", dict(OBJECTION_KINDS)),
    ("The debrief: the Driver's answer", "stance", {
        "defend": "the tests show the Driver is right, and it cites them",
        "concede": "the Driver accepts the point and says what it withdraws or lowers",
        "change_approach": "more of the same won't settle it; the Driver says what it will test differently",
    }),
    ("The debrief: the Skeptic's judgement", "convinced", dict(zip(CONVINCED, (
        "the evidence shows what the answer claims", "some of it holds",
        "it doesn't show it, or would look the same either way")))),
    ("The debrief: outcome", "outcome", {
        "settled": "a defence that convinced the Skeptic; the question no longer blocks the verdict",
        "conceded": "the Driver accepted the point; its observation stays unproven",
        "new_approach": "the Driver will test it differently next round; still open",
        "open": "not settled; carried into the next checkpoint",
    }),
    ("Replays before a bug is reported", "replay", {
        "reproduced": "every cited test came out the same when run again from a fresh start",
        "not reproduced": "a cited test came out differently, so the bug was lowered to an anomaly",
        "couldn't replay": "the replay couldn't run or couldn't tell, so the bug was lowered",
        "not available": "this adapter doesn't replay tests",
    }),
]
_TAGS = {"coverage": LEVEL_TAGS, "quality": QUALITY_TAGS, "convinced": {c: f"convinced: {c}" for c in CONVINCED}}


def glossary_for(output: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """The groups of terms that appear in this run, each with the terms it uses, as the
    report shows them (L2, OK so far, change approach...)."""
    text = json.dumps(output, ensure_ascii=False)
    used = []
    for group, field, terms in GROUPS:
        present = [(_label(_TAGS.get(field, {}).get(raw, raw.replace("_", " ")), raw), meaning)
                   for raw, meaning in terms.items() if f'"{field}": "{raw}"' in text]
        if present:
            used.append((group, present))
    return used
