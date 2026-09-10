"""The read-only safety gate: may the crawl act on this control?

The browser analog of the game kit's modality gating + coordinate denylist, and it
holds the same line: in a read-only pass the bot looks and navigates but never *commits*
anything - no form submitted, nothing deleted, bought, saved or sent. It is a pure
function of a captured element, so it is exhaustively unit-testable with no browser.

It fails safe by denying whole risky *classes* rather than trusting a control to look
harmless: anything we would have to type into, anything whose name carries a mutating
verb, a submit/reset input, an off-site or non-http link, and any control whose role we
do not recognise are all refused. What is left - plain links to the same origin and
buttons/tabs/menu items with a benign name - is what the read-only crawl is allowed to
click. A benignly-named button that secretly mutates would slip through; that residual
risk is what the Stage 5 vetting pass exists to close, and until then read-only is the
honest posture rather than a guaranteed one.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Roles the crawl would have to *enter* something into. Off limits in read-only.
FORM_INPUT_ROLES = frozenset({
    "textbox", "checkbox", "radio", "combobox", "listbox", "slider", "switch",
    "spinbutton", "searchbox", "menuitemcheckbox", "menuitemradio",
})

# Roles the crawl may click when nothing else refuses them.
CLICKABLE_ROLES = frozenset({"link", "button", "tab", "menuitem"})

# Mutating verbs in an accessible name. Word-ish boundaries so "saved search" is caught
# but "unsaved" is not the trigger and "delete" inside "undeletable" does not misfire on
# a substring alone - kept deliberately broad, since a false "committing" only costs
# coverage while a false "safe" could mutate real data.
_MUTATION_WORDS = (
    "delete", "remove", "discard", "buy", "purchase", "pay", "checkout", "order",
    "submit", "save", "send", "confirm", "create", "update", "edit", "publish",
    "post", "apply", "book", "upload", "subscribe", "unsubscribe", "sign out",
    "signout", "log out", "logout", "add to cart", "add to basket", "reset",
    "cancel", "accept", "agree", "download",
)
_MUTATION_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _MUTATION_WORDS) + r")\b")


def _origin(url: str) -> str:
    p = urlparse(url or "")
    return f"{p.scheme}://{p.netloc}" if p.netloc else ""


def classify(element: dict, base_origin: str = "") -> tuple[bool, str]:
    """Return (committing, reason). `committing` True means the read-only crawl must NOT
    act on it. `reason` explains the verdict, shown before anything clicks, as the game
    kit shows its refusals."""
    role = element.get("role", "")
    name = (element.get("name") or "").strip().lower()
    href = (element.get("href") or "").strip()
    itype = (element.get("type") or "").strip().lower()

    if role in FORM_INPUT_ROLES:
        return True, f"a {role} would take input, which read-only does not send"
    if itype in ("submit", "reset"):
        return True, f"an input of type {itype!r} commits a form"
    if name and _MUTATION_RE.search(name):
        return True, f"the name {name!r} carries a mutating verb"

    if href:
        scheme = urlparse(href).scheme.lower()
        if scheme in ("mailto", "tel", "javascript", "file", "data"):
            return True, f"a {scheme}: link is not a navigation to follow"
        if scheme in ("http", "https"):
            origin = _origin(href)
            if base_origin and origin and origin != base_origin:
                return True, f"an off-site link to {origin} leaves the app under test"

    if role not in CLICKABLE_ROLES:
        # Fail closed: a control whose role we do not recognise is not proven safe.
        return True, f"role {role!r} is not a recognised safe-to-click control"

    return False, "safe: a same-origin navigation / benign control"


def committing(element: dict, base_origin: str = "") -> bool:
    return classify(element, base_origin)[0]


def safe_actions(elements: list[dict], base_origin: str = "") -> list[dict]:
    """The subset of a state's elements the read-only crawl may act on."""
    return [e for e in elements if not committing(e, base_origin)]
