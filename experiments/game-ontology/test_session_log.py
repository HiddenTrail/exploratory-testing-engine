"""`write_session_log`: one row per action taken, in wall-clock order.

Separate from `report.md`, which groups by screen - this is the other cut, one line per
occurrence in the order it happened, for retracing a run against what somebody was
watching at the time. See `Recon._log_activity` for how a row gets built during a real
pass; this covers only the serialisation, which is where a `;` in a note or an action
description would otherwise misparse the row silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recon import write_session_log  # noqa: E402


def test_a_row_per_action_in_the_order_given(tmp_path):
    rows = [
        {"at": "2026-09-08-11:51:30", "screen": "sc01", "action": "click at (0.500, 0.500)",
         "result": "same screen, different appearance, 6 cells, 3024ms", "notes": ""},
        {"at": "2026-09-08-11:51:33", "screen": "sc01", "action": "click at (0.200, 0.030)",
         "result": "went to another screen, now on sc02, 556 cells, 3093ms",
         "notes": "sc02-v1 changed 109 of 576 cells while being sampled with no input in flight"},
    ]
    path = write_session_log(rows, tmp_path)
    assert path == tmp_path / "session-log.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "2026-09-08-11:51:30; sc01; click at (0.500, 0.500); "
        "same screen, different appearance, 6 cells, 3024ms; ",
        "2026-09-08-11:51:33; sc01; click at (0.200, 0.030); "
        "went to another screen, now on sc02, 556 cells, 3093ms; "
        "sc02-v1 changed 109 of 576 cells while being sampled with no input in flight",
    ]


def test_a_semicolon_inside_a_field_does_not_split_the_row(tmp_path):
    """A `;` in a note is exactly what would misparse a row - the field it lives in has
    to lose it rather than pass it through, or a reader (or a spreadsheet import) sees an
    extra column that was never there."""
    rows = [{"at": "2026-09-08-11:51:30", "screen": "sc01", "action": "click at (0.500, 0.500)",
             "result": "nothing visible changed, 0 cells, 3010ms",
             "notes": "could not get a verdict for click:a; click:b; click:c"}]
    path = write_session_log(rows, tmp_path)
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line.count(";") == 4  # exactly the 4 field separators, none from the note
    assert "could not get a verdict for click:a, click:b, click:c" in line


def test_no_rows_writes_an_empty_file(tmp_path):
    """A pass that never completed even one action - refused before its first move, say -
    should not fail to write the file it promised."""
    path = write_session_log([], tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""
