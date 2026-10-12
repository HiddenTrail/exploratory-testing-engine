"""An adapter's result can't overwrite the fields the engine writes beside it (issue #411).
A test's casting-log entry is the engine's fields plus the adapter's result, and a bug's
replay record is the same. A clash was silent: the result's value won, so a 'cast_test'
in a result would make the bug replays run a different test. No model calls."""

import dataclasses
import itertools

import httpx
import pytest

import trailhound.loop as loop
import trailhound.runner as runner
from trailhound.adapter import RESERVED_RESULT_KEYS, with_result
from trailhound.config import RunConfig
from trailhound.tests import test_runner_persistence as persistence
from trailhound.tests.test_verify import _adapter, _bug, _log
from trailhound.verify import replay_bugs


def test_a_result_joins_the_engines_fields_when_nothing_clashes():
    assert with_result({"checkpoint": 1}, {"test_number": 3, "outcome": {}}) == {
        "checkpoint": 1, "test_number": 3, "outcome": {}}


def test_a_result_that_uses_an_engine_field_is_refused():
    with pytest.raises(RuntimeError, match="'cast_test', 'checkpoint'.*rename"):
        with_result({"checkpoint": 1, "cast_test": {}}, {"test_number": 3, "checkpoint": 9, "cast_test": "x"})


def test_the_reserved_keys_are_the_casting_log_fields_the_engine_writes():
    assert {"checkpoint", "round", "round_reasoning", "linked_hypothesis", "oracle_claim_id",
            "follows_up", "rules_out_if", "cast_test", "replay_of", "for"} == RESERVED_RESULT_KEYS


def test_a_run_whose_adapter_returns_an_engine_field_stops_and_says_which(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: httpx.Response(200))
    monkeypatch.setattr(runner, "get_happy_day_example", lambda adapter: {"request": {}, "response": {}})
    monkeypatch.setattr(runner, "build_client", lambda: object())
    monkeypatch.setattr(loop, "get_casting_round", persistence._fake_casting_round)
    monkeypatch.setattr(loop, "get_checkpoint_hypothesis", persistence._fake_hypothesis)
    adapter = dataclasses.replace(persistence._FAKE_ADAPTER,
                                  execute_test=lambda test, n: {"test_number": n, "cast_test": "another test"})
    output = runner.run(adapter, RunConfig(max_checkpoints=1, out_dir=tmp_path))
    assert output["stopped_reason"] == "error" and "'cast_test'" in output["error"]


def test_a_replay_result_that_uses_an_engine_field_is_refused():
    adapter = dataclasses.replace(_adapter([]), execute_test=lambda test, n: {"test_number": n, "value": "500",
                                                                             "for": "someone else"})
    with pytest.raises(RuntimeError, match="'for'"):
        replay_bugs(adapter, [_bug([1])], _log("500"), itertools.count(2))
