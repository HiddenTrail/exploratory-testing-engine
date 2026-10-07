"""What the tests have actually sent, worked out from the log (issue #65).

The Skeptic never sees test data, so it used to guess coverage from the Driver's
prose, and it guessed wrong: in a complex_sut run it listed "malformed/missing
client_id" and "priority=high" as untouched after tests had sent an empty
client_id and priority high. This gives it the facts instead: for each input
field in the adapter's casting schema, the values tried so far, and for a field
with a fixed set of values (an enum or a boolean), the ones never tried.

It reads the adapter's own casting schema, so it works for every adapter without
adapter code. It summarises inputs only, never results, so the Skeptic stays cold.
"""

from __future__ import annotations

import json
import re

# Fields a test carries that aren't inputs to the system under test.
_NOT_INPUTS = ("linked_hypothesis", "oracle_claim_id")
MAX_VALUES = 10
MAX_VALUE_CHARS = 30

# The kinds of value a field can be sent (#328), so the context can say a field has had
# only plain text and never an empty value, a boundary or markup. A value can be several
# kinds at once ("-1" is a number and negative). "text" means none of the others.
VALUE_KINDS = ("empty", "spaces", "padded", "long", "number", "zero", "negative", "decimal", "huge",
               "markup", "script", "quote", "non-ascii", "email", "text")
LONG_VALUE = 256
HUGE_NUMBER = 10 ** 9
_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", re.ASCII)
_ZERO = re.compile(r"[+-]?(0+(\.0*)?|\.0+)([eE][+-]?\d+)?", re.ASCII)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# A script in a value: a script tag, a javascript: link, or an event handler attribute.
# Only real handler names count: "one=1" and "Online=yes" aren't scripts.
_SCRIPT = re.compile(r"<\s*script|javascript:|\bon(error|load|click|dblclick|mouse\w+|focus|blur|change|input|"
                     r"submit|key(down|up|press)|animation\w+|toggle|pointer\w+)\s*=", re.IGNORECASE)


def value_kinds(value) -> list[str]:
    """The kinds of one value sent to a field, in VALUE_KINDS order."""
    text = "" if value is None else str(value)
    if text == "":
        return ["empty"]
    if not text.strip():
        return ["spaces"]
    kinds = set()
    if text != text.strip():
        kinds.add("padded")
    if len(text) >= LONG_VALUE:
        kinds.add("long")
    if _NUMBER.fullmatch(text.strip()):
        kinds.add("number")
        number = float(text.strip())
        if _ZERO.fullmatch(text.strip()):           # "1e-400" is a tiny number, not zero
            kinds.add("zero")
        if number < 0:
            kinds.add("negative")
        if "." in text:                             # written with a point; "1e5" is a whole number
            kinds.add("decimal")
        if abs(number) >= HUGE_NUMBER:
            kinds.add("huge")
    if "<" in text and ">" in text:
        kinds.add("markup")
    if _SCRIPT.search(text):
        kinds.add("script")
    if "'" in text or '"' in text:
        kinds.add("quote")
    if any(ord(c) > 127 for c in text):
        kinds.add("non-ascii")
    if _EMAIL.fullmatch(text.strip()):
        kinds.add("email")
    if not kinds or kinds == {"padded"}:
        kinds.add("text")
    return [k for k in VALUE_KINDS if k in kinds]


def input_fields(casting_tool_schema: dict) -> dict[str, dict]:
    """The test fields that are sent to the system, by name, with their schema.
    Empty for a casting schema without the usual candidate_tests shape."""
    items = ((casting_tool_schema or {}).get("input_schema", {}).get("properties", {})
             .get("candidate_tests", {}).get("items", {}).get("properties", {}))
    return {name: spec for name, spec in items.items()
            if name not in _NOT_INPUTS and not name.startswith("predicted_")}


def _shown(value):
    if isinstance(value, (list, dict)):        # a test's steps (#310): compact, and cut like text
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + "..."
    return value


def summarize(casting_tool_schema: dict, tests: list[dict]) -> dict:
    """tests: the candidate tests that ran (not skipped), in order. Returns
    {"tests_run": n, "fields": [{"field", "values_tried", "more_values"?, "never_tried"?}]}."""
    fields = []
    for name, spec in input_fields(casting_tool_schema).items():
        tried = []
        for test in tests:
            value = test.get(name)
            if value is not None and value not in tried:
                tried.append(value)
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in tried):
            tried.sort()
        row = {"field": name, "values_tried": [_shown(v) for v in tried[:MAX_VALUES]]}
        if len(tried) > MAX_VALUES:
            row["more_values"] = len(tried) - MAX_VALUES
        choices = spec.get("enum") or ([True, False] if spec.get("type") == "boolean" else None)
        if choices:
            row["never_tried"] = [c for c in choices if c not in tried]
        fields.append(row)
    return {"tests_run": len(tests), "fields": fields}
