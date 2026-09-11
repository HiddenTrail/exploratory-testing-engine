"""The Collector records console, page errors, responses AND failed requests.

Uses a fake page that just stores the event callbacks, so the handlers are exercised
with no browser - which is what catches shape bugs like reading r.request on a
requestfailed event (whose payload is a Request, not a Response).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from perceive import Collector  # noqa: E402


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, cb):
        self.handlers[event] = cb

    def fire(self, event, payload):
        self.handlers[event](payload)


class FakeRequest:
    def __init__(self, method="GET", url="http://x/api", failure="net::ERR_CONNECTION_REFUSED"):
        self.method, self.url, self.failure = method, url, failure


class FakeResponse:
    def __init__(self, status=200, url="http://x/", method="GET"):
        self.status, self.url = status, url
        self.request = FakeRequest(method=method, url=url, failure=None)


class FakeConsoleMsg:
    def __init__(self, type_, text, location=""):
        self.type, self.text, self.location = type_, text, location


def test_collector_records_responses():
    page = FakePage()
    col = Collector().attach(page)
    page.fire("response", FakeResponse(status=500, url="http://x/api", method="GET"))
    _, network = col.drain()
    assert {"method": "GET", "url": "http://x/api", "status": 500} in network


def test_collector_records_failed_requests():
    # The regression guard: a requestfailed payload is a Request, not a Response.
    page = FakePage()
    col = Collector().attach(page)
    page.fire("requestfailed", FakeRequest(method="POST", url="http://x/dead"))
    _, network = col.drain()
    failed = [n for n in network if n.get("failure")]
    assert failed, "failed request not recorded"
    assert failed[0]["status"] == 0 and failed[0]["method"] == "POST"
    assert "REFUSED" in failed[0]["failure"]


def test_collector_records_console_and_page_errors():
    page = FakePage()
    col = Collector().attach(page)
    page.fire("console", FakeConsoleMsg("error", "boom", "app.js:1"))
    page.fire("pageerror", ValueError("kaboom"))
    console, _ = col.drain()
    kinds = {c["type"] for c in console}
    assert "error" in kinds and "pageerror" in kinds


def test_drain_clears():
    page = FakePage()
    col = Collector().attach(page)
    page.fire("response", FakeResponse())
    col.drain()
    assert col.drain() == ([], [])
