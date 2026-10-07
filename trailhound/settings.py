"""Settings the engine reads from the environment.

Since the rename to Trailhound (#335) their names start with TRAILHOUND_. The old
ENGINE_ names still work for now, with a warning, so a spending limit set under an old
name is never silently ignored. When both are set, the new name wins, and the run says
the old one is ignored.
"""

from __future__ import annotations

import os

PREFIX = "TRAILHOUND_"
OLD_PREFIX = "ENGINE_"
_warned: set[str] = set()


def read(name: str) -> tuple[str, str]:
    """A setting's value, stripped ("" when it isn't set), and the variable it came
    from, so an error message can name the one the person actually set."""
    new, old = PREFIX + name, OLD_PREFIX + name
    value = os.environ.get(new, "").strip()
    old_value = os.environ.get(old, "").strip()
    if not old_value:
        return value, new
    if old not in _warned:
        _warned.add(old)
        if not value:
            print(f"  {old} is the old name of {new}. It still works for now, but rename it.")
        elif value != old_value:
            print(f"  {old} is set too, and ignored: {new} ({value}) counts, not {old} ({old_value}).")
    return (value, new) if value else (old_value, old)


def get(name: str) -> str:
    return read(name)[0]
