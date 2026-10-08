"""Restart a local test target and log in fresh, before an experiment's run (#372).

The local Juice Shop keeps baskets, reviews and users from earlier runs, and after a
restart it forgets the logins it handed out, so an old session file is refused by parts
of it (#360). Runs compared in an experiment should each start from the same, fresh
target:

    python -m trailhound.adapters.web_gui.fresh_target --container test-targets-juice-shop-1 \
        --url http://127.0.0.1:3000 --recipe test-targets/login-recipes/juice-shop.json --product juice-shop

It only restarts a container labelled trailhound.sandbox=true (test-targets/docker-compose.yml
puts it on every local target), and the login recipe only runs against this machine.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request

SANDBOX_LABEL = "trailhound.sandbox"


def is_sandbox(labels: dict | None) -> bool:
    return (labels or {}).get(SANDBOX_LABEL) == "true"


def container_labels(container: str, run=subprocess.run) -> dict:
    """The container's labels. SystemExit if docker doesn't know it."""
    done = run(["docker", "inspect", "--type", "container", container, "--format", "{{json .Config.Labels}}"],
               capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"docker doesn't know a container called {container!r}: {done.stderr.strip()[:200]}")
    return json.loads(done.stdout or "null") or {}


def restart(container: str, run=subprocess.run) -> None:
    """Restart the container, but only a throwaway test target."""
    labels = container_labels(container, run)
    if not is_sandbox(labels):
        # Made before the rename (#335), a target has the old label: say how to remake it.
        old = (" It has the label from before the rename to Trailhound (qes.sandbox); remake it with "
               "docker compose -f test-targets/docker-compose.yml up -d" if labels.get("qes.sandbox") == "true" else "")
        raise SystemExit(f"{container} isn't labelled {SANDBOX_LABEL}=true, so it isn't restarted: only the local "
                         f"test targets in test-targets/docker-compose.yml are.{old}")
    done = run(["docker", "restart", container], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"docker couldn't restart {container}: {done.stderr.strip()[:200]}")


def wait_until_up(url: str, timeout_s: float = 120, open_url=urllib.request.urlopen, sleep=time.sleep) -> float:
    """Seconds until `url` answers 200. SystemExit if it doesn't within timeout_s."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            with open_url(url, timeout=5) as response:
                if response.status == 200:
                    return time.monotonic() - start
        except Exception:
            pass
        sleep(2)
    raise SystemExit(f"{url} didn't answer within {timeout_s:.0f} s of the restart.")


def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Restart a local test target and log in fresh from its recipe.")
    ap.add_argument("--container", required=True, help="e.g. test-targets-juice-shop-1")
    ap.add_argument("--url", required=True, help="the target's base URL, e.g. http://127.0.0.1:3000")
    ap.add_argument("--recipe", help="the login recipe; left out, no login")
    ap.add_argument("--product", help="product slug for the session file, e.g. juice-shop")
    ap.add_argument("--name", default="logged-in", help="session name (default logged-in)")
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait for the target (default 120)")
    args = ap.parse_args(argv)
    if args.recipe and not args.product:
        ap.error("--recipe needs --product, for where the session is saved")

    restart(args.container)
    print(f"Restarted {args.container}; {args.url} answered after {wait_until_up(args.url, args.timeout):.0f} s.")
    if args.recipe:
        from trailhound.adapters.web_gui.login_recipe import log_in, session_path
        out = session_path(args.product, args.name)
        log_in(args.recipe, args.url, out)
        print(f"Logged in fresh from {args.recipe}, saved as '{args.name}'.")


if __name__ == "__main__":
    main()
