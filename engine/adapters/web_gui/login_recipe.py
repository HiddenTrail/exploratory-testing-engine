"""Log in with no person at the keyboard, from a recipe file, and save the session (issue #255).

save_session (#155) needs a person to log in, or at least to start the login. A CI job
has no person, so a recipe says what to do instead: a JSON file with the credentials to
use and the steps that log in, run in order on the live app. For example
test-targets/login-recipes/juice-shop.json registers a throwaway account and logs in:

    python -m engine.adapters.web_gui.login_recipe --recipe test-targets/login-recipes/juice-shop.json \\
        --url http://127.0.0.1:3000 --product juice-shop --name logged-in

The recipe holds no secrets and no product-specific code lives here. Credentials are
"generated:email" / "generated:password" (fresh for each run) or "env:<VAR>" (read from
the environment), and steps refer to them as {email}, {password}. Nothing prints a
credential or a stored value. A step that sends a request can create data (an account),
so a recipe with one is refused unless the target is this machine. The session is
written where save_session writes it, under the same rules: only where git ignores it.

Steps, run in order once the start URL has loaded:
    {"request": {"method": "POST", "path": "/api/Users/", "json": {...}}}   an HTTP call, must answer below 400
    {"goto": "/#/login"}                                                    open a path on the target
    {"click": "#loginButton"}                                               a CSS selector, or
    {"click": {"role": "button", "name": "Log in"}}                         a role and accessible name
    {"click_if_present": ...}                                               the same, skipped if it isn't there
    {"fill": "#email", "value": "{email}"}                                  type into a field
The recipe's "until" (as save_session's --until, e.g. "storage:bid") says when the login
is done and the session is saved.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

from engine.adapters.web_gui.save_session import REPO, capture_session, parse_until, session_path

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_STEP_KINDS = ("request", "goto", "click", "click_if_present", "fill")


def load_recipe(path) -> dict:
    """The recipe, or SystemExit saying what's wrong with it."""
    try:
        recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"Can't read the login recipe {path}: {e}")
    errors = []
    if not isinstance(recipe.get("credentials"), dict):
        errors.append("'credentials' must be an object, e.g. {\"email\": \"generated:email\"}")
    for name, source in (recipe.get("credentials") or {}).items():
        if not isinstance(source, str) or not source.startswith(("generated:", "env:")):
            errors.append(f"credential '{name}' must be 'generated:email', 'generated:password' or 'env:<VAR>'")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list")
    for i, step in enumerate(steps or []):
        kinds = [k for k in _STEP_KINDS if isinstance(step, dict) and k in step]
        if len(kinds) != 1:
            errors.append(f"steps[{i}] must have exactly one of: {', '.join(_STEP_KINDS)}")
        elif kinds[0] == "fill" and "value" not in step:
            errors.append(f"steps[{i}] fills a field, so it needs a 'value'")
    if not isinstance(recipe.get("until"), str):
        errors.append("'until' must say when the login is done, e.g. \"storage:bid\"")
    if errors:
        raise SystemExit(f"The login recipe {path} isn't valid:\n  " + "\n  ".join(errors))
    return recipe


def resolve_credentials(spec: dict, environ=os.environ) -> dict:
    """Each credential's value: generated fresh for this run, or read from the environment."""
    values = {}
    for name, source in spec.items():
        kind, _, arg = source.partition(":")
        if kind == "env":
            if not environ.get(arg):
                raise SystemExit(f"The login recipe needs the environment variable {arg} (for '{name}'), and it's unset.")
            values[name] = environ[arg]
        elif arg == "email":
            values[name] = f"qes-{secrets.token_hex(4)}@example.test"
        elif arg == "password":
            # Mixed case, a digit and a symbol, so common password rules accept it.
            values[name] = "Qs1!" + secrets.token_urlsafe(12)
        else:
            raise SystemExit(f"Credential '{name}': 'generated:{arg}' isn't one this knows (email, password).")
    return values


