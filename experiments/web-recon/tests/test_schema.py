"""The ontology round-trips through JSON with every field intact."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema import Action, Element, Evidence, Ontology, State, Transition  # noqa: E402


def test_ontology_round_trips():
    onto = Ontology(
        target={"url": "http://localhost:5173/"},
        session={"seconds": 12, "actions": 3},
        states=[
            State(id="s1", url="http://localhost:5173/", signature="/|button:go",
                  title="Home", observations=2, first_seen=0,
                  elements=[Element(key="button:go", role="button", name="Go",
                                    kind="button", locator="#go", committing=True)]),
        ],
        transitions=[
            Transition(id="t1", source="s1",
                       action=Action(kind="click", element_key="button:go", target="#go"),
                       dest="s2", effect="navigate", changed=True, count=1,
                       evidence=[Evidence(kind="http_error", summary="500 /api/x", detail={"status": 500})]),
        ],
        findings=[Evidence(kind="console_error", summary="boom", state_id="s1", seq=2)],
    )

    back = Ontology.from_dict(onto.to_dict())

    assert back.schema == onto.schema
    assert back.target == {"url": "http://localhost:5173/"}
    assert back.states[0].elements[0].name == "Go"
    assert back.states[0].elements[0].committing is True
    assert back.transitions[0].action.kind == "click"
    assert back.transitions[0].action.id == "click:button:go"
    assert back.transitions[0].evidence[0].detail["status"] == 500
    assert back.findings[0].summary == "boom"


def test_save_and_load(tmp_path):
    onto = Ontology(target={"url": "u"}, states=[State(id="s1", url="u", signature="sig")])
    path = onto.save(tmp_path / "ontology.json")
    assert Ontology.load(path).states[0].signature == "sig"
