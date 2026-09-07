"""The guards on the synthesis pass, with a stub client in place of a model.

No test here makes a real call, and none needs to. What is worth testing is not the prose - a
model writes that and it will be different every time - but the three things that decide whether
the prose is *admissible*: that a claim must cite a measurement that exists, that an
uncitable claim cannot be laundered into a paragraph, and that a failed call costs three pages
rather than the whole run.

The validator tests are written against the messages it produces as much as against its verdicts,
because those messages are fed back to the model verbatim on retry. A validator that says
"invalid claims" buys three identical failures; one that names the offending key and lists the
real ones gets a corrected answer on the second attempt.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthesize  # noqa: E402
import wikibuild  # noqa: E402
from engine import client as engine_client  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ontology.json"
AT = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def facts(tmp_path: Path) -> wikibuild.Facts:
    run = tmp_path / "recon-1"
    run.mkdir()
    run.joinpath("ontology.json").write_bytes(FIXTURE.read_bytes())
    return wikibuild.derive(run, json.loads(FIXTURE.read_text(encoding="utf-8")))


def good_answer(keys: set[str]) -> dict:
    key = sorted(keys)[0]
    return {
        "title": "What the routes imply about this interface",
        "summary": "Everything returns through one screen and one screen has no recorded exit.",
        "sections": [
            {"heading": "The shape", "paragraphs": ["Four routes over five screens."]},
            {"heading": "What follows", "paragraphs": ["One screen is entered and never left."]},
        ],
        "claims": [
            {"claim": "The lobby is the hub every route returns through.",
             "evidence_keys": ["graph.edges"], "confidence": "inferred",
             "rival": "The pass simply began there and never tried leaving another way."},
            {"claim": "The profile screen has no recorded exit.",
             "evidence_keys": ["graph.sinks", key], "confidence": "measured",
             "rival": "An exit exists and the pass never pressed it."},
        ],
        "unsupported": ["Whether the shop can be left by a tap the pass never sent."],
    }


# --- the digest -------------------------------------------------------------------------

def test_the_digest_carries_numbers_not_files(facts):
    """A model handed image paths reasons about files it cannot open, and then cites them."""
    payload = synthesize.digest(facts)
    text = json.dumps(payload)
    assert ".png" not in text
    assert "fingerprint" not in text
    assert "variants" not in text
    assert payload["graph"]["sinks"] == ["sc04"]


def test_the_digest_keeps_the_run_s_own_words(facts):
    """The screen purposes and refusal reasons are the only prose the pass produced."""
    payload = synthesize.digest(facts)
    assert payload["screens"][0]["purpose"]
    assert "irreversible" in json.dumps(payload["refusals"])


def test_the_citable_vocabulary_is_the_digest_s_own_keys(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    assert "graph" in keys and "graph.sinks" in keys
    assert "refusals.by_reason" in keys
    assert "coverage.never_activated" in keys
    assert "screens[0].purpose" not in keys        # one level only, on purpose


# --- the citation rule ------------------------------------------------------------------

def test_an_invented_key_is_rejected_and_the_real_ones_are_listed(facts):
    """The failure mode this exists to stop: prose about the game rather than about the run."""
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["claims"][0]["evidence_keys"] = ["monetisation_surface"]
    errors = synthesize.validator(keys)(answer)
    assert errors
    assert "'monetisation_surface'" in errors[0] or "monetisation_surface" in errors[0]
    assert "The citable keys are" in errors[0]
    assert "graph.sinks" in errors[0]


def test_a_claim_with_no_citation_is_told_where_to_put_it(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["claims"][0]["evidence_keys"] = []
    errors = synthesize.validator(keys)(answer)
    assert any("move to 'unsupported'" in error for error in errors)


def test_a_claim_must_name_its_rival(facts):
    """Without one, a claim is unfalsifiable and the page is an opinion with a table."""
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["claims"][1].pop("rival")
    assert any("rival" in error for error in synthesize.validator(keys)(answer))


def test_confidence_must_be_one_of_the_three(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["claims"][0]["confidence"] = "high"
    errors = synthesize.validator(keys)(answer)
    assert any("measured, inferred or speculative" in error for error in errors)


def test_an_empty_unsupported_list_is_rejected(facts):
    """That field is the most useful paragraph on the page, so it is not optional."""
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["unsupported"] = []
    assert any("'unsupported'" in error for error in synthesize.validator(keys)(answer))


def test_an_overlong_answer_is_told_to_be_shorter_not_to_be_correct(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    answer = good_answer(keys)
    answer["sections"][0]["paragraphs"] = ["x" * (synthesize.MAX_PARAGRAPH + 1)]
    errors = synthesize.validator(keys)(answer)
    assert any("over the" in error and "limit" in error for error in errors)


def test_a_valid_answer_passes(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    assert synthesize.validator(keys)(good_answer(keys)) == []


# --- rendering --------------------------------------------------------------------------

def test_confidence_is_a_column_not_a_tone(facts):
    """A speculative claim inside a paragraph gets read as a finding three months later."""
    keys = synthesize.citable(synthesize.digest(facts))
    page = synthesize.render(good_answer(keys), synthesize.PAGES[0], "recon-1")
    table = page.body.split("| Claim |")[1]
    assert "| inferred |" in table and "| measured |" in table
    assert "`graph.edges`" in table


def test_the_page_says_what_the_model_could_and_could_not_see(facts):
    keys = synthesize.citable(synthesize.digest(facts))
    page = synthesize.render(good_answer(keys), synthesize.PAGES[0], "recon-1")
    assert "No image, no client and no other source was available to it" in page.body
    assert "What the measurements could not settle" in page.body


# --- the budget and the soft failure ----------------------------------------------------

def test_exactly_three_calls_are_made_and_no_more(facts, tmp_path, monkeypatch):
    """A fixed budget, not a loop that decides it needs a fourth."""
    calls = []

    def fake(client, **kwargs):
        calls.append(kwargs["tool_name"])
        return good_answer(synthesize.citable(synthesize.digest(facts)))

    monkeypatch.setattr(engine_client, "call_tool_with_retry", fake)
    result = synthesize.run(facts, tmp_path, "recon-1", generated_by="process:cr-kit@test",
                            now=AT, client=object(), model="test-model")
    assert len(calls) == 3 == len(result.pages)
    assert calls == [spec.tool for spec in synthesize.PAGES]
    assert result.skipped == []


def test_no_credentials_costs_three_pages_not_the_run(facts, tmp_path, monkeypatch):
    """By this point the deterministic wiki is complete, and it is not worth failing over."""
    def refuse():
        raise SystemExit("ENGINE_USE_BEDROCK is set but no region is configured")

    monkeypatch.setattr(engine_client, "build_client", refuse)
    result = synthesize.run(facts, tmp_path, "recon-1", generated_by="process:cr-kit@test",
                            now=AT)
    assert result.pages == []
    assert len(result.skipped) == 1
    assert "deterministic wiki is complete without them" in result.skipped[0]
    assert not (tmp_path / "wiki").exists()


def test_one_failed_call_does_not_lose_the_other_two(facts, tmp_path, monkeypatch):
    def fake(client, **kwargs):
        if kwargs["tool_name"] == synthesize.PAGES[1].tool:
            raise RuntimeError("model gave up after 3 attempts")
        return good_answer(synthesize.citable(synthesize.digest(facts)))

    monkeypatch.setattr(engine_client, "call_tool_with_retry", fake)
    result = synthesize.run(facts, tmp_path, "recon-1", generated_by="process:cr-kit@test",
                            now=AT, client=object(), model="test-model")
    assert len(result.pages) == 2
    assert len(result.skipped) == 1
    assert synthesize.PAGES[1].rel in result.skipped[0]


def test_the_written_pages_meet_the_same_frontmatter_contract(facts, tmp_path, monkeypatch):
    """These land in the same bundle as the deterministic ones and are read by the same parser."""
    monkeypatch.setattr(engine_client, "call_tool_with_retry",
                        lambda client, **kw: good_answer(
                            synthesize.citable(synthesize.digest(facts))))
    result = synthesize.run(facts, tmp_path, "recon-1", generated_by="process:cr-kit@test",
                            now=AT, client=object(), model="test-model")
    for path in result.pages:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\ntype: Quality Concept\n")
        block = text.split("---", 2)[1]
        generated = [line for line in block.splitlines() if line.startswith("generated:")][0]
        assert generated.count(",") == 1
        assert '"' not in block.split("title: ", 1)[1].split("\n", 1)[0][1:-1]
        # LF, like the deterministic pages. A \r in a bullet spins the renderer's list loop
        # until its output array overflows - see wikibuild.write.
        assert b"\r" not in path.read_bytes()


def test_the_citable_list_is_sent_to_the_model(facts, tmp_path, monkeypatch):
    """The rule is only enforceable if the vocabulary was actually supplied."""
    seen = {}

    def fake(client, **kwargs):
        seen["message"] = kwargs["user_message"]
        return good_answer(synthesize.citable(synthesize.digest(facts)))

    monkeypatch.setattr(engine_client, "call_tool_with_retry", fake)
    synthesize.run(facts, tmp_path, "recon-1", generated_by="process:cr-kit@test", now=AT,
                   client=object(), model="test-model")
    assert "Citable keys, exactly as written" in seen["message"]
    assert "graph.sinks" in seen["message"]


def test_the_system_prompt_rules_out_outside_knowledge(facts):
    """The one thing a model knows about this target that the run did not measure."""
    assert "inadmissible" in synthesize.SYSTEM
    assert "one account on one day" in synthesize.SYSTEM
