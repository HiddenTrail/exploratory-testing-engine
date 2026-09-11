"""Deciding "is this the same view as one I've seen?" - deterministically, no model.

The browser analog of the game recon's fingerprint, and it draws the same screen/variant
line the game does:

- **State** (a place) is the *structure*: the URL route plus the set of interactive
  controls on the page. Two frames with the same controls are the same view even if
  their content differs - so a map that pans, a feed that scrolls, or a status line that
  flips from "Loading" to "Error" is one state, not a new one. That transient content is
  not lost: it is a *variant*, and any error in it is an oracle finding on the state.
- **Variant** (an appearance) is state + a hash of the visible text, for when it matters
  that the same view is showing something different.

This is pure (URL + Observation dicts), so it is unit-testable against recorded fixtures
with nothing attached. It deliberately does NOT rely on the accessibility tree: measured
on EcoEstate, a Leaflet canvas app, `page.accessibility.snapshot()` returns nothing, so
an identity built on it would collapse every app with a thin a11y tree into one blob.
The interactive-element set read straight off the DOM is the signal that survives.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

# Roles that name a real control (so the signature ignores the giant "generic" map/body
# container, whose accessible name is the whole page's changing text).
CONTROL_ROLES = frozenset({
    "button", "link", "textbox", "checkbox", "radio", "combobox", "tab", "menuitem",
    "menuitemcheckbox", "switch", "slider",
})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _route(url: str) -> str:
    """URL path without the query/fragment. The query often carries transient state
    (a year, a filter) that is a variant of one view, not a different view."""
    return urlparse(url or "").path or "/"


def control_keys(obs) -> list[str]:
    """The sorted set of real controls on the page - the structural skeleton of a state.

    `obs` is an Observation-like object or dict with an `elements` list. Disabled
    controls are kept (their presence is structural); the giant generic container and
    anything not in CONTROL_ROLES is dropped.
    """
    elements = obs["elements"] if isinstance(obs, dict) else obs.elements
    keys = set()
    for e in elements:
        if e.get("role") in CONTROL_ROLES:
            keys.add(f"{e['role']}:{_norm(e.get('name', ''))}")
    return sorted(keys)


def landmark_keys(obs) -> list[str]:
    """Visible heading text - the landmark signal that separates views sharing a control
    set but differing in content (a "You said yes" page vs a "You said no" page, both
    with only a Back button). Bounded and normalised; empty for apps with no headings
    (a canvas map), so it never *over*-splits those - it only adds resolution where the
    page provides it.
    """
    headings = obs.get("headings", []) if isinstance(obs, dict) else getattr(obs, "headings", [])
    return [_norm(h)[:60] for h in (headings or [])[:3]]


def signature(obs) -> str:
    """A stable state signature: URL route + control skeleton + landmark headings. Same
    signature == same state, tolerant of content (body text, map position, loaded vs
    error) by construction, but resolving views that differ by heading."""
    url = obs["url"] if isinstance(obs, dict) else obs.url
    skeleton = ";".join(control_keys(obs))
    landmarks = ";".join(landmark_keys(obs))
    return f"{_route(url)}|{skeleton}|{landmarks}"


def same_state(a, b) -> bool:
    return signature(a) == signature(b)


def _visible_text(obs) -> str:
    return obs["text"] if isinstance(obs, dict) else obs.text


def appearance(obs) -> str:
    """State signature plus a short hash of the visible text - the variant key. Two
    Observations of the same state with different text get different appearances."""
    text_hash = hashlib.blake2s(_norm(_visible_text(obs)).encode(), digest_size=6).hexdigest()
    return f"{signature(obs)}#{text_hash}"
