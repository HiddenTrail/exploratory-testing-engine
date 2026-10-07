"""Save a browser session to start web_gui tests and Spoor from (issue #155).

A session file is Playwright's context.storage_state() (cookies and localStorage), plus each
origin's sessionStorage under "sessionStorage", which Playwright leaves out (issue #228).
Playwright and Spoor ignore that key, so the file still works with both. web_gui loads it
into every test's fresh context (WEB_GUI_SESSION, #154), and Spoor
maps from it (spoor explore --session). The Driver can't type credentials, and that stays,
so a session comes from a person, or from a scripted login on a sandbox target:

    python -m trailhound.adapters.web_gui.save_session --url http://127.0.0.1:3000 \\
        --product juice-shop --name logged-in

opens a visible browser at the URL. Log in (or put the app in any state worth keeping),
then press Enter in this terminal. No password is stored anywhere. With --until, it saves as
soon as a condition holds, without waiting for Enter (for CI, or no terminal):

    --until storage:token        a local or session storage key exists
    --until cookie:sessionid     a cookie exists
    --until url:/dashboard       the URL contains the text
    --until selector:#logout     an element matching the CSS selector exists

A session file holds live auth cookies, so this refuses to write anywhere git doesn't
ignore (the default, .sessions/, is), and it prints only the names of what it saved.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SESSIONS_DIR = REPO / ".sessions"
UNTIL_KINDS = ("storage", "cookie", "url", "selector")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")


def session_path(product: str, name: str) -> Path:
    """Where a product's named session lives: .sessions/<product>/<name>.json."""
    for label, value in (("product", product), ("name", name)):
        if not _SLUG.fullmatch(value or ""):
            raise SystemExit(f"--{label} must be lowercase letters, digits and dashes, e.g. 'juice-shop' "
                             f"or 'logged-in' (got {value!r})")
    return SESSIONS_DIR / product / f"{name}.json"


def parse_until(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    kind, _, value = text.partition(":")
    if kind not in UNTIL_KINDS or not value:
        raise SystemExit(f"--until must be one of {', '.join(k + ':<value>' for k in UNTIL_KINDS)} (got {text!r})")
    return kind, value


def is_ignored(path: Path) -> bool:
    """Whether git ignores this path, so a session saved there can't be committed by
    accident. Without git, only a path inside .sessions/ counts."""
    try:
        done = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=REPO, capture_output=True)
        if done.returncode in (0, 1):
            return done.returncode == 0
    except OSError:
        pass
    return SESSIONS_DIR in Path(path).resolve().parents


def refuse_unless_ignored(path: Path) -> None:
    if not is_ignored(path):
        raise SystemExit(f"Not saving a session to {path}: git doesn't ignore it, so it could be committed. "
                         f"Use the default under .sessions/, or a path your .gitignore covers.")


def condition_met(page, context, until: tuple[str, str]) -> bool:
    kind, value = until
    try:
        if kind == "url":
            return value in page.url
        if kind == "selector":
            return page.query_selector(value) is not None
        if kind == "cookie":
            return any(c.get("name") == value for c in context.cookies())
        if kind == "storage":
            return bool(page.evaluate("(k) => localStorage.getItem(k) !== null || sessionStorage.getItem(k) !== null",
                                      value))
    except Exception:
        return False
    return False


def summary(state: dict) -> dict:
    """What was saved, by name only: never a cookie's or a storage entry's value."""
    return {
        "cookies": sorted({c["name"] for c in state.get("cookies", [])}),
        "storage": sorted({e["name"] for o in state.get("origins", []) for e in o.get("localStorage", [])}),
        "session_storage": sorted({e["name"] for o in state.get("origins", []) for e in o.get("sessionStorage", [])}),
    }


_SESSION_STORAGE_JS = "() => [location.origin, Object.entries(sessionStorage)]"


