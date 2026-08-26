"""Asserts engine.tools and the token_purchase adapter's per-SUT pieces are
unchanged from experiments/token-purchase-poc/run_live.py - the literal
contract this port must not silently drift from. Loads the original module
directly from its file path (it's not an importable package)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from engine import tools as engine_tools
from engine.adapters.token_purchase import adapter as token_purchase_adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = REPO_ROOT / "experiments" / "token-purchase-poc"


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

def test_hypothesis_tool_schema_matches(original):
    assert engine_tools.HYPOTHESIS_TOOL == original.HYPOTHESIS_TOOL


def test_skeptic_tool_schema_covers_everything_the_original_required(original):
    # History of deliberate divergence from the original, in order:
    # 1. engine.tools added a required coverage_breadth_check field after a live run
    #    showed "strong_enough" firing on 5 narrow tests that never touched most of
    #    the documented interface - the original had no way to weigh breadth of
    #    coverage, only depth of evidence for individual claims.
    # 2. A later consistency pass measured real duplication across a live checkpoint
    #    (reasoning and coverage_breadth_check independently restating the same 6
    #    untested behaviors, ~1300 chars) and found inference_validity_check/
    #    anomaly_critique were each one prose blob covering ALL claimed anomalies at
    #    once, instead of checking each individually. Fix: drop the pure-restatement
    #    'reasoning' field, and reshape coverage_breadth_check into an object
    #    (coverage_breadth: {material, note}) and inference_validity_check +
    #    anomaly_critique into one list with an entry per anomaly (anomaly_checks:
    #    [{anomaly_ref, discriminates_from_rival, rival_is_genuine, note}]).
    # So engine.tools is no longer a literal field-name superset of the original -
    # it's a superset of what the original REQUIRED, reshaped for size/clarity, not
    # a smaller or weaker check. Assert the substance survived under its new name.
    original_required = set(original.SKEPTIC_TOOL["input_schema"]["required"])
    engine_required = set(engine_tools.SKEPTIC_TOOL["input_schema"]["required"])
    # Every original required field maps onto something still required in engine.tools,
    # either unchanged (verdict, gaps, recommended_next_tests, prior_critique_addressed)
    # or reshaped (inference_validity_check/anomaly_critique -> anomaly_checks).
    unchanged = {"verdict", "gaps", "recommended_next_tests", "prior_critique_addressed"}
    assert unchanged <= original_required
    assert unchanged <= engine_required
    assert {"inference_validity_check", "anomaly_critique"} <= original_required
    assert "anomaly_checks" in engine_required

    # Both deliberate additions are present and required.
    assert {"coverage_breadth", "anomaly_checks"} <= engine_required
    assert "coverage_breadth_check" not in original_required  # confirms this really is an addition

    engine_props = engine_tools.SKEPTIC_TOOL["input_schema"]["properties"]
    assert set(engine_props["coverage_breadth"]["properties"]) == {"material", "note"}
    assert set(engine_props["anomaly_checks"]["items"]["properties"]) == {
        "anomaly_ref", "discriminates_from_rival", "rival_is_genuine", "note",
    }
    assert engine_props["verdict"]["enum"] == ["weak", "strong_enough"]

    # The duplicative top-level 'reasoning' field the consistency pass measured as
    # pure restatement is gone - a deliberate removal, not an oversight.
    assert "reasoning" not in engine_props


def test_bug_report_tool_schema_matches(original):
    assert engine_tools.BUG_REPORT_TOOL == original.BUG_REPORT_TOOL


def test_hypothesis_system_prompt_matches(original):
    assert engine_tools.HYPOTHESIS_SYSTEM_PROMPT == original.HYPOTHESIS_SYSTEM_PROMPT


def test_skeptic_system_prompt_still_covers_the_original_material_reasons(original):
    # Deliberately no longer byte-identical (see
    # test_skeptic_tool_schema_covers_everything_the_original_required) - check the
    # original's core teaching content ('your_own_prior_review', the continuity
    # check) is still present. 'inference_validity_check' itself was renamed away
    # (see discriminates_from_rival below) so it's expected to disappear from the
    # engine version - that's the deliberate reshape, not lost coverage.
    assert "your_own_prior_review" in original.SKEPTIC_SYSTEM_PROMPT
    assert "your_own_prior_review" in engine_tools.SKEPTIC_SYSTEM_PROMPT
    assert "inference_validity_check" in original.SKEPTIC_SYSTEM_PROMPT

    for phrase in ("coverage_breadth", "discriminates_from_rival", "anomaly_checks"):
        assert phrase in engine_tools.SKEPTIC_SYSTEM_PROMPT
        assert phrase not in original.SKEPTIC_SYSTEM_PROMPT


def test_bug_report_system_prompt_matches(original):
    # One deliberate difference: the original leaked domain vocabulary ("real
    # auth_token/card_number/expiry/cvv/credit_count values") into an otherwise
    # domain-agnostic prompt. engine.tools generalizes this to "real values" -
    # content must match after that substitution; whitespace/line-wrap can
    # differ since the shorter phrase reflows the paragraph.
    original_generalized = original.BUG_REPORT_SYSTEM_PROMPT.replace(
        "real auth_token/card_number/expiry/cvv/credit_count values", "real values"
    )
    normalize = lambda text: " ".join(text.split())
    assert normalize(engine_tools.BUG_REPORT_SYSTEM_PROMPT) == normalize(original_generalized)


def test_hypothesis_and_bug_report_validator_behavior_matches_on_sample_inputs(original):
    # Unaffected by the coverage_breadth_check addition - these should still match exactly.
    sample_bad_hyp = {"observed_behavior": "x"}
    assert engine_tools.validate_hypothesis_response(sample_bad_hyp) == original.validate_hypothesis_response(sample_bad_hyp)

    sample_bad_bugs = {"bugs": []}
    assert engine_tools.validate_bug_reports(sample_bad_bugs) == original.validate_bug_reports(sample_bad_bugs)


def test_skeptic_validator_requires_coverage_breadth_and_anomaly_checks():
    sample_missing_new_fields = {
        "verdict": "weak",
        "gaps": ["a", "b"],
        "recommended_next_tests": ["a", "b"],
        "prior_critique_addressed": "n/a",
    }
    errors = engine_tools.validate_skeptic_response(sample_missing_new_fields)
    assert "missing required field 'coverage_breadth'" in errors
    assert "missing required field 'anomaly_checks'" in errors

    sample_complete = {
        **sample_missing_new_fields,
        "coverage_breadth": {"material": False, "note": "x"},
        "anomaly_checks": [],
    }
    assert engine_tools.validate_skeptic_response(sample_complete) == []


def test_skeptic_validator_checks_anomaly_checks_count_against_hypothesis():
    sample = {
        "verdict": "weak",
        "gaps": ["a", "b"],
        "recommended_next_tests": ["a", "b"],
        "prior_critique_addressed": "n/a",
        "coverage_breadth": {"material": False, "note": "x"},
        "anomaly_checks": [
            {"anomaly_ref": "test 3", "discriminates_from_rival": False, "rival_is_genuine": True, "note": "n"},
        ],
    }
    assert engine_tools.validate_skeptic_response(sample, expected_anomaly_count=1) == []
    errors = engine_tools.validate_skeptic_response(sample, expected_anomaly_count=2)
    assert any("exactly one entry per claimed anomaly" in e for e in errors)


# --- token_purchase adapter's per-SUT pieces vs. the original ---

def test_casting_tool_schema_matches(original):
    assert token_purchase_adapter.CASTING_TOOL == original.CASTING_TOOL


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
