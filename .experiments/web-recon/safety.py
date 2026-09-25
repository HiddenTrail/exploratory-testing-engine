"""The read-only safety gate: *how* may the crawl act on this control - or not at all?

The browser analog of the game kit's modality gating. A read-only pass looks, navigates,
toggles a view and runs a search, but never *commits* data - nothing deleted, bought,
saved, sent, or typed into a sensitive field. `plan()` is a pure function of a captured
element returning how to actuate it, so it is exhaustively unit-testable with no browser.

What it allows:
- **click** a link/button/tab/menu item with a benign name, and a *selection* control
  (radio, checkbox, tab, switch). These are usually a client-side view toggle - but a
  toggle that auto-persists to the server (a "Public listing" switch) would slip through
  looking benign, and a reboot cannot undo a server write. This is a looser posture than
  strict read-only, taken deliberately so the crawl can exercise the controls it finds;
  the residual mutation risk is what the Stage 5 vetting pass exists to close.
- **fill** a *search/filter* text box with a benign probe value (never pressing Enter, so
  it cannot submit an enclosing form) - a query typed into a field, not a write.

What it refuses (fail-safe by denying whole classes rather than trusting a control to
look harmless): a submit/reset, any name carrying a mutating verb, an off-site or
non-http link, a disabled control, a sensitive field (password/email/amount/…) or any
generic text box, a combobox/slider/listbox we cannot actuate without guessing, and any
role we do not recognise. A benignly-named control that secretly mutates would still slip
through; closing that is the Stage 5 vetting pass's job, and until then this is the honest
posture, not a guaranteed one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Selection controls: clicking one toggles a view/selection, not server state.
SELECTION_ROLES = frozenset({
    "radio", "checkbox", "switch", "tab", "menuitemcheckbox", "menuitemradio",
})
# Everything a read-only crawl may click.
CLICK_ROLES = frozenset({"link", "button", "tab", "menuitem"}) | SELECTION_ROLES
# Text entry roles - only fillable when they are clearly a search/filter box.
TEXT_ROLES = frozenset({"textbox", "searchbox"})

# A benign probe typed into a search box - a query that writes nothing.
SEARCH_PROBE = "test"

# Mutating verbs in an accessible name. Word boundaries so "saved search" is caught but a
# substring like "delete" inside "undeletable" is not the sole trigger. Deliberately
# broad: a false "skip" only costs coverage, a false "act" could mutate real data.
_MUTATION_WORDS = (
    "delete", "remove", "discard", "buy", "purchase", "pay", "checkout", "order",
    "submit", "save", "send", "confirm", "create", "update", "edit", "publish",
    "post", "apply", "book", "upload", "subscribe", "unsubscribe", "sign out",
    "signout", "log out", "logout", "add to cart", "add to basket", "reset",
    "cancel", "accept", "agree", "download",
)
_MUTATION_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _MUTATION_WORDS) + r")\b")

# A text field that is clearly a search/filter - safe to type a query into.
_SEARCHY_RE = re.compile(r"\b(search|filter|find|postcode|postal|zip|query|lookup)\b")
# A field we must never type into, by name or by input type.
_SENSITIVE_RE = re.compile(
    r"\b(password|passcode|email|e-mail|card|cvv|cvc|iban|account|amount|price|"
    r"quantity|qty|phone|tel|ssn|login|username|user\s?name)\b")
_SENSITIVE_TYPES = frozenset({"password", "email", "tel", "number", "date", "file"})

# Link schemes that are not a same-app navigation to follow.
_NON_NAV_SCHEMES = frozenset({"mailto", "tel", "javascript", "file", "data", "blob", "ws", "wss", "about"})

# Stage 5b vetting. Two disjoint sets decide whether a *committing* control - one the
# read-only gate refuses - may be actuated when the operator explicitly enables mutations
# (crawl --mutate). Fail-closed throughout: a committing control is touched only if it is
# affirmatively reversible AND carries no destructive verb; anything unrecognised is refused.
#
# NEVER actuated, mutations enabled or not: irreversible, destructive, money, auth, or
# data-writing. This is stricter than a bare read-only skip - it is the "even if you asked,
# no" list, so a --mutate run cannot delete, buy, send, publish, or sign out.
_DESTRUCTIVE_WORDS = (
    "delete", "remove", "discard", "buy", "purchase", "pay", "checkout", "order",
    "save", "send", "confirm", "create", "publish", "post", "book", "upload",
    "subscribe", "unsubscribe", "sign out", "signout", "log out", "logout", "reset",
    "add to cart", "add to basket", "download", "accept", "agree", "edit", "update",
)
_DESTRUCTIVE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _DESTRUCTIVE_WORDS) + r")\b")
# The only committing actions a vetting pass admits: a search / filter / sort / show query,
# which is a read on the server (an idempotent GET-style request), reversible by nature.
_REVERSIBLE_WORDS = ("search", "filter", "find", "show", "sort", "calculate", "compute",
                     "preview", "refresh", "lookup", "go")
_REVERSIBLE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _REVERSIBLE_WORDS) + r")\b")


@dataclass(frozen=True)
class Plan:
    kind: str | None       # "click" | "fill" | None (skip)
    reason: str
    value: str = ""        # what to type, for a "fill"


@dataclass(frozen=True)
class Vetting:
    kind: str | None       # "submit_search" | "submit" | None (refuse)
    reason: str
    value: str = ""        # what to type, for a submit_search


def _netloc(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def _field_text(element: dict) -> str:
    return f"{element.get('name', '')} {element.get('type', '')}".strip().lower()


def plan(element: dict, base_origin: str = "") -> Plan:
    """How to actuate this control in a read-only pass: click, fill, or skip (with why)."""
    role = element.get("role", "")
    name = (element.get("name") or "").strip().lower()
    href = (element.get("href") or "").strip()
    itype = (element.get("type") or "").strip().lower()

    if element.get("disabled"):
        return Plan(None, "the control is disabled - acting would hang, not act")
    if itype in ("submit", "reset"):
        return Plan(None, f"an input of type {itype!r} commits a form")
    if name and _MUTATION_RE.search(name):
        return Plan(None, f"the name {name!r} carries a mutating verb")

    if href:
        parsed = urlparse(href)
        scheme = parsed.scheme.lower()
        if scheme in _NON_NAV_SCHEMES:
            return Plan(None, f"a {scheme}: link is not a navigation to follow")
        # Any link naming a host other than the app's (absolute or protocol-relative)
        # leaves the page and is refused. Fail closed: if the base origin is unknown we
        # cannot confirm same-origin, so a hosted link is refused too. A relative link
        # (no netloc) stays in the app and is allowed.
        if parsed.netloc and parsed.netloc.lower() != _netloc(base_origin):
            return Plan(None, f"an off-site link to {parsed.netloc} leaves the app under test")
        if scheme and scheme not in ("http", "https"):
            return Plan(None, f"a {scheme}: link is not an http navigation")

    if role in CLICK_ROLES:
        return Plan("click", "a same-origin navigation / benign control / view toggle")

    if role in TEXT_ROLES:
        if itype in _SENSITIVE_TYPES or _SENSITIVE_RE.search(_field_text(element)):
            return Plan(None, "a sensitive field - read-only never types into it")
        if itype == "search" or _SEARCHY_RE.search(_field_text(element)):
            return Plan("fill", "a search/filter box - safe to type a query", SEARCH_PROBE)
        return Plan(None, "a generic text field - read-only does not fill it")

    return Plan(None, f"role {role!r} is not a recognised actuable control")


def committing(element: dict, base_origin: str = "") -> bool:
    """True if the read-only crawl must NOT act on this element at all."""
    return plan(element, base_origin).kind is None


def vet(element: dict, base_origin: str = "", enabled: bool = False) -> Vetting:
    """Stage 5b: may this *committing* control be actuated as a vetted mutation?

    Pure, deterministic, and fail-closed - the model never reaches this decision. It admits
    exactly one class: a **reversible, read-style query submit** (a search / filter / sort /
    show), which is an idempotent GET on the server, not a data write. Anything carrying a
    destructive verb (delete, buy, send, save, publish, sign out, ...) is refused even here,
    as is a sensitive field and anything unrecognised. Returns how to actuate it, or refuse.

    `enabled` gates the whole pass: with mutations off (the default) every control is
    refused, so the crawl stays read-only unless the operator opts in with --mutate."""
    if not enabled:
        return Vetting(None, "mutations are disabled - the crawl is read-only")
    role = element.get("role", "")
    name = (element.get("name") or "").strip().lower()
    itype = (element.get("type") or "").strip().lower()
    field = _field_text(element)

    if element.get("disabled"):
        return Vetting(None, "the control is disabled")
    if _DESTRUCTIVE_RE.search(name) or _DESTRUCTIVE_RE.search(field):
        return Vetting(None, "carries a destructive/irreversible verb - refused even under --mutate")

    # A text field: the sensitive guard applies here (never type into a password/card/price
    # box). A search/filter box may be filled with a benign query and submitted (Enter) -
    # the read-only pass fills but will not submit; this is its vetted, reversible extension.
    if role in TEXT_ROLES:
        if itype in _SENSITIVE_TYPES or _SENSITIVE_RE.search(field):
            return Vetting(None, "a sensitive field - never submitted")
        if itype == "search" or _SEARCHY_RE.search(field):
            return Vetting("submit_search", "submit a search/filter query - an idempotent, reversible read", SEARCH_PROBE)
        return Vetting(None, "a generic text field - not a vetted query")
    # A submit button, or a button named like a reversible query action (Search / Filter / Sort).
    if (itype == "submit" or role == "button") and _REVERSIBLE_RE.search(name):
        return Vetting("submit", "a reversible query submit (search/filter/sort/show)")
    return Vetting(None, "not an affirmatively-reversible commit - fail closed")


def vetted_actions(elements: list[dict], base_origin: str = "", enabled: bool = False
                   ) -> list[tuple[dict, Vetting]]:
    """Each committing element paired with its vetting, for the ones a mutation pass admits."""
    out = []
    for e in elements:
        v = vet(e, base_origin, enabled)
        if v.kind is not None:
            out.append((e, v))
    return out


def action_plans(elements: list[dict], base_origin: str = "") -> list[tuple[dict, Plan]]:
    """Each element paired with its actuation plan, for the ones the crawl may act on."""
    out = []
    for e in elements:
        p = plan(e, base_origin)
        if p.kind is not None:
            out.append((e, p))
    return out


def safe_actions(elements: list[dict], base_origin: str = "") -> list[dict]:
    """The elements the read-only crawl may act on (click or fill)."""
    return [e for e, _ in action_plans(elements, base_origin)]
