"""Record the multi-page PoC's views as fixtures - the multi-view corpus Stage 0's
degenerate EcoEstate couldn't provide. Walks question -> Yes -> Back -> No so identity
can be tested on genuinely distinct views and on a return-to-a-known-state.

    ../../.venv/Scripts/python capture_poc.py [url]   (default http://localhost:5174/)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright

from identity import signature
from perceive import Collector, capture

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5174/"
FIX = Path(__file__).parent / "fixtures"


def main():
    FIX.mkdir(exist_ok=True)
    saved = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 768})
        col = Collector().attach(page)

        page.goto(URL, wait_until="networkidle")

        def grab(name):
            page.wait_for_timeout(400)
            obs = capture(page, col)
            obs.save(FIX / f"{name}.json")
            saved[name] = signature(obs)

        grab("poc-question")
        page.get_by_role("button", name="Yes").first.click()
        grab("poc-yes")
        page.get_by_role("button", name="Back").first.click()
        grab("poc-question-return")
        page.get_by_role("button", name="No").first.click()
        grab("poc-no")

        browser.close()

    print("captured PoC fixtures + their state signatures:")
    for name, sig in saved.items():
        print(f"  {name:22} -> {sig}")
    distinct = len(set(saved.values()))
    print(f"\ndistinct states among the 4 frames: {distinct}")
    print(f"question == question-after-back? {saved['poc-question'] == saved['poc-question-return']}")


if __name__ == "__main__":
    main()
