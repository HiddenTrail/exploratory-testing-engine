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

# Fields a test carries that aren't inputs to the system under test.
_NOT_INPUTS = ("linked_hypothesis", "oracle_claim_id")
MAX_VALUES = 10
MAX_VALUE_CHARS = 30


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
