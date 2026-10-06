"""Test fully by default, and be careful only where a target is tagged careful (#299).

The engine is for testing: on a target it types, submits, buys, changes settings and
builds on its own earlier steps. A tag marks what needs care. On a careful part of a
target, the Driver only looks: the read-only safety gate decides each step there, as it
did everywhere before. Two things are refused everywhere, careful or not: logging out,
which ends the session every test starts from, and leaving the site (session.py's
guard, #308).

Tags come from the target's file, test-targets/careful/<product>.json, set once per
product, and from WEB_GUI_CAREFUL for one run (comma-separated routes like "/#/payment"
and control names like "Delete account", or "*" for the whole target). Pure, so it is
tested without a browser.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CAREFUL_DIR = REPO / "test-targets" / "careful"
_ENV = "WEB_GUI_CAREFUL"

# Ends the logged-in session every test starts from, so it's refused even when testing fully.
_LOG_OUT_RE = re.compile(r"\b(log ?out|sign ?out|logoff|log off)\b", re.IGNORECASE)

EVERYTHING = {"everything": True, "routes": [], "controls": []}
NOTHING = {"everything": False, "routes": [], "controls": []}


def load(product: str = "", env: str | None = None, careful_dir: Path = CAREFUL_DIR) -> dict:
    """The target's careful tags: its file, plus WEB_GUI_CAREFUL for this run."""
    tags = {"everything": False, "routes": [], "controls": []}
    path = careful_dir / f"{product}.json" if product else None
    if path is not None and path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        tags["everything"] = bool(saved.get("everything"))
        tags["routes"] += [r for r in saved.get("routes", []) if isinstance(r, str) and r.strip()]
        tags["controls"] += [c for c in saved.get("controls", []) if isinstance(c, str) and c.strip()]
    for item in (os.environ.get(_ENV, "") if env is None else env).split(","):
        item = item.strip()
        if item == "*":
            tags["everything"] = True
        elif item.startswith(("/", "#")):
            tags["routes"].append(item)
        elif item:
            tags["controls"].append(item)
    return tags


def _route(route: str) -> str:
    return "/" + route.lstrip("/") if not route.startswith("#") else "/" + route


def applies(tags: dict, route: str = "", name: str = "") -> bool:
    """Whether a step on `route` (path and #fragment), or on a control called `name`,
    is on a careful part of the target."""
    if tags.get("everything"):
        return True
    here = _route(route) if route else ""
    if here and any(here.startswith(_route(r)) for r in tags.get("routes", [])):
        return True
    lowered = (name or "").lower()
    return bool(lowered) and any(c.lower() in lowered for c in tags.get("controls", []))


def logs_out(text: str) -> bool:
    return bool(_LOG_OUT_RE.search(text or ""))


def describe(tags: dict) -> str:
    """The line a run says it with, in the log, the Driver's briefing and the report."""
    if tags.get("everything"):
        return ("Careful: this whole target is tagged careful, so the Driver only looks. A step that would submit, "
                "buy, delete or type into anything but a search box is refused.")
    parts = [f"routes {', '.join(tags['routes'])}" if tags.get("routes") else "",
             f"controls named {', '.join(tags['controls'])}" if tags.get("controls") else ""]
    tagged = " and ".join(p for p in parts if p)
    if not tagged:
        return "Testing fully: nothing on this target is tagged careful."
    return f"Testing fully, except where tagged careful ({tagged}): there the Driver only looks."
