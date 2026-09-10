"""Deterministic oracles find the functional defect with no model in the loop."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracles import console_errors, http_errors, run_observation_oracles  # noqa: E402
from perceive import Observation  # noqa: E402
from schema import Evidence  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def test_finds_the_property_prices_500():
    obs = Observation.load(FIX / "eco-loaded.json")
    errors = http_errors(obs, state_id="s1", seq=3)
    assert any(e.detail["status"] == 500 and "property-prices" in e.detail["url"] for e in errors), \
        [e.summary for e in errors]


def test_console_noise_is_filtered():
    obs = Observation.load(FIX / "eco-loaded.json")
    for e in console_errors(obs):
        assert "frame-ancestors" not in e.summary.lower()
        assert "react devtools" not in e.summary.lower()


def test_synthetic_console_error_is_reported():
    obs = {
        "url": "u", "text": "", "elements": [], "network": [],
        "console": [{"type": "error", "text": "TypeError: x is undefined", "location": "app.js:10"}],
    }
    findings = console_errors(obs)
    assert len(findings) == 1 and findings[0].kind == "console_error"


def test_clean_page_yields_no_findings():
    obs = {"url": "u", "text": "", "elements": [],
           "network": [{"method": "GET", "url": "/api/ok", "status": 200}],
           "console": [{"type": "log", "text": "hello", "location": ""}]}
    assert run_observation_oracles(obs) == []


def test_findings_are_evidence_objects():
    obs = Observation.load(FIX / "eco-loaded.json")
    for e in run_observation_oracles(obs, "s1", 3):
        assert isinstance(e, Evidence)
