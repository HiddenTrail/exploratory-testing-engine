"""Asserts engine.tools and the token_purchase adapter's per-SUT pieces are
unchanged from .experiments/token-purchase-poc/run_live.py - the literal
contract this port must not silently drift from. Loads the original module
directly from its file path (it's not an importable package)."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from engine import tools as engine_tools
from engine.adapters.token_purchase import adapter as token_purchase_adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = REPO_ROOT / ".experiments" / "token-purchase-poc"


@pytest.fixture(scope="module")
def original():
    sys.path.insert(0, str(ORIGINAL_DIR))
    try:
        spec = importlib.util.spec_from_file_location("original_token_purchase_run_live", ORIGINAL_DIR / "run_live.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(ORIGINAL_DIR))


# --- Domain-agnostic engine.tools vs. the original's most-evolved version ---

# The one standing rival explanation added to the shared vocabulary after a live
# run against a non-HTTP SUT. Five taps in a row were reported as five ordinary
# no-ops when in fact the client was behind a modal and accepting nothing at all -
# one cause, not five broken controls. It is phrased with no domain nouns because
# it is the same failure as an HTTP SUT returning the unchanged prior state, or a
# request rejected before it reached any handler.
_UNACCEPTED_INPUT_RIVAL = "NEVER ACCEPTED"


# The Driver's hypothesis, the Skeptic's review and the bug reports are no longer
# compared with the original: issue #41 replaced all three on purpose with structured
# schemas (short fields, word limits, engine-assigned ids, finding / anomaly / bug
# kinds, a verdict that must follow from the Skeptic's objections, and a status the
# engine decides instead of the bug-report model). What must survive the redesign is
# checked directly below and in test_hypothesis_schema.py / test_skeptic_schema.py,
# notably the unaccepted-input rival.


def test_hypothesis_prompt_prefers_one_cause_over_several_broken_controls():
    # The specific reasoning the addition exists to install, and the reason it is in
    # the shared prompt rather than one adapter's: a claim resting on several inputs
    # that each did nothing must consider that nothing was being accepted at all.
    prompt = engine_tools.HYPOTHESIS_SYSTEM_PROMPT
    assert _UNACCEPTED_INPUT_RIVAL in prompt
    assert "the input was never accepted at all" in engine_tools.HYPOTHESIS_TOOL["input_schema"]["properties"][
        "observations"]["description"]
    assert "one cause instead of many" in prompt
    assert "identical observation" in prompt
    # And the Skeptic must be able to fail a hypothesis for not ruling it out,
    # otherwise the instruction to the Driver has no consequence.
    assert "discriminates_from_rival=false" in engine_tools.SKEPTIC_SYSTEM_PROMPT
    assert _UNACCEPTED_INPUT_RIVAL in engine_tools.SKEPTIC_SYSTEM_PROMPT
    assert _UNACCEPTED_INPUT_RIVAL in engine_tools.SKEPTIC_TOOL["input_schema"]["properties"][
        "observation_checks"]["description"]


# --- token_purchase adapter's per-SUT pieces vs. the original ---

def test_casting_tool_schema_matches(original):
    # Deliberate divergence: oracle_claim_id was added as a required
    # candidate_tests field so a test can cite a ranked oracle idea by its
    # stable id, instead of relying on the Driver's free-text
    # linked_hypothesis to match it back to an oracle claim - see
    # docs/ontology-todo.md's former "known gap: claim matching is
    # exact-string only". Stripping it back out should make the schemas
    # identical again, proving that's the only change.
    engine_schema = copy.deepcopy(token_purchase_adapter.CASTING_TOOL)
    items = engine_schema["input_schema"]["properties"]["candidate_tests"]["items"]
    del items["properties"]["oracle_claim_id"]
    items["required"].remove("oracle_claim_id")
    assert engine_schema == original.CASTING_TOOL


def test_casting_system_prompt_matches(original):
    for budget, is_first in ((12, True), (8, False)):
        assert token_purchase_adapter.casting_system_prompt(budget, is_first) == original.casting_system_prompt(budget, is_first)


def test_known_accounts_and_schema_doc_match(original):
    assert token_purchase_adapter.KNOWN_ACCOUNTS == original.KNOWN_ACCOUNTS
    assert token_purchase_adapter.API_SCHEMA_DOC == original.API_SCHEMA_DOC
    assert token_purchase_adapter.KNOWN_DECLINE_REASONS == original.KNOWN_DECLINE_REASONS


def test_validate_casting_response_matches_on_sample_inputs(original):
    sample = {"give_up": False, "reasoning": "x", "candidate_tests": []}
    assert token_purchase_adapter.validate_casting_response(sample) == original.validate_casting_response(sample)
