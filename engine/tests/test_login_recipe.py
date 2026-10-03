"""Logging in from a recipe file with no person (issue #255). No browser and no network:
the page and the HTTP client are faked."""

import json

import pytest

from engine.adapters.web_gui import login_recipe as lr

JUICE_SHOP = lr.REPO / "test-targets" / "login-recipes" / "juice-shop.json"


def _recipe(tmp_path, **kw):
    recipe = {"credentials": {"email": "generated:email", "password": "generated:password"},
              "steps": [{"goto": "/#/login"}, {"fill": "#email", "value": "{email}"}, {"click": "#go"}],
              "until": "storage:token", **kw}
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    return path


def test_the_juice_shop_recipe_is_valid():
    recipe = lr.load_recipe(JUICE_SHOP)
    assert recipe["until"] == "storage:bid"
    assert any("request" in step for step in recipe["steps"])     # it registers, so it's local only


@pytest.mark.parametrize("change, message", [
    ({"credentials": {"email": "hunter2"}}, "credential 'email' must be"),
    ({"steps": []}, "'steps' must be a non-empty list"),
    ({"steps": [{"goto": "/", "click": "#x"}]}, "steps[0] must have exactly one of"),
    ({"steps": [{"fill": "#email"}]}, "steps[0] fills a field, so it needs a 'value'"),
    ({"until": None}, "'until' must say when the login is done"),
])
def test_a_broken_recipe_is_refused_with_the_reason(tmp_path, change, message):
    with pytest.raises(SystemExit) as stopped:
        lr.load_recipe(_recipe(tmp_path, **change))
    assert message in str(stopped.value)


def test_credentials_are_generated_fresh_or_read_from_the_environment():
    first = lr.resolve_credentials({"email": "generated:email", "password": "generated:password"})
    second = lr.resolve_credentials({"email": "generated:email", "password": "generated:password"})
    assert first["email"].endswith("@example.test") and first["email"] != second["email"]
    assert first["password"] != second["password"] and first["password"].startswith("Qs1!")
    assert lr.resolve_credentials({"user": "env:SHOP_USER"}, environ={"SHOP_USER": "ann"}) == {"user": "ann"}
    with pytest.raises(SystemExit, match="needs the environment variable SHOP_USER"):
        lr.resolve_credentials({"user": "env:SHOP_USER"}, environ={})


def test_placeholders_are_filled_inside_strings_lists_and_objects():
    filled = lr.fill_in({"email": "{email}", "pair": ["{password}", "{password}"], "n": 1},
                        {"email": "a@b.test", "password": "pw"})
    assert filled == {"email": "a@b.test", "pair": ["pw", "pw"], "n": 1}


def test_a_recipe_that_sends_requests_only_runs_against_this_machine(tmp_path):
    recipe = lr.load_recipe(JUICE_SHOP)
    for url in ("http://127.0.0.1:3000", "http://localhost:3000"):
        lr.refuse_unless_local(recipe, url)
    with pytest.raises(SystemExit, match="only runs against this machine"):
        lr.refuse_unless_local(recipe, "https://shop.example.com")
    lr.refuse_unless_local(lr.load_recipe(_recipe(tmp_path)), "https://shop.example.com")   # no requests: fine


class _Page:
    def __init__(self, missing=()):
        self.done, self.missing = [], set(missing)

    def goto(self, url, wait_until=None):
        self.done.append(("goto", url))

    def wait_for_timeout(self, ms):
        pass

    def locator(self, css):
        return _Target(self, css)

    def get_by_role(self, role, name):
        return _Target(self, f"{role}:{name}")


class _Target:
    def __init__(self, page, what):
        self.page, self.what, self.first = page, what, self

    def click(self, timeout=None):
        if self.what in self.page.missing:
            raise TimeoutError(self.what)
        self.page.done.append(("click", self.what))

    def fill(self, value, timeout=None):
        self.page.done.append(("fill", self.what, value))


class _Http:
    def __init__(self, status):
        self.status, self.sent = status, []

    def request(self, method, url, json=None, timeout=None):
        self.sent.append((method, url, json))
        return type("R", (), {"status_code": self.status})()


def test_the_steps_run_in_order_with_the_credentials_filled_in():
    steps = lr.load_recipe(JUICE_SHOP)["steps"]
    page, http = _Page(missing={"button:dismiss cookie message"}), _Http(201)
    lr.run_steps(page, steps, "http://127.0.0.1:3000/", {"email": "a@b.test", "password": "pw"}, http=http)
    assert http.sent[0][:2] == ("POST", "http://127.0.0.1:3000/api/Users/")
    assert http.sent[0][2]["email"] == "a@b.test" and http.sent[0][2]["passwordRepeat"] == "pw"
    assert page.done == [("goto", "http://127.0.0.1:3000/#/login"), ("click", "button:Close Welcome Banner"),
                         ("fill", "#email", "a@b.test"), ("fill", "#password", "pw"), ("click", "#loginButton")]


def test_a_failed_request_stops_the_login_without_printing_a_value():
    with pytest.raises(SystemExit) as stopped:
        lr.run_steps(_Page(), [{"request": {"method": "POST", "path": "/api/Users/", "json": {"password": "{password}"}}}],
                     "http://127.0.0.1:3000", {"password": "SECRET-PW"}, http=_Http(500))
    assert "POST /api/Users/) answered 500" in str(stopped.value) and "SECRET-PW" not in str(stopped.value)
