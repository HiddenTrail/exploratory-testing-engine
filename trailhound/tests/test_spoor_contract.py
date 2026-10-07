"""The contract with Spoor's saved map format (issue #144): run a real Spoor on a tiny
static site and check its map against what trailhound/adapters/web_gui/from_spoor.py reads.

Spoor is optional, so this is skipped unless its CLI is available: on PATH (CI's
spoor-contract job installs the version pinned in trailhound/requirements-spoor.txt), or
named by SPOOR_CLI, e.g. Spoor's own virtualenv on a dev machine:

    SPOOR_CLI=../ht-spoor/.venv/Scripts/spoor python -m pytest trailhound/tests/test_spoor_contract.py

It talks to Spoor only through the CLI and the saved map, never its Python modules.
"""

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SITE = Path(__file__).parent / "fixtures" / "spoor_contract_site"
SPOOR = os.environ.get("SPOOR_CLI") or shutil.which("spoor")

# CI sets REQUIRE_SPOOR, so a Spoor that failed to install fails the job instead of
# skipping it into a green tick.
pytestmark = pytest.mark.skipif(not SPOOR and not os.environ.get("REQUIRE_SPOOR"),
                                reason="Spoor's CLI isn't installed (see trailhound/requirements-spoor.txt)")


@pytest.fixture(scope="module")
def site_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _explore(site_url, work, *extra):
    """Run Spoor in its own folder, so each map gets its own .spoor-cache (a logged-in
    map must not overwrite the logged-out one), and return the saved map's path."""
    assert SPOOR, "REQUIRE_SPOOR is set but Spoor's CLI isn't on PATH or in SPOOR_CLI"
    done = subprocess.run([SPOOR, "explore", site_url, "--max-states", "6", "--max-seconds", "120", *extra],
                          cwd=work, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    maps = list((work / ".spoor-cache" / "maps").glob("*.json"))
    assert len(maps) == 1, f"expected one saved map, found {maps}"
    return maps[0]


@pytest.fixture(scope="module")
def spoor_map(site_url, tmp_path_factory):
    return json.loads(_explore(site_url, tmp_path_factory.mktemp("spoor")).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def session_file(site_url, tmp_path_factory):
    """A saved session in our format (#155, #228): the contract site shows its account
    link only when localStorage has contract_session=1. The sessionStorage entry is ours;
    Spoor has to accept a file that carries it."""
    path = tmp_path_factory.mktemp("session") / "logged-in.json"
    path.write_text(json.dumps({"cookies": [], "origins": [{
        "origin": site_url, "localStorage": [{"name": "contract_session", "value": "1"}],
        "sessionStorage": [{"name": "tab", "value": "1"}]}]}), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def session_map_path(site_url, session_file, tmp_path_factory):
    return _explore(site_url, tmp_path_factory.mktemp("spoor-session"), "--session", str(session_file))


def _exploration(site_url, saved_map):
    return (saved_map.get(site_url) or saved_map.get(site_url + "/"))["exploration"]


def _action_names(exploration):
    return {a["name"] for s in exploration["states"] for a in s["actions"]}


def test_the_map_is_keyed_by_the_explored_url_and_has_an_exploration(site_url, spoor_map):
    entry = spoor_map.get(site_url) or spoor_map.get(site_url + "/")
    assert entry, f"no entry for {site_url}; keys: {list(spoor_map)}"
    assert isinstance(entry.get("exploration"), dict)


def test_the_exploration_is_in_the_format_from_spoor_reads(site_url, spoor_map):
    from trailhound.adapters.web_gui.from_spoor import map_errors

    exploration = _exploration(site_url, spoor_map)
    assert map_errors(exploration) == []
    # The toggle and the link each lead somewhere new, so a working Spoor maps more
    # than the start page. If this drops to one, the format may be fine but the
    # check is no longer testing anything.
    assert len(exploration["states"]) >= 2
    assert any(t["from"] != t["to"] for t in exploration["transitions"])


# ---- mapping from a saved session (issue #156) ----------------------------------------------

def test_a_saved_session_reaches_what_a_logged_out_map_cant(site_url, spoor_map, session_map_path):
    from trailhound.adapters.web_gui.from_spoor import map_errors

    logged_out = _exploration(site_url, spoor_map)
    logged_in = _exploration(site_url, json.loads(session_map_path.read_text(encoding="utf-8")))
    assert "Your account" not in _action_names(logged_out)
    assert "Your account" in _action_names(logged_in)
    assert len(logged_in["states"]) > len(logged_out["states"])
    assert map_errors(logged_in) == []


def test_from_spoor_converts_a_session_map_and_records_the_session(site_url, session_file, session_map_path, tmp_path):
    out = tmp_path / "converted.json"
    done = subprocess.run([sys.executable, "-m", "trailhound.adapters.web_gui.from_spoor", "--map", str(session_map_path),
                           "--url", site_url, "--session", str(session_file), "--out", str(out)],
                          cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    converted = json.loads(out.read_text(encoding="utf-8"))
    # The converter replays every path live from the same session, so the account page
    # only survives if our harness restores the session the way Spoor did.
    assert any(s["url"].endswith("/account.html") for s in converted["states"])
    assert converted["session"]["session_name"] == "logged-in"
