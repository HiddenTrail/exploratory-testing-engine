"""Signals per step, a request log, and what the server said (issue #326). No browser."""

import time

from trailhound.adapters.web_gui import adapter as adp
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _acting_session, _Obs

ORIGIN = "http://app.example"


def _request(path, status, t=0.0, method="GET", origin=ORIGIN, **extra):
    return {"t": t, "method": method, "url": origin + path, "status": status, **extra}


def test_the_server_said_is_one_line_without_emails_ids_or_tokens():
    said = live_session.server_message('{"error": "You can order only up to 5 items of this product."}\n')
    assert said == '{"error": "You can order only up to 5 items of this product."}'
    secret = live_session.server_message("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc for a.b@x.co")
    assert "eyJ" not in secret and "a.b@x.co" not in secret and "<token>" in secret
    assert len(live_session.server_message("x " * 500)) <= 200


def test_a_logged_path_keeps_the_query_names_not_their_values():
    assert live_session.log_path("http://x/rest/products/search?q=secret&page=2") == "/rest/products/search?q=<v>&page=<v>"
    assert live_session.log_path("http://x/api/BasketItems/13") == "/api/BasketItems/13"


def test_a_step_says_what_it_set_off_trusted_only_when_the_test_is():
    requests = [_request("/api/BasketItems/13", 400, method="PUT",
                         message='{"error":"You can order only up to 5 items of this product."}'),
                _request("/rest/slow", 200, ms=3200),
                _request("/x.js", 404, origin="https://cdn.example")]
    console = [{"type": "error", "text": "boom"}, {"type": "warning", "text": "careful"}]
    found = live_session.step_signals(console, requests, {}, ORIGIN, trusted=True)
    assert found["signals"] == {"console_errors": ["boom"], "failed_requests": ["PUT http://app.example/api/BasketItems/13 -> 400"]}
    assert found["signals_weak"] == {"failed_requests": ["GET https://cdn.example/x.js -> 404"]}
    assert found["server_said"] == ['PUT http://app.example/api/BasketItems/13 -> 400: '
                                    '{"error":"You can order only up to 5 items of this product."}']
    assert found["slow"] == ["GET /rest/slow took 3.2 s"]
    untrusted = live_session.step_signals(console, requests, {}, ORIGIN, trusted=False)
    assert "signals" not in untrusted and untrusted["signals_weak"]["console_errors"] == ["boom"]
    assert live_session.step_signals([], [_request("/ok", 200, ms=40)], {}, ORIGIN, trusted=True) == {}


def test_the_request_log_lists_the_own_sites_requests_and_counts_the_rest():
    rows, others = live_session.request_log(
        [_request("/api/x?id=7", 200, ms=12), _request("/api/y", 500, ms=30, message="oops"),
         _request("/a.js", 200, origin="https://cdn.example")], step=2, origin=ORIGIN)
    assert rows == [{"step": 2, "method": "GET", "path": "/api/x?id=<v>", "status": 200, "ms": 12},
                    {"step": 2, "method": "GET", "path": "/api/y", "status": 500, "ms": 30, "message": "oops"}]
    assert others == 1


def test_a_failed_responses_body_is_read_after_the_step_and_only_for_the_own_site():
    sess = live_session.Session.__new__(live_session.Session)
    sess._site = ORIGIN

    class Resp:
        def __init__(self, body):
            self.body = body

        def text(self):
            if self.body is None:
                raise RuntimeError("body is gone")
            return self.body
    requests = [_request("/api/a", 400, _response=Resp('{"error":"no"}')),
                _request("/b.js", 404, origin="https://cdn.example", _response=Resp("third party")),
                _request("/api/c", 500, _response=Resp(None))]
    sess._read_messages(requests)
    assert requests[0]["message"] == '{"error":"no"}'
    assert "message" not in requests[1] and "message" not in requests[2]
    assert not any("_response" in r for r in requests)          # nothing unserialisable is left


def test_an_error_is_tied_to_the_step_that_set_it_off(monkeypatch):
    after = _Obs(elements=[{"role": "button", "name": "A", "locator": "#a"}])
    after.url = "http://app.example/"
    sess = _acting_session(monkeypatch, after)
    sess._site = ORIGIN
    real = sess._do_step

    def step(s):
        record = real(s)
        if s["name"] == "B":                                     # only the second step fails a request
            sess._requests[id(record)] = _request("/api/BasketItems/13", 400, t=time.time(), method="PUT", ms=20,
                                                  message='{"error":"only 5"}')
        return record
    monkeypatch.setattr(sess, "_do_step", step)
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#a"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/")
    sess.careful = {"everywhere": False, "routes": [], "controls": []}
    result = sess.act_steps("st01", [{"do": "click", "role": "button", "name": "A"},
                                     {"do": "click", "role": "button", "name": "B"}])
    first, second = result["steps"]
    assert "server_said" not in first
    assert second["server_said"] == ['PUT http://app.example/api/BasketItems/13 -> 400: {"error":"only 5"}']
    assert result["request_log"]["own_site"] == [{"step": 2, "method": "PUT", "path": "/api/BasketItems/13",
                                                  "status": 400, "ms": 20, "message": '{"error":"only 5"}'}]


def test_the_driver_gets_the_short_form_and_the_report_the_log():
    entry = {"test_number": 1, "result": {"request_log": {"own_site": [{"step": 1, "method": "GET", "path": "/x",
                                                                         "status": 500, "ms": 9, "message": "oops"}],
                                                          "third_party": 2},
                                          "steps": [{"do": "click", "role": "button", "name": "A", "status": "done",
                                                     "server_said": ["GET http://app.example/x -> 500: oops"]}]}}
    [redacted] = adp.redact_history_for_model([entry])
    assert "request_log" not in redacted["result"]
    assert redacted["result"]["steps"][0]["server_said"] == ["GET http://app.example/x -> 500: oops"]
    html = adp._request_log_html(entry["result"])
    assert "<code>/x</code>" in html and "oops" in html and "And 2 request(s) to other sites" in html
    assert "the server said GET http://app.example/x -&gt; 500: oops" in adp._steps_html(entry["result"]["steps"])


def test_console_warnings_are_hints_only():
    before = _Obs()
    after = _Obs(console=[{"type": "warning", "text": "deprecated API"}])
    signals, weak = live_session._signal_diff(before, after, [], {}, {}, True, True, {}, ORIGIN)
    assert "console_warnings" not in signals and weak["console_warnings"] == ["deprecated API"]
