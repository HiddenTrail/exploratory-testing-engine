"""A fresh target before each run of an experiment (issue #372). Stubbed docker, no network."""

import json
import subprocess

import pytest

from trailhound.adapters.web_gui import fresh_target


class _Docker:
    def __init__(self, labels, fail=()):
        self.labels, self.fail, self.calls = labels, fail, []

    def __call__(self, args, **kw):
        self.calls.append(args[:2])
        if args[1] in self.fail:
            return subprocess.CompletedProcess(args, 1, "", "No such object")
        out = json.dumps(self.labels) if args[1] == "inspect" else ""
        return subprocess.CompletedProcess(args, 0, out, "")


def test_only_a_sandbox_target_is_restarted():
    docker = _Docker({"trailhound.sandbox": "true"})
    fresh_target.restart("test-targets-juice-shop-1", run=docker)
    assert docker.calls == [["docker", "inspect"], ["docker", "restart"]]
    docker = _Docker({"com.docker.compose.project": "something-else"})
    with pytest.raises(SystemExit, match="isn't labelled trailhound.sandbox=true"):
        fresh_target.restart("my-database", run=docker)
    assert docker.calls == [["docker", "inspect"]]                     # never restarted
    with pytest.raises(SystemExit, match="label from before the rename to Trailhound"):
        fresh_target.restart("test-targets-juice-shop-1", run=_Docker({"qes.sandbox": "true"}))
    with pytest.raises(SystemExit, match="doesn't know a container"):
        fresh_target.restart("ghost", run=_Docker({}, fail=("inspect",)))


def test_it_waits_until_the_target_answers():
    answers = iter([OSError("refused"), type("R", (), {"status": 503, "__enter__": lambda s: s, "__exit__": lambda *a: None})(),
                    type("R", (), {"status": 200, "__enter__": lambda s: s, "__exit__": lambda *a: None})()])

    def open_url(url, timeout):
        item = next(answers)
        if isinstance(item, Exception):
            raise item
        return item
    assert fresh_target.wait_until_up("http://127.0.0.1:3000", open_url=open_url, sleep=lambda s: None) >= 0
    with pytest.raises(SystemExit, match="didn't answer within"):
        fresh_target.wait_until_up("http://x", timeout_s=0, open_url=open_url, sleep=lambda s: None)
