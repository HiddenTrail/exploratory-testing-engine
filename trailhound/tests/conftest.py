"""Shared test setup."""

import pytest

from trailhound import budget


@pytest.fixture(autouse=True)
def _fresh_spending_limit():
    """The spending limit (trailhound/budget.py) counts model calls for the whole process, so
    each test starts with a fresh one: otherwise the stubbed calls of earlier tests add up
    until a later test hits the limit."""
    budget._GUARD = budget.SpendGuard()
    yield
