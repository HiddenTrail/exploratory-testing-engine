"""engine.bootstrap.jira_mock - the stubbed ticket store proving the
context-enriched bootstrap roadmap's "swap the source" design holds,
without any real JIRA auth/API (see the module's own TODO for Phase 4)."""

import pytest

from engine.bootstrap.jira_mock import fetch_ticket_context


def test_fetch_ticket_context_returns_known_ticket_text():
    context = fetch_ticket_context("PROJ-101")

    assert "Exploratory testing needed for the credits-purchase API" in context
    assert "credits-purchase API for an app that sells in-app credits" in context


def test_fetch_ticket_context_raises_for_unknown_ticket():
    with pytest.raises(KeyError, match="Unknown mock ticket 'NOPE-1'"):
        fetch_ticket_context("NOPE-1")

    with pytest.raises(KeyError, match="PROJ-101"):
        fetch_ticket_context("NOPE-1")
