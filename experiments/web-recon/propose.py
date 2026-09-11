"""Optional LLM proposal of interactable elements the deterministic scan may have missed -
the Driver's "propose" half of a driver/skeptic loop, and off by default.

The creed holds: the model only *nominates* candidates. It does not get to assert an
element exists or is safe. Every nomination is then, by the deterministic crawler:
  1. **resolved** on the live page (a nomination that matches no unique element is a
     hallucination and is dropped before any action - the skeptic rejecting it pre-test);
  2. run through the **deterministic safety gate** (`safety.plan` decides click/fill/skip -
     the model proposes, the gate disposes, so a proposal can never widen what is touched);
  3. **actuated and measured** like any other control - a proposed-but-`dead`/`blocked`
     control is the skeptic's verdict, recorded as measurement, not the model's word.

So this widens *coverage* (controls the DOM read missed - a div with a click handler, an
icon button with no accessible name the model can still describe) without ceding the
read-only guarantee or the "map is discovered, not declared" creed.

Authentication is the engine's, reused (as synthesize.py does). Digest/validation/parse
are pure and unit-tested with a fake client; the real call runs only behind `--llm`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.client import build_client, call_tool_with_retry, default_model  # noqa: E402

# Roles the crawler can robustly locate by (role, accessible name) and actuate - the model
# is asked to nominate only these, so a nomination is resolvable and actionable, not a
# guess at a raw CSS path (which it would hallucinate).
PROPOSABLE_ROLES = ("button", "link", "tab", "menuitem", "radio", "checkbox", "switch")

# A hard cap on how many nominations one state's call may yield, so a runaway response
# cannot balloon the action budget. The crawler also dedupes against what it already found.
MAX_CANDIDATES = 8

PROPOSE_TOOL = {
    "name": "propose_interactables",
    "description": (
        "Nominate interactive controls on this page that the automated DOM scan may have "
        "missed - a clickable icon with no text label, a div acting as a button, a control "
        "revealed only on hover. Only nominate things a user could click; do not invent."),
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": list(PROPOSABLE_ROLES),
                                 "description": "The control's ARIA role."},
                        "name": {"type": "string",
                                 "description": "Its exact visible/accessible name, as a user would read it."},
                        "why": {"type": "string",
                                "description": "Why you believe it is interactive and was likely missed."},
                    },
                    "required": ["role", "name", "why"],
                },
            },
        },
        "required": ["candidates"],
    },
}

SYSTEM = """You are helping an automated read-only web crawler find interactive controls its
DOM scan may have missed. You are given what the crawler already measured on one page - its
URL, headings, the interactive elements it already found, and a slice of the visible text.

Nominate up to a handful of controls a user could interact with that are NOT already in the
found list - for example an icon-only button, a div that behaves like a button, a tab or a
control that appears only on hover. Give each one's ARIA role and its exact visible name.

Rules: only nominate controls you have concrete reason to believe exist on THIS page from the
evidence given; do not invent plausible-sounding controls; do not repeat ones already found.
Every nomination will be resolved against the live page and dropped if it matches nothing, so
a wrong guess only wastes a check - but do not pad. Call propose_interactables."""


def propose_digest(obs, max_text: int = 800) -> str:
    """A compact, model-readable description of one state - only what was measured. Pure."""
    found = "\n".join(f"  - {e.get('role', '')}: {e.get('name', '') or '(no name)'}"
                      for e in obs.elements) or "  (none)"
    text = (obs.text or "").strip().replace("\n", " ")
    if len(text) > max_text:
        text = text[:max_text] + " ..."
    return (f"URL: {obs.url}\nTITLE: {obs.title!r}\n"
            f"HEADINGS: {', '.join(obs.headings) or '(none)'}\n"
            f"ALREADY-FOUND INTERACTIVE ELEMENTS:\n{found}\n"
            f"VISIBLE TEXT (excerpt):\n{text}")


def validate_candidates(data) -> list[str]:
    """Shape-check the tool payload before the crawler trusts it. Pure."""
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    cands = data.get("candidates")
    if not isinstance(cands, list):
        return ["'candidates' must be a list"]
    errors = []
    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            errors.append(f"candidates[{i}] must be an object")
            continue
        if c.get("role") not in PROPOSABLE_ROLES:
            errors.append(f"candidates[{i}].role must be one of {PROPOSABLE_ROLES}")
        if not isinstance(c.get("name"), str) or not c["name"].strip():
            errors.append(f"candidates[{i}].name must be a non-empty string")
    return errors


def parse_candidates(data) -> list[dict]:
    """The validated payload -> a clean, capped, deduped candidate list. Pure.

    A name carrying a double quote is dropped: the crawler addresses a candidate by a
    `role=<role>[name="<name>"]` selector string, which a quote in the name would break."""
    seen, out = set(), []
    for c in data.get("candidates", []):
        role, name = c.get("role", ""), (c.get("name") or "").strip()
        if role not in PROPOSABLE_ROLES or not name or '"' in name:
            continue
        key = (role, name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"role": role, "name": name, "why": c.get("why", "")})
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def propose(obs, client, model: str, max_tokens: int = 800) -> list[dict]:
    """One tool-forced nomination call for a single state. Pure of I/O beyond the client,
    so it is testable with a fake client."""
    data = call_tool_with_retry(
        client, model=model, system=SYSTEM, tools=[PROPOSE_TOOL],
        tool_name="propose_interactables", user_message=propose_digest(obs),
        validate_fn=validate_candidates, max_tokens=max_tokens)
    return parse_candidates(data)


def make_proposer(client=None, model: str = ""):
    """Return a `proposer(obs) -> list[candidate]` the crawler can call per state, or None
    if the engine's auth is not configured. Soft-fails per call to an empty list, so a
    flaky model degrades the crawl to the deterministic path rather than breaking it."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO_ROOT / ".env")
        client = client or build_client()
        model = model or default_model()
    except (Exception, SystemExit):  # noqa: BLE001 - no model configured -> no proposer
        return None

    def proposer(obs) -> list[dict]:
        try:
            return propose(obs, client, model)
        except (Exception, SystemExit):  # noqa: BLE001 - a bad call must not break the crawl
            return []

    return proposer
