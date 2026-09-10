"""Record a corpus of EcoEstate Observations as JSON fixtures.

The point is a fixed dataset the identity/oracle logic can be developed and tested
against with no live browser - and, for the Stage 0 spike, the specific cases that
decide whether semantic identity is even feasible here: the same view at different map
zoom levels (must collapse to one state) versus genuinely different views.

Run from this directory with the app up on :5173:
    ../../.venv/Scripts/python capture_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from perceive import Collector, capture

URL = "http://localhost:5173/"
FIX = Path(__file__).parent / "fixtures"


def _click_if_present(page, role, name) -> bool:
    try:
        loc = page.get_by_role(role, name=name)
        if loc.count() > 0:
            loc.first.click(timeout=2000)
            return True
    except Exception:
        pass
    return False


def main() -> None:
    FIX.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        col = Collector().attach(page)

        page.goto(URL, wait_until="domcontentloaded")
        capture(page, col).save(FIX / "eco-initial.json")

        page.wait_for_timeout(3500)  # let boundaries load and the heatmap fetch resolve/fail
        capture(page, col).save(FIX / "eco-loaded.json")

        # Two map interactions: same view, different appearance. These must not become
        # new states - the browser analog of the scroll-surface over-split.
        if _click_if_present(page, "button", "Zoom in"):
            page.wait_for_timeout(1200)
            capture(page, col).save(FIX / "eco-zoom1.json")
            _click_if_present(page, "button", "Zoom in")
            page.wait_for_timeout(1200)
            capture(page, col).save(FIX / "eco-zoom2.json")

        # A fresh visit, to check cross-visit stability of the signature.
        page2 = browser.new_page(viewport={"width": 1280, "height": 900})
        Collector().attach(page2)
        page2.goto(URL, wait_until="domcontentloaded")
        page2.wait_for_timeout(3500)
        capture(page2, Collector().attach(page2)).save(FIX / "eco-loaded-revisit.json")

        browser.close()

    saved = sorted(f.name for f in FIX.glob("eco-*.json"))
    print(f"captured {len(saved)} fixtures: {', '.join(saved)}")
    # A quick look at what controls the DOM actually exposes (the a11y tree was thin).
    from perceive import Observation
    loaded = Observation.load(FIX / "eco-loaded.json")
    print(f"\neco-loaded: url={loaded.url!r} title={loaded.title!r}")
    print(f"  interactive elements found: {len(loaded.elements)}")
    for e in loaded.elements[:20]:
        print(f"    [{e['role']}] {e['name']!r}  <- {e['locator']}")
    errs = [n for n in loaded.network if n["status"] >= 400]
    print(f"  non-2xx responses: {errs}")


if __name__ == "__main__":
    sys.exit(main())
