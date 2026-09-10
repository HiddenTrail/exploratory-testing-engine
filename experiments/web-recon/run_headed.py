"""A visible (headed) run of the Stage 0 core against a live app.

Opens a real browser window you can watch, drives a couple of actions, and prints what
the deterministic core makes of each frame: the state signature, the controls it found,
and any functional findings the oracles produced. No model, nothing mutating.

    ../../.venv/Scripts/python run_headed.py [url]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright

from identity import control_keys, same_state, signature
from oracles import run_observation_oracles
from perceive import Collector, capture

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/"


def show(label, obs, state_id, seq):
    print(f"\n=== {label} ===")
    print(f"  url:       {obs.url}")
    print(f"  title:     {obs.title!r}")
    print(f"  signature: {signature(obs)}")
    print(f"  controls:  {control_keys(obs)}")
    findings = run_observation_oracles(obs, state_id, seq)
    if findings:
        for f in findings:
            print(f"  FINDING [{f.kind}]: {f.summary}")
    else:
        print("  findings:  (none)")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=700)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        col = Collector().attach(page)

        print(f"Navigating (headed) to {URL} ...")
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)  # let data load / fail
        first = capture(page, col)
        show("initial view", first, "s1", 0)

        # Two visible map interactions - should stay the SAME state (no over-split).
        for i in (1, 2):
            try:
                page.get_by_role("button", name="Zoom in").first.click(timeout=2000)
                page.wait_for_timeout(1200)
            except Exception as e:
                print(f"  (zoom {i} skipped: {e})")
        after = capture(page, col)
        show("after zooming in twice", after, "s1", 2)

        print(f"\nsame state after zoom? {same_state(first, after)}  "
              f"(expected True - a map pan/zoom is one view, not a new one)")

        page.wait_for_timeout(3000)  # a moment to watch before it closes
        browser.close()


if __name__ == "__main__":
    main()
