"""The bootstrap probe sends real requests, so it stays on this machine and off other
paths (issue #415). No network or model calls: the CLI is stopped before it builds a
client, and the probe checks are pure functions."""

import sys

import pytest

from trailhound.bootstrap import cli
from trailhound.bootstrap.discovery import DiscoveredEndpoint
from trailhound.bootstrap.probe import validate_probe_response

_ENDPOINT = DiscoveredEndpoint(path="/orders/{id}", method="PUT", request_fields=[], response_fields=[],
                               raw_request_schema={}, raw_response_schema={})


def _probe(method, path):
    return {"give_up": False, "reasoning": "r", "method": method, "path": path, "body": {}}


def _errors(method, path, base_url="http://127.0.0.1:8000"):
    return validate_probe_response(_probe(method, path), base_url=base_url, endpoint=_ENDPOINT)


def _main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--name", "my_api", "--display-name", "My API", *args])
    monkeypatch.setattr(cli, "build_client", lambda: pytest.fail("a client was built, so a model call could follow"))
    monkeypatch.setattr(cli, "discover_or_draft_schema", lambda *a: pytest.fail("the SUT was contacted"))
    cli.main()


def test_the_cli_refuses_a_site_that_isnt_on_this_machine(monkeypatch):
    with pytest.raises(SystemExit, match="isn't on this machine.*--allow-remote"):
        _main(monkeypatch, "--base-url", "https://api.example.com")


def test_allow_remote_lets_a_throwaway_copy_through(monkeypatch):
    with pytest.raises(pytest.fail.Exception, match="a client was built"):
        _main(monkeypatch, "--base-url", "https://staging-copy.example.com", "--allow-remote")


def test_a_local_site_needs_no_flag(monkeypatch):
    for url in ("http://127.0.0.1:8020", "http://localhost:8000", "http://[::1]:8000"):
        with pytest.raises(pytest.fail.Exception, match="a client was built"):
            _main(monkeypatch, "--base-url", url)


def test_discover_only_reads_any_site(monkeypatch):
    # Discovery only GETs the published API description.
    seen = []
    monkeypatch.setattr(cli, "_run_discover_only", lambda base_url, name: seen.append(base_url))
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--name", "my_api", "--base-url", "https://api.example.com",
                                      "--discover-only"])
    cli.main()
    assert seen == ["https://api.example.com"]


def test_a_probe_may_read_anywhere_on_the_site_and_write_only_to_its_endpoint():
    assert _errors("GET", "/docs") == []
    assert _errors("PUT", "/orders/42") == []
    assert _errors("PUT", "/orders/42?dry=1") == []
    [error] = _errors("PUT", "/accounts/7")
    assert "only to /orders/{id}" in error


@pytest.mark.parametrize("method", ["DELETE", "PATCH", "POST"])
def test_a_probe_may_only_use_get_and_the_endpoints_own_method(method):
    [error] = _errors(method, "/orders/42")
    assert f"'{method}' isn't allowed here" in error and "GET or PUT" in error


@pytest.mark.parametrize("path", ["@evil.example/x", "//evil.example/x", "orders/42", ".evil.example/x"])
def test_a_probe_path_cant_leave_the_site(path):
    errors = _errors("GET", path)
    assert errors and "'path' must start with '/' and stay on http://127.0.0.1:8000" in errors[0]


def test_a_get_endpoint_allows_get_only():
    get = DiscoveredEndpoint(path="/items", method="GET", request_fields=[], response_fields=[],
                             raw_request_schema={}, raw_response_schema={})
    [error] = validate_probe_response(_probe("POST", "/items"), base_url="http://localhost:8000", endpoint=get)
    assert "'POST' isn't allowed here: send GET." in error


def test_without_a_site_and_endpoint_only_the_shape_is_checked():
    # The shape checks on their own, as before (#415 added the rest).
    assert validate_probe_response(_probe("DELETE", "/anything")) == []