def save_state(context, out: Path) -> dict:
    """Write the context's session to `out`: Playwright's storage_state, plus the
    sessionStorage of every page open in it, per origin (issue #228). Playwright leaves
    sessionStorage out because it belongs to one tab, but apps keep login-related state
    there: Juice Shop keeps the basket id in it, so a saved session without it opened
    the basket with "TypeError: Cannot read properties of null (reading 'Products')"
    in every test. Returns the summary."""
    state = context.storage_state()
    by_origin: dict[str, dict] = {}
    for page in context.pages:
        try:
            origin, entries = page.evaluate(_SESSION_STORAGE_JS)
        except Exception:   # a closed page, or one on about:blank
            continue
        if origin and origin != "null" and entries:
            by_origin.setdefault(origin, {}).update(dict(entries))
    for origin, items in by_origin.items():
        entry = next((o for o in state["origins"] if o["origin"] == origin), None)
        if entry is None:
            entry = {"origin": origin, "localStorage": []}
            state["origins"].append(entry)
        entry["sessionStorage"] = [{"name": k, "value": v} for k, v in items.items()]
    out.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return summary(state)


def capture_session(url: str, out: Path, until: tuple[str, str] | None = None, headed: bool = True,
                    timeout_s: float = 600, on_page=None, wait_for_enter: bool = True) -> dict:
    """Open a browser at `url`, let a person (or `on_page`, for a scripted sandbox login)
    put the app into the state worth keeping, and save the session once `until` holds or
    Enter is pressed. Returns the summary of what was saved. Nothing is written if the
    timeout runs out."""
    refuse_unless_ignored(out)
    if until is None and not (wait_for_enter and sys.stdin and sys.stdin.isatty()):
        raise SystemExit("No terminal to press Enter in: pass --until so the session is saved when a condition holds.")
    from playwright.sync_api import sync_playwright

    entered = threading.Event()
    if until is None or (wait_for_enter and sys.stdin and sys.stdin.isatty()):
        def wait():
            try:
                input("Put the app in the state to keep (e.g. log in), then press Enter here to save... ")
                entered.set()
            except EOFError:
                pass
        threading.Thread(target=wait, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        if on_page:
            on_page(page)
        deadline = time.time() + timeout_s
        while not (entered.is_set() or (until and condition_met(page, context, until))):
            if time.time() > deadline:
                browser.close()
                raise SystemExit(f"Gave up after {timeout_s:.0f} s: "
                                 + (f"{until[0]}:{until[1]} never held" if until else "Enter was never pressed")
                                 + ". Nothing was saved.")
            page.wait_for_timeout(500)
        out.parent.mkdir(parents=True, exist_ok=True)
        saved = save_state(context, out)
        browser.close()
    return saved


def main() -> None:
    ap = argparse.ArgumentParser(description="Save a browser session for web_gui (WEB_GUI_SESSION) and Spoor (--session).")
    ap.add_argument("--url", required=True, help="where to open the browser, e.g. the login page")
    ap.add_argument("--product", required=True, help="product slug, e.g. juice-shop")
    ap.add_argument("--name", required=True, help="the state this session is in, e.g. logged-in")
    ap.add_argument("--until", default=None, help="save when this holds: storage:<key>, cookie:<name>, url:<text> "
                                                   "or selector:<css> (otherwise press Enter)")
    ap.add_argument("--headless", action="store_true", help="no visible browser (only useful with --until)")
    ap.add_argument("--timeout", type=float, default=600, help="seconds to wait before giving up (default 600)")
    args = ap.parse_args()

    out = session_path(args.product, args.name)
    saved = capture_session(args.url, out, parse_until(args.until), headed=not args.headless, timeout_s=args.timeout)
    print(f"Saved session '{args.name}' to {out.relative_to(REPO)}: cookies {', '.join(saved['cookies']) or 'none'}; "
          f"storage {', '.join(saved['storage']) or 'none'}; session storage "
          f"{', '.join(saved['session_storage']) or 'none'}. Values are never printed.")
    print(f"Use it: WEB_GUI_SESSION={out.relative_to(REPO).as_posix()}, or spoor explore <url> --session {out}")


if __name__ == "__main__":
    main()
