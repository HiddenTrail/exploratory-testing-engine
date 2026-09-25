"""The casting checks every adapter shares (issue #96): give_up may be left out
when there are tests, the round's reasoning is short, and every adapter's later
rounds describe the structured feedback the same way. No LLM calls."""

import importlib

import pytest

from engine.tools import CASTING_REASONING_WORDS, PRIOR_FEEDBACK_GUIDE, casting_envelope_errors

ADAPTERS = ("token_purchase", "complex_sut", "clash_royale", "web_gui")


def test_give_up_can_be_left_out_when_there_are_tests():
    # The most common casting retry after #41: an answer with tests but no give_up.
    errors, tests = casting_envelope_errors({"reasoning": "r", "candidate_tests": [{"x": 1}]})
    assert errors == [] and tests == [{"x": 1}]


def test_give_up_is_required_when_there_are_no_tests():
    errors, _ = casting_envelope_errors({"reasoning": "r", "candidate_tests": []})
    assert any("missing required field 'give_up'" in e for e in errors)
    assert casting_envelope_errors({"give_up": True, "reasoning": "r", "candidate_tests": []})[0] == []


def test_no_tests_without_giving_up_is_rejected():
    errors, _ = casting_envelope_errors({"give_up": False, "reasoning": "r", "candidate_tests": []})
    assert any("must be non-empty unless give_up is true" in e for e in errors)


def test_reasoning_is_short():
    near = {"give_up": True, "reasoning": "word " * (CASTING_REASONING_WORDS + 10), "candidate_tests": []}
    assert casting_envelope_errors(near)[0] == []
    far = {**near, "reasoning": "word " * (2 * CASTING_REASONING_WORDS + 1)}
    assert any("'reasoning' is far too long" in e for e in casting_envelope_errors(far)[0])


@pytest.mark.parametrize("name", ADAPTERS)
def test_every_adapter_uses_the_shared_checks_and_guide(name):
    adapter = importlib.import_module(f"engine.adapters.{name}.adapter")
    assert any("missing required field 'give_up'" in e
               for e in adapter.validate_casting_response({"reasoning": "r", "candidate_tests": []}))
    assert PRIOR_FEEDBACK_GUIDE in adapter.casting_system_prompt(4, False)
    assert PRIOR_FEEDBACK_GUIDE not in adapter.casting_system_prompt(6, True)
