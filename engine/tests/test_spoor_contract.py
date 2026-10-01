"""The contract with Spoor's saved map format (issue #144): run a real Spoor on a tiny
static site and check its map against what engine/adapters/web_gui/from_spoor.py reads.

Spoor is optional, so this is skipped unless its CLI is available: on PATH (CI's
spoor-contract job installs the version pinned in engine/requirements-spoor.txt), or
named by SPOOR_CLI, e.g. Spoor's own virtualenv on a dev machine:

    SPOOR_CLI=../ht-spoor/.venv/Scripts/spoor python -m pytest engine/tests/test_spoor_contract.py

It talks to Spoor only through the CLI and the saved map, never its Python modules.
"""

import functools
import http.server
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

SITE = Path(__file__).parent / "fixtures" / "spoor_contract_site"
SPOOR = os.environ.get("SPOOR_CLI") or shutil.which("spoor")

# CI sets REQUIRE_SPOOR, so a Spoor that failed to install fails the job instead of
# skipping it into a green tick.
pytestmark = pytest.mark.skipif(not SPOOR and not os.environ.get("REQUIRE_SPOOR"),
                                reason="Spoor's CLI isn't installed (see engine/requirements-spoor.txt)")


@pytest.fixture(scope="module")
def site_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def spoor_map(site_url, tmp_path_factory):
    assert SPOOR, "REQUIRE_SPOOR is set but Spoor's CLI isn't on PATH or in SPOOR_CLI"
    work = tmp_path_factory.mktemp("spoor")
    done = subprocess.run([SPOOR, "explore", site_url, "--max-states", "6", "--max-seconds", "120"],
                          cwd=work, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    maps = list((work / ".spoor-cache" / "maps").glob("*.json"))
    assert len(maps) == 1, f"expected one saved map, found {maps}"
    return json.loads(maps[0].read_text(encoding="utf-8"))


def test_the_map_is_keyed_by_the_explored_url_and_has_an_exploration(site_url, spoor_map):
    entry = spoor_map.get(site_url) or spoor_map.get(site_url + "/")
    assert entry, f"no entry for {site_url}; keys: {list(spoor_map)}"
    assert isinstance(entry.get("exploration"), dict)


def test_the_exploration_is_in_the_format_from_spoor_reads(site_url, spoor_map):
    from engine.adapters.web_gui.from_spoor import map_errors

    exploration = (spoor_map.get(site_url) or spoor_map.get(site_url + "/"))["exploration"]
    assert map_errors(exploration) == []
    # The toggle and the link each lead somewhere new, so a working Spoor maps more
    # than the start page. If this drops to one, the format may be fine but the
    # check is no longer testing anything.
    assert len(exploration["states"]) >= 2
    assert any(t["from"] != t["to"] for t in exploration["transitions"])