def fill_in(value, credentials: dict):
    """`value` with every {name} replaced by that credential, inside strings, lists and objects."""
    if isinstance(value, str):
        for name, secret in credentials.items():
            value = value.replace("{" + name + "}", secret)
        return value
    if isinstance(value, list):
        return [fill_in(v, credentials) for v in value]
    if isinstance(value, dict):
        return {k: fill_in(v, credentials) for k, v in value.items()}
    return value


def refuse_unless_local(recipe: dict, base_url: str) -> None:
    """A request step can create data (an account), so it only runs against this machine."""
    host = urlsplit(base_url).hostname or ""
    if any("request" in step for step in recipe["steps"]) and host not in _LOCAL_HOSTS:
        raise SystemExit(f"The login recipe sends requests that can create data, so it only runs against this "
                         f"machine ({', '.join(_LOCAL_HOSTS)}), not {host!r}.")


def _locator(page, target):
    if isinstance(target, dict):
        return page.get_by_role(target["role"], name=target["name"])
    return page.locator(target)


def run_steps(page, steps: list[dict], base_url: str, credentials: dict, http=None) -> None:
    """Run the steps in order on the live page. Errors name the step, never a value."""
    import httpx

    http = http or httpx
    base = base_url.rstrip("/")
    for i, step in enumerate(steps):
        if "request" in step:
            req = fill_in(step["request"], credentials)
            answer = http.request(req.get("method", "POST"), base + "/" + req["path"].lstrip("/"),
                                  json=req.get("json"), timeout=15)
            if answer.status_code >= 400:
                raise SystemExit(f"Login recipe step {i} ({req.get('method', 'POST')} {req['path']}) answered "
                                 f"{answer.status_code}.")
        elif "goto" in step:
            page.goto(base + "/" + step["goto"].lstrip("/"), wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
        elif "click_if_present" in step:
            try:
                _locator(page, step["click_if_present"]).first.click(timeout=2000)
            except Exception:
                pass
        elif "click" in step:
            _locator(page, step["click"]).first.click(timeout=10000)
        elif "fill" in step:
            _locator(page, step["fill"]).first.fill(fill_in(step["value"], credentials), timeout=10000)


def log_in(recipe_path, base_url: str, out: Path, headed: bool = False, timeout_s: float = 60,
           environ=os.environ) -> dict:
    """Run the recipe against `base_url` and save the session to `out`. Returns what was
    saved, by name only."""
    recipe = load_recipe(recipe_path)
    refuse_unless_local(recipe, base_url)
    credentials = resolve_credentials(recipe["credentials"], environ)
    return capture_session(base_url, out, until=parse_until(recipe["until"]), headed=headed, timeout_s=timeout_s,
                           on_page=lambda page: run_steps(page, recipe["steps"], base_url, credentials),
                           wait_for_enter=False)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Log in from a recipe file, with no person, and save the session.")
    ap.add_argument("--recipe", required=True, help="the login recipe, e.g. test-targets/login-recipes/juice-shop.json")
    ap.add_argument("--url", required=True, help="the target's base URL, e.g. http://127.0.0.1:3000")
    ap.add_argument("--product", required=True, help="product slug, e.g. juice-shop")
    ap.add_argument("--name", default="logged-in", help="session name (default logged-in)")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--timeout", type=float, default=60, help="seconds to wait for 'until' (default 60)")
    args = ap.parse_args()

    out = session_path(args.product, args.name)
    saved = log_in(args.recipe, args.url, out, headed=args.headed, timeout_s=args.timeout)
    print(f"Logged in from {args.recipe} and saved '{args.name}' to {out.relative_to(REPO)}: cookies "
          f"{', '.join(saved['cookies']) or 'none'}; storage {', '.join(saved['storage']) or 'none'}; session storage "
          f"{', '.join(saved['session_storage']) or 'none'}. Values are never printed.")


if __name__ == "__main__":
    main()
