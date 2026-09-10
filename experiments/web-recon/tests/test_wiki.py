"""The wiki builds from an ontology by arithmetic - findings, graph, states - no model."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema import Action, Element, Evidence, Ontology, State, Transition  # noqa: E402
from wiki import build_wiki  # noqa: E402


def _ontology(with_findings=True):
    states = [
        State(id="st01", url="http://x/", title="Home",
              signature="/|button:no;button:yes|is this a test?",
              elements=[Element(key="button:yes", role="button", name="Yes",
                                kind="button", locator="#yes")]),
        State(id="st02", url="http://x/", title="Home",
              signature="/|button:back|you said yes",
              elements=[Element(key="button:back", role="button", name="Back",
                                kind="button", locator="#back")]),
    ]
    transitions = [Transition(id="tr001", source="st01", dest="st02", effect="navigate",
                              action=Action(kind="click", element_key="button:Yes", target="#yes"))]
    findings = ([Evidence(kind="http_error", summary="500 GET /api/property-prices?year=2024",
                          state_id="st01", seq=1)] if with_findings else [])
    return Ontology(target={"url": "http://x/"}, session={"actions": 3},
                    states=states, transitions=transitions, findings=findings)


def test_wiki_reports_findings_states_and_edges():
    doc = build_wiki(_ontology())
    assert "Functional findings" in doc
    assert "property-prices" in doc            # the finding detail
    assert "st01" in doc and "st02" in doc     # both states rendered
    assert "button:Yes" in doc                 # the transition/edge label
    assert "read-only, no model" in doc        # the provenance claim
    assert "http://x/" in doc                  # the target


def test_clean_ontology_states_no_findings():
    doc = build_wiki(_ontology(with_findings=False))
    assert "No functional findings" in doc


def test_finding_gives_its_state_a_red_node():
    doc = build_wiki(_ontology())
    assert "#dc2626" in doc  # red used for a state carrying a finding (and the HTTP badge)


def test_empty_ontology_does_not_crash():
    doc = build_wiki(Ontology(target={"url": "u"}))
    assert "(no states)" in doc and "No functional findings" in doc
