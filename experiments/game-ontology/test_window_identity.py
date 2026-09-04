"""Which window counts as the game - the check that decides where input goes.

The failure these cover is not a wrong map or a wasted pass: it is a drag sent into
somebody's text editor. It happened. `Controller._belongs` has four relations, and the
last one compares *titles*, reachable only when no exe resolves. A Google Play Games
title has no exe by construction (`experiments/android-bot/attach.py`), so for that
target the title is permanently the only evidence - and a Play Games window's title is
the game's bare name, which is also in the title of every editor tab and browser tab
naming a file about the game. A VS Code window showing `clash-royale-wiki.html` was
adopted as a usurping Clash Royale window on exactly that line.

`Target.owner_image` is the answer: the target names the process that draws it, and that
outranks any title resemblance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import controller as ctl
from controller import Controller, Target

EMULATOR = "crosvm.exe"
INSTALL = r"C:\Program Files\Google\Play Games"
GAME_EXE = Path(INSTALL) / "current" / "emulator" / EMULATOR
EDITOR_EXE = Path(r"C:\Users\someone\AppData\Local\Programs\Microsoft VS Code\Code.exe")
CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
IMPOSTOR_EXE = Path(r"C:\Users\someone\Downloads\crosvm.exe")

# The titles as they really appeared on the machine this was written on.
GAME_TITLE = "Clash Royale - PekkaMarjamaki"
EDITOR_TITLE = ("android-bot — wiki (/c%3A/Users/pmarj/qes-exploration/experiments/"
                "android-bot/clash-royale-wiki.html) - qes-exploration - Visual Studio Code")
CHROME_TITLE = "Clash Royale – Google Play ‑sovellukset - Google Chrome"

_IMAGES = {101: GAME_EXE, 202: EDITOR_EXE, 303: CHROME_EXE, 404: IMPOSTOR_EXE, 505: None}


@pytest.fixture
def images(monkeypatch):
    """Process images by pid, so no real process has to exist. 505 is unreadable."""
    monkeypatch.setattr(ctl, "process_image", lambda pid: _IMAGES.get(pid))


def play_games_target() -> Target:
    """The android-bot target: an owning process named, and no exe, on purpose."""
    return Target(name="Clash Royale", window_title=GAME_TITLE, exe="",
                  owner_image=(EMULATOR, INSTALL))


# -- Target.disowns -------------------------------------------------------------


def test_the_emulator_is_not_disowned(images):
    assert play_games_target().disowns(101) == ""


def test_an_editor_is_disowned_however_its_window_is_titled(images):
    assert "Code.exe" in play_games_target().disowns(202)


def test_a_browser_is_disowned(images):
    assert "chrome.exe" in play_games_target().disowns(303)


def test_the_folder_is_checked_not_just_the_file_name(images):
    """A `crosvm.exe` in Downloads is not the Play Games emulator. Both halves of the
    check matter; the file name alone matches any copy anywhere on the machine."""
    reason = play_games_target().disowns(404)
    assert reason and INSTALL in reason


def test_an_unreadable_process_is_disowned(images):
    """Fails closed. A window whose owner cannot be established is not one to send
    input to, and the cost of being wrong the other way is only a refused handover."""
    assert play_games_target().disowns(505) == "its process image cannot be read"


def test_a_missing_pid_is_disowned(images):
    assert play_games_target().disowns(None) != ""


def test_a_target_without_the_constraint_disowns_nothing(images):
    """Every other target in the repo resolves an exe and relies on that instead, so an
    unset `owner_image` has to stay a no-op rather than start rejecting windows."""
    plain = Target(name="Clash Royale", window_title=GAME_TITLE, exe="")
    assert all(plain.disowns(pid) == "" for pid in _IMAGES)


# -- Controller._belongs --------------------------------------------------------


def test_belongs_refuses_the_editor_that_names_the_game(images):
    """The regression. Without `owner_image` this returned "its title ... is the name of
    the game", which is enough to be adopted and then driven."""
    session = Controller(play_games_target(), verbose=False)
    session.hwnd, session.pid = 5444950, 101
    assert session._belongs(202, EDITOR_TITLE) == ""


def test_belongs_still_accepts_the_window_being_driven(images):
    session = Controller(play_games_target(), verbose=False)
    session.hwnd, session.pid = 5444950, 101
    assert session._belongs(101, GAME_TITLE) == "the same process"


def test_the_near_miss_is_reported_once_per_process(images, capsys):
    """Reported because a silently-declined window is the one a person needs told about,
    once because `_belongs` runs for every visible window on every readiness check."""
    session = Controller(play_games_target(), verbose=True)
    session.hwnd, session.pid = 5444950, 101
    for _ in range(3):
        session._belongs(202, EDITOR_TITLE)
    said = capsys.readouterr().out
    assert said.count("even though its title names the game") == 1
    assert "Code.exe" in said


def test_an_unrelated_window_is_refused_without_a_note(images, capsys):
    """Only a title that names the game is a near miss worth printing; the rest of the
    desktop is not, or the note becomes noise nobody reads."""
    session = Controller(play_games_target(), verbose=True)
    session.hwnd, session.pid = 5444950, 101
    assert session._belongs(202, "Untitled - Notepad") == ""
    assert "even though its title names the game" not in capsys.readouterr().out
