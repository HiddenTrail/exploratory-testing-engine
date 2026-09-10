"""The web-recon ontology: what a browser exploration writes down.

The same shape as the game recon's `ontology.json` - a labelled multigraph of states
(nodes) and (state, action) -> state transitions (edges), each state carrying the
interactive elements found on it - so a wiki builder can consume either. The
differences are all gains a browser hands you for free over a game's pixels: a state is
identified by a *semantic* signature (URL + accessibility structure) rather than a pixel
fingerprint, an element is addressed by a stable locator rather than a vetted
coordinate, and every observation can carry hard *evidence* (console errors, HTTP
status, exceptions) - which is what lets this find functional bugs, not just a map.

Deliberately pure: no Playwright, no network, no model. It is dataclasses and JSON
(de)serialisation, so it round-trips under test with nothing attached.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

SCHEMA = "web-recon/1"


@dataclass(frozen=True)
class Element:
    """One interactive thing discovered on a state, read from the page - not invented.

    `key` is stable across visits (role + accessible name + a positional tiebreak) so a
    resumed run and the transition table can refer to the same control. `locator` is how
    to act on it deterministically (a CSS/role selector), kept separate from `key`
    because the key is for identity and the locator is for action.
    """
    key: str
    role: str
    name: str
    kind: str            # "link" | "button" | "textbox" | "checkbox" | ... (the a11y role family)
    locator: str
    committing: bool = False   # does acting on it plausibly mutate state? (fail-closed default below)
    href: str = ""


@dataclass(frozen=True)
class Evidence:
    """Something the browser reported that a deterministic oracle can judge.

    e.g. an HTTP 500, a console error, an unhandled rejection, a dead control. `seq` is
    the action index it was seen at, so a finding can be traced to the exact step.
    """
    kind: str                 # "http_error" | "console_error" | "exception" | "dead_control" | ...
    summary: str
    state_id: str = ""
    action_key: str = ""
    seq: int = -1
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    kind: str                 # "click" | "navigate" | "fill" | ...
    element_key: str = ""
    target: str = ""          # locator for a click, url for a navigate

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.element_key or self.target}"


@dataclass
class Transition:
    id: str
    source: str
    action: Action
    dest: str
    effect: str               # "navigate" | "same" | "changed" | "error" | "dead"
    changed: bool = False
    count: int = 1
    first_seen: int = 0
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class State:
    """One identified app state (a view). Named structurally by default; a human/model
    name is optional and never required, exactly as the game recon keeps screen names as
    a nicety over the id."""
    id: str
    url: str
    signature: str
    title: str = ""
    elements: list[Element] = field(default_factory=list)
    observations: int = 1
    first_seen: int = 0
    # Cells/paths of the signature that were seen to vary between visits without the
    # state being a different place - the browser analog of the game's volatile mask.
    volatile: list[str] = field(default_factory=list)
    name: str = ""            # optional, model-supplied (off by default)
    purpose: str = ""         # optional, model-supplied


@dataclass
class Ontology:
    target: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    states: list[State] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    findings: list[Evidence] = field(default_factory=list)
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "target": self.target,
            "session": self.session,
            "states": [asdict(s) for s in self.states],
            "transitions": [
                {**{k: v for k, v in asdict(t).items() if k != "action"},
                 "action": asdict(t.action)}
                for t in self.transitions
            ],
            "findings": [asdict(e) for e in self.findings],
        }

    @staticmethod
    def from_dict(data: dict) -> "Ontology":
        states = [
            State(
                **{**s, "elements": [Element(**e) for e in s.get("elements", [])]}
            )
            for s in data.get("states", [])
        ]
        transitions = []
        for t in data.get("transitions", []):
            t = dict(t)
            action = Action(**t.pop("action"))
            evidence = [Evidence(**e) for e in t.pop("evidence", [])]
            transitions.append(Transition(action=action, evidence=evidence, **t))
        findings = [Evidence(**e) for e in data.get("findings", [])]
        return Ontology(
            schema=data.get("schema", SCHEMA),
            target=data.get("target", {}),
            session=data.get("session", {}),
            states=states,
            transitions=transitions,
            findings=findings,
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> "Ontology":
        return Ontology.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
