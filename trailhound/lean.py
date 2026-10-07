"""Lean runs, for experiments (issue #295).

Most runs are experiments: did a change make the engine find more? For that the model
only has to write what decides a finding. A lean run drops the rest of what it writes:
the testing story, the debrief, the bug report write-ups, and the free text in the
hypothesis and the Skeptic's review that nothing downstream decides on. Each skipped
part can be switched back on for an experiment that is about it.

The dropped fields are filled with empty values once an answer is in, so everything
after the call (the report, the summary, the next checkpoint) reads them as before.
Nothing here imports trailhound.tools, which imports it.
"""

from __future__ import annotations

import copy

# The calls a lean run skips, and can switch back on one by one (--with).
PARTS = ("story", "debrief", "bug_reports")

# Fields the model doesn't write in a lean run, as paths into the tool's input schema.
# An array's path goes on into its items.
HYPOTHESIS_DROPS = (
    ("behaviors",), ("untested",),
    ("observations", "mechanism"), ("observations", "why"),
    ("prior_gaps", "reason"),
)
# coverage.material stays: it is one of the four objections a verdict can rest on.
SKEPTIC_DROPS = (
    ("observation_checks", "note"),
    ("coverage", "untouched"), ("coverage", "note"),
    ("prior_gaps_check", "note"),
)

CASTING_NOTE = """

This is a lean run, for an experiment: keep 'reasoning' to one short sentence and each
predicted outcome to one short line."""

HYPOTHESIS_NOTE = """

This is a lean run, for an experiment: there is no behaviors or untested list, and no mechanism or why
for an observation. Give only the fields the tool asks for, each as short as it can be."""

SKEPTIC_NOTE = """

This is a lean run, for an experiment: there are no notes and no list of untouched areas. List only the
gaps that block your verdict, and keep each one short."""


def _node(schema: dict, key: str) -> dict:
    node = schema["properties"][key]
    return node["items"] if node.get("type") == "array" and "properties" in node.get("items", {}) else node


def strip_schema(tool: dict, drops) -> dict:
    """A copy of the tool with the dropped fields gone from its schema, so the model
    isn't asked for them at all."""
    lean = copy.deepcopy(tool)
    for path in drops:
        node = lean["input_schema"]
        for key in path[:-1]:
            node = _node(node, key)
        node["properties"].pop(path[-1], None)
        if path[-1] in node.get("required", []):
            node["required"].remove(path[-1])
    return lean


def _empty(tool: dict, path) -> object:
    node = tool["input_schema"]
    for key in path[:-1]:
        node = _node(node, key)
    return [] if node["properties"][path[-1]].get("type") == "array" else ""


def fill(answer: dict, tool: dict, drops) -> dict:
    """The dropped fields put back as empty values (an empty list or text), so code that
    reads them doesn't have to know the run was lean. Fields the model sent anyway are
    kept."""
    for path in drops:
        empty = _empty(tool, path)
        holders = [answer]
        for key in path[:-1]:
            nxt = []
            for holder in holders:
                value = holder.get(key)
                nxt.extend(v for v in (value if isinstance(value, list) else [value]) if isinstance(v, dict))
            holders = nxt
        for holder in holders:
            holder.setdefault(path[-1], copy.copy(empty))
    return answer
