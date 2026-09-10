"""The optional LLM synthesis: digest/validate/render are pure; the call is tested with
a fake client so no model is contacted."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import synthesize  # noqa: E402
from schema import Action, Evidence, Ontology, State, Transition  # noqa: E402


def _onto():
    return Ontology(
        target={"url": "http://x/"},
        states=[State(id="st01", url="http://x/", signature="/|button:go|home", title="Home")],
        transitions=[Transition(id="t1", source="st01", dest="st01", effect="dead",
                                action=Action(kind="click", element_key="button:Go", target="#go"))],
        findings=[Evidence(kind="http_error", summary="500 /api/x", state_id="st01")],
        observations=[Evidence(kind="dead_control", summary="button:Go on st01 changed nothing",
                               state_id="st01")])


def test_digest_carries_the_measurements():
    d = synthesize.digest(_onto())
    for token in ("http://x/", "st01", "500 /api/x", "dead_control"):
        assert token in d, token


def test_validate_review():
    good = {"summary": "an app", "claims": [
        {"claim": "c", "cites": "st01", "confidence": "measured", "rival": "r"}]}
    assert synthesize.validate_review(good) == []
    bad = {"summary": "", "claims": [
        {"claim": "c", "cites": "st01", "confidence": "maybe", "rival": ""}]}
    assert synthesize.validate_review(bad)  # empty summary, bad confidence, empty rival


def test_render_synthesis():
    review = {"summary": "An EcoEstate price map.", "claims": [
        {"claim": "Shows property prices", "cites": "st01", "confidence": "measured",
         "rival": "could be a trend view"}]}
    doc = synthesize.render_synthesis(review)
    for token in ("An EcoEstate price map.", "Shows property prices", "measured",
                  "could be a trend view", "st01"):
        assert token in doc, token


class _FakeBlock:
    type = "tool_use"
    name = "submit_review"
    id = "b1"

    def __init__(self, data):
        self.input = data


class _FakeMessage:
    stop_reason = "tool_use"
    usage = None

    def __init__(self, data):
        self.content = [_FakeBlock(data)]


class _FakeClient:
    """Stands in for the Anthropic client: returns a canned tool call, no network."""

    def __init__(self, data):
        self._data = data
        self.messages = self

    def create(self, **kwargs):
        return _FakeMessage(self._data)


def test_synthesize_with_a_fake_client():
    review = {"summary": "s", "claims": [
        {"claim": "c", "cites": "st01", "confidence": "inferred", "rival": "r"}]}
    out = synthesize.synthesize(_onto(), _FakeClient(review), "fake-model")
    assert out["summary"] == "s"
    assert out["claims"][0]["confidence"] == "inferred"
