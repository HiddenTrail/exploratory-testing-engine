"""The entry point's sequencing, with no game, no node and no child process.

`cr.py` is glue, and the interesting thing about glue is the order it does things in and what it
does when a step fails. So nothing here checks output text for its own sake. What is checked is:

- the recon command line, because it is the one place a forbidden argument could appear. No test
  can prove a battle is never fought, but `--allow-battle` never being constructed is the closest
  thing to it that a test can hold, and it is worth holding permanently.
- that a crash resumes from the dead pass's own map rather than starting over, and that the two
  cases where it must not retry both stop.
- that everything after the pass - teardown, node, synthesis - fails soft. By the time those run
  the map is on disk, and losing the wiki over a missing renderer would be absurd.

Cross-platform on purpose. `cr.main` imports `controller` for the encoding and DPI calls, so the
one test that goes through `main` installs a stub under that name, the same trick and for the
same reason as `test_preflight.py`.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cr  # noqa: E402
from engine import client as engine_client  # noqa: E402


class Ran:
    """A stand-in for `subprocess.run` that records commands and hands back a code."""

    def __init__(self, codes: list[int]):
        self.codes, self.commands = codes, []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        code = self.codes[min(len(self.commands) - 1, len(self.codes) - 1)]
        return subprocess.CompletedProcess(command, code, stdout="", stderr="")


# --- the recon command line -------------------------------------------------------------

def test_the_command_never_allows_a_battle(tmp_path, monkeypatch):
    """The one argument this kit must never construct.

    Training Camp is the only authorised battle on this account and even that needs a person to
    ask for it; the ladder Battle button is a live match against a stranger with trophies at
    stake. `battle.py` refuses without the flag, so not passing it is the whole guard.
    """
    ran = Ran([0])
    monkeypatch.setattr(cr.subprocess, "run", ran)
    cr.recon(tmp_path / "recon-1", 5.0, 0.93, None)
    flat = " ".join(ran.commands[0])
    assert "--allow-battle" not in flat
    assert "battle.py" not in flat


def test_the_derived_threshold_is_passed_to_the_pass(tmp_path, monkeypatch):
    """Otherwise preflight measured this session's drift for nothing."""
    ran = Ran([0])
    monkeypatch.setattr(cr.subprocess, "run", ran)
    cr.recon(tmp_path / "recon-1", 7.5, 0.912, None)
    command = ran.commands[0]
    assert command[command.index("--screen-match") + 1] == "0.912"
    assert command[command.index("--minutes") + 1] == "7.5"
    assert command[command.index("--game") + 1] == cr.GAME
    assert "--resume" not in command


# --- retrying ---------------------------------------------------------------------------

def _explore(tmp_path, monkeypatch, codes, maps):
    """Run `explore` with a fake pass that exits with `codes` and writes maps per `maps`."""
    ran = Ran(codes)
    calls = []

    def fake(command, **kwargs):
        result = ran(command, **kwargs)
        run_dir = Path(command[command.index("--out") + 1])
        run_dir.mkdir(parents=True, exist_ok=True)
        if maps[min(len(ran.commands) - 1, len(maps) - 1)]:
            run_dir.joinpath("ontology.json").write_text("{}", encoding="utf-8")
        calls.append(command)
        return result

    monkeypatch.setattr(cr.subprocess, "run", fake)
    return cr.explore(tmp_path, 1.0, 0.93, 1), ran.commands


def test_a_clean_pass_runs_once(tmp_path, monkeypatch):
    run_dir, commands = _explore(tmp_path, monkeypatch, [0], [True])
    assert len(commands) == 1
    assert run_dir == tmp_path / "recon-1"


def test_a_crashed_pass_is_resumed_from_its_own_map(tmp_path, monkeypatch):
    """A fresh pass would spend the remaining budget re-finding what the dead one found."""
    run_dir, commands = _explore(tmp_path, monkeypatch, [1, 0], [True, True])
    assert len(commands) == 2
    assert commands[1][commands[1].index("--resume") + 1] == str(tmp_path / "recon-1")
    assert run_dir == tmp_path / "recon-2"


def test_a_pass_that_wrote_nothing_is_not_retried(tmp_path, monkeypatch):
    """There is nothing to resume from, and the usual cause needs a person, not a retry."""
    run_dir, commands = _explore(tmp_path, monkeypatch, [1], [False])
    assert len(commands) == 1
    assert run_dir is None


def test_the_retry_limit_stops_the_loop(tmp_path, monkeypatch):
    """And the last map is still returned, because a partial map builds a wiki."""
    run_dir, commands = _explore(tmp_path, monkeypatch, [1, 1], [True, True])
    assert len(commands) == 2
    assert run_dir == tmp_path / "recon-2"


def test_a_pass_that_exits_zero_without_a_map_is_not_taken_at_its_word(tmp_path, monkeypatch):
    """`run_recon.py` swallows KeyboardInterrupt, so a clean exit code is not proof of a map."""
    run_dir, _ = _explore(tmp_path, monkeypatch, [0], [False])
    assert run_dir is None


# --- the model the vetting layer needs --------------------------------------------------

class FakeMessages:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return object()


