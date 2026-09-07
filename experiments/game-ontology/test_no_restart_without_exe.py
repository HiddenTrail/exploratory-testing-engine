"""A game this harness cannot launch is a game it must never close.

`Controller._restart` closes the game and then launches it again. The closing half works
for every target; the launching half needs an executable, and a Google Play Games title
does not have one - `Target.exe` is empty by construction, because a Play Games shortcut
has a blank TargetPath and the client cannot be started from a path at all
(`experiments/android-bot/attach.py`).

So on that target the two halves are not symmetrical, and `_restart` used to run them in
the order that loses: `close()` posts WM_CLOSE to the game and taskkills its pid if that
does not take, and only afterwards does `_launch` raise `cannot find an executable`. The
window went funny, which is recoverable; the game ended up shut with nothing able to
reopen it, which is not.

Observed 2026-09-07. A liveness check - the one script whose entire job is to look without
touching - sampled a Play Games window that was hidden rather than foreground. The
verified grab inside it called `ensure_readable`, which called `_restart`, which closed
the client it had been asked to check on. These cover both ends of that: `_restart`
refusing before it touches anything, and an observing grab not starting the chain.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import controller as ctl
from controller import Controller, Target, WindowLost

EMULATOR = "crosvm.exe"
INSTALL = r"C:\Program Files\Google\Play Games"


def unlaunchable() -> Target:
    """The android-bot target: an owning process named, and no exe, on purpose."""
    return Target(name="Clash Royale", window_title="Clash Royale", exe="",
                  owner_image=(EMULATOR, INSTALL))


def launchable(tmp_path: Path) -> Target:
    """An ordinary target, whose exe exists - the case that must still relaunch."""
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"")
    return Target(name="Tile Tale", window_title="Tile Tale", exe=str(exe))


@pytest.fixture
def watched(monkeypatch):
    """Record every destructive step instead of performing it."""
    done: list[str] = []
    monkeypatch.setattr(Controller, "close", lambda self: done.append("close") or "closed")
    monkeypatch.setattr(Controller, "_launch", lambda self: done.append("launch"))
    monkeypatch.setattr(Controller, "focus", lambda self: True)
    monkeypatch.setattr(Controller, "_wait_settled", lambda self: 0.0)
    monkeypatch.setattr(ctl.time, "sleep", lambda _seconds: None)
    return done


# -- _restart on a target with no executable -----------------------------------


def test_restart_refuses_when_there_is_no_executable(watched):
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    with pytest.raises(WindowLost):
        session._restart("window is gone")


def test_it_closes_nothing_on_the_way_out(watched):
    """The point of the whole change. Refusing loudly but after `close()` is no better
    than not refusing: the game is shut either way."""
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    with pytest.raises(WindowLost):
        session._restart("window would not come to the foreground")
    assert watched == []


def test_the_refusal_says_what_to_do_about_it(watched):
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    with pytest.raises(WindowLost) as raised:
        session._restart("window is gone")
    said = str(raised.value)
    assert "window is gone" in said, "the original symptom is the useful half"
    assert "cannot be relaunched" in said
    assert "open the game yourself" in said


def test_a_refused_restart_is_not_counted_as_one(watched):
    """`restarts` is reported as coverage. A restart that did not happen must not
    appear there, or the report claims the session recovered from something."""
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    with pytest.raises(WindowLost):
        session._restart("window is gone")
    assert session.restarts == 0


# -- the ordinary target still restarts ----------------------------------------


def test_a_launchable_target_still_closes_and_relaunches(watched, tmp_path):
    """The guard must be about launchability, not a blanket ban on restarting."""
    session = Controller(launchable(tmp_path), verbose=False)
    session.hwnd = 4242
    assert session._restart("window is gone") == "restarted"
    assert watched == ["close", "launch"]
    assert session.restarts == 1


# -- ensure_readable must not reach the closing path either --------------------


def test_a_dead_window_raises_rather_than_closing(watched, monkeypatch):
    """`ensure_readable` funnels three separate failures into `_restart`. With no exe,
    all three have to come out as an exception and leave the game running."""
    monkeypatch.setattr(ctl, "window_alive", lambda hwnd: False)
    monkeypatch.setattr(Controller, "successor_window", lambda self: None)
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    with pytest.raises(WindowLost):
        session.ensure_readable()
    assert watched == []


# -- watching is not driving ---------------------------------------------------


def test_an_unverified_grab_never_escalates(monkeypatch):
    """`grab(verify=False)` is what an observer uses, and it must not consult
    `ensure_readable` at all - that is the call which can end in a close."""
    escalated: list[str] = []
    monkeypatch.setattr(Controller, "ensure_readable",
                        lambda self, allow_restart=True: escalated.append("escalated"))
    monkeypatch.setattr(ctl, "is_foreground", lambda hwnd: False)
    monkeypatch.setattr(ctl, "grab_thumbnail",
                        lambda *args: bytes(4 * args[-2] * args[-1]))
    session = Controller(unlaunchable(), verbose=False)
    session.hwnd = 3214162
    session._last_good = (0, 0, 400, 800)

    session.grab(8, 8, verify=False)
    assert escalated == []

    # And the same call with verification on does escalate, so the test above is not
    # passing because the escalation is unreachable for some other reason.
    session.grab(8, 8, verify=True)
    assert escalated == ["escalated"]


def test_fingerprint_can_watch_without_verifying(monkeypatch):
    """The flag has to reach `grab`, because that is the only place it does anything."""
    import recon

    seen: list[bool] = []
    monkeypatch.setattr(Controller, "grab",
                        lambda self, cols, rows, region=None, verify=True:
                        seen.append(verify) or bytes(4 * cols * rows))
    session = Controller(unlaunchable(), verbose=False)

    recon.fingerprint(session, verify=False)
    recon.fingerprint(session)
    assert seen == [False, True]
