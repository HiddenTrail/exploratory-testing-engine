"""The deterministic graph oracles flag the navigation anomalies, no model."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze import analyze, blocked_controls, dead_controls, dead_ends, redundant_controls  # noqa: E402
from schema import Action, Ontology, State, Transition  # noqa: E402


def _tr(tid, src, key, dest, effect):
    return Transition(id=tid, source=src, dest=dest, effect=effect,
                      action=Action(kind="click", element_key=key, target="#x"))


def _ontology():
    states = [State(id=i, url="u", signature=i) for i in ("st01", "st02", "st03")]
    transitions = [
        _tr("t1", "st01", "button:A", "st02", "navigate"),
        _tr("t2", "st01", "button:B", "st02", "navigate"),   # redundant with A -> st02
        _tr("t3", "st01", "button:Z", "st01", "dead"),       # dead control
        _tr("t4", "st02", "button:Back", "st01", "navigate"),
        _tr("t5", "st03", "button:X", "st03", "blocked"),    # blocked; st03 has no way out
    ]
    return Ontology(states=states, transitions=transitions)


def test_dead_control_flagged():
    d = dead_controls(_ontology())
    assert len(d) == 1 and d[0].kind == "dead_control"


def test_blocked_control_flagged():
    b = blocked_controls(_ontology())
    assert len(b) == 1 and b[0].state_id == "st03"


def test_redundant_controls_flagged():
    r = redundant_controls(_ontology())
    assert len(r) == 1 and "st02" in r[0].summary and "button:A" in r[0].summary


def test_dead_ends_flagged():
    ends = {e.state_id for e in dead_ends(_ontology())}
    assert ends == {"st03"}  # st01 and st02 both navigate elsewhere


def test_single_state_is_not_a_dead_end():
    solo = Ontology(states=[State(id="st01", url="u", signature="a")], transitions=[])
    assert dead_ends(solo) == []


def test_analyze_covers_every_oracle():
    kinds = {e.kind for e in analyze(_ontology())}
    assert {"dead_control", "blocked_control", "redundant_controls", "dead_end"} <= kinds
