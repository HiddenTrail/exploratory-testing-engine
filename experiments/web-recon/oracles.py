"""Deterministic functional oracles: turn an Observation's evidence into findings.

This is the browser's advantage over a game's pixels made concrete. A game could only
observe "the picture changed"; a browser reports HTTP status, console errors and
exceptions, so a whole class of defects is caught by *rules*, with no model and no
prediction - the EcoEstate 500 is found here for free. The judgments a rule cannot make
(does a control do what its label implies?) are left to the optional, off-by-default
model pass; nothing here needs it.

Each oracle takes an Observation (and the state/seq it was seen in) and returns zero or
more `Evidence`. Pure and testable against recorded fixtures.
"""

from __future__ import annotations

from schema import Evidence

# Console message types that are defects on their face.
_ERROR_CONSOLE_TYPES = frozenset({"error", "pageerror"})

# A CSP-in-<meta> warning and a "download React DevTools" notice are noise, not defects;
# keep the oracle from crying wolf on them. Matched loosely on the message text.
_CONSOLE_IGNORE = (
    "content security policy directive 'frame-ancestors'",
    "download the react devtools",
)


def http_errors(obs, state_id: str = "", seq: int = -1) -> list[Evidence]:
    """Every non-2xx/3xx response the page made. A 4xx/5xx from the app's own API is a
    finding on its face; a third-party 4xx is still worth recording, so all are kept."""
    out = []
    for n in (obs["network"] if isinstance(obs, dict) else obs.network):
        status = n.get("status", 0)
        if status >= 400:
            out.append(Evidence(
                kind="http_error",
                summary=f"{status} {n.get('method', 'GET')} {n.get('url', '')}",
                state_id=state_id, seq=seq,
                detail={"status": status, "url": n.get("url", ""), "method": n.get("method", "")},
            ))
    return out


def console_errors(obs, state_id: str = "", seq: int = -1) -> list[Evidence]:
    """Console errors and uncaught page exceptions, minus known dev-noise."""
    out = []
    for m in (obs["console"] if isinstance(obs, dict) else obs.console):
        if m.get("type") not in _ERROR_CONSOLE_TYPES:
            continue
        text = (m.get("text") or "")
        if any(pat in text.lower() for pat in _CONSOLE_IGNORE):
            continue
        out.append(Evidence(
            kind="console_error" if m["type"] == "error" else "exception",
            summary=text[:200],
            state_id=state_id, seq=seq,
            detail={"location": m.get("location", "")},
        ))
    return out


OBSERVATION_ORACLES = (http_errors, console_errors)


def run_observation_oracles(obs, state_id: str = "", seq: int = -1) -> list[Evidence]:
    """Every observation-level oracle, flattened. Transition-level oracles (a control
    that changed nothing, two controls to the same state) come once the crawl exists."""
    findings: list[Evidence] = []
    for oracle in OBSERVATION_ORACLES:
        findings.extend(oracle(obs, state_id, seq))
    return findings