def _client(monkeypatch, error=None, missing=None):
    messages = FakeMessages(error)
    client = types.SimpleNamespace(messages=messages)

    def build():
        if missing:
            raise missing
        return client

    monkeypatch.setattr(engine_client, "build_client", build)
    return messages


def test_the_model_is_checked_with_one_token(monkeypatch):
    """Construction proves a region is set. Only a call proves the SSO token is still valid."""
    messages = _client(monkeypatch)
    said = cr.check_model()
    assert len(messages.calls) == 1
    assert messages.calls[0]["max_tokens"] == 1
    assert "vetting layer is live" in said


def test_an_expired_token_is_refused_not_warned(monkeypatch):
    """Without that call the pass runs on the denylist alone, which is one guard, not two."""
    _client(monkeypatch, error=RuntimeError("ExpiredTokenException"))
    with pytest.raises(cr.checks.Refuse) as refused:
        cr.check_model()
    message = str(refused.value)
    assert "aws sso login" in message
    assert "safety layers" in message
    assert "Nothing was tapped." in message


def test_missing_credentials_are_a_refusal_not_a_crash(monkeypatch):
    """`build_client` raises SystemExit, which sails straight past `except Exception`."""
    _client(monkeypatch, missing=SystemExit("no region is configured"))
    with pytest.raises(cr.checks.Refuse) as refused:
        cr.check_model()
    assert "no region is configured" in str(refused.value)


# --- everything after the pass fails soft -----------------------------------------------

def test_a_failed_teardown_is_a_sentence_not_an_exception(monkeypatch):
    """The map is already on disk by now. Losing the wiki over the way home would be absurd."""
    attach_mod = types.ModuleType("attach")

    def refuse(game, verbose=True):
        raise RuntimeError("the window went away")

    attach_mod.attach = refuse
    attach_mod.apply_calibration = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "attach", attach_mod)

    said = cr.teardown(cr.GAME)
    assert "teardown FAILED" in said
    assert "by hand" in said


def test_no_node_means_no_html_and_no_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    notes = cr.render(tmp_path)
    assert len(notes) == 1
    assert "complete and readable" in notes[0]
    assert "--wiki-only" in notes[0]


def test_the_index_is_rebuilt_before_the_html_is_rendered(tmp_path, monkeypatch):
    """The renderer walks the bundle; an index written after it is an index nobody rendered."""
    ran = Ran([0, 0])
    monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(cr.subprocess, "run", ran)
    cr.render(tmp_path)
    assert [Path(command[1]).name for command in ran.commands] == \
        ["rebuild-index.mjs", "render-html.mjs"]
    assert all(command[command.index("--dir") + 1] == str(tmp_path) for command in ran.commands)


# --- what the build actor looks like ----------------------------------------------------

def test_the_build_actor_carries_no_comma(monkeypatch):
    """A comma in it truncates the timestamp beside it when the renderer unpacks frontmatter."""
    assert "," not in cr._version()
    monkeypatch.setattr(cr.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert cr._version() == "process:cr-kit@unknown"


# --- the one path that must not touch the game ------------------------------------------

def test_wiki_only_skips_the_client_entirely(tmp_path, monkeypatch):
    """Its whole purpose: rebuild from files after installing node, or after a builder edit."""
    controller_mod = types.ModuleType("controller")
    controller_mod.readable_output = lambda: None
    controller_mod.set_dpi_aware = lambda: None
    monkeypatch.setitem(sys.modules, "controller", controller_mod)

    def forbidden(*args, **kwargs):
        raise AssertionError("--wiki-only touched the game")

    monkeypatch.setattr(cr, "explore", forbidden)
    monkeypatch.setattr(cr, "teardown", forbidden)
    built = []
    monkeypatch.setattr(cr, "build_wiki", lambda *a: built.append(a))

    run_dir = tmp_path / "recon-1"
    run_dir.mkdir()
    (tmp_path / "preflight.json").write_text('{"wiki_note": "measured here"}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["cr.py", "--wiki-only", str(run_dir)])

    assert cr.main() == 0
    assert built and built[0][0] == tmp_path and built[0][1] == run_dir
    assert built[0][2] == "measured here"


def test_a_refusal_exits_nonzero_without_running_a_pass(tmp_path, monkeypatch):
    """The doctor's verdict has to be visible to a shell script, not only to a reader."""
    controller_mod = types.ModuleType("controller")
    controller_mod.readable_output = lambda: None
    controller_mod.set_dpi_aware = lambda: None
    monkeypatch.setitem(sys.modules, "controller", controller_mod)

    preflight_mod = types.ModuleType("preflight")
    preflight_mod.DRIFT_SAMPLES = 6

    def refuse(game, samples=6):
        raise cr.checks.Refuse("the client is on the shop screen. Nothing was tapped.")

    preflight_mod.run = refuse
    monkeypatch.setitem(sys.modules, "preflight", preflight_mod)
    monkeypatch.setattr(cr, "explore", lambda *a: pytest.fail("a refusal still ran a pass"))
    monkeypatch.setattr(sys, "argv", ["cr.py", "--minutes", "1"])

    assert cr.main() == 2
