"""Signals per step, a request log, and what the server said (issue #326). No browser."""

import time

from trailhound.adapters.web_gui import adapter as adp
from trailhound.adapters.web_gui import session as live_session
from trailhound.tests.test_web_gui_adapter import _acting_session, _Obs

ORIGIN = "http://app.example"


def _request(path, status, t=0.0, method="GET", origin=ORIGIN, **extra):
    return {"t": t, "method": method, "url": origin + path, "status": status, **extra}


def test_what_the_server_said_is_taken_by_an_allowlist_and_redacted():
    said = live_session.server_message('{"error":"You can order only up to 5 items of this product."}',
                                       "application/json")
    assert said == "You can order only up to 5 items of this product."
    # Found in review: an SQL error echoed the query and a stack trace. Only the message keys count.
    sqli = '{"error":{"message":"SQLITE_ERROR: near x","stack":"Error at /app/x.js:10","sql":"SELECT * FROM Users"}}'
    assert live_session.server_message(sqli, "application/json") == "SQLITE_ERROR: near x"
    assert live_session.server_message("<html><head><title>Error: Unexpected path</title><style>*{}</style>",
                                       "text/html") == "Error: Unexpected path"
    assert live_session.server_message("Forbidden\nmore lines", "text/plain") == "Forbidden"
    assert live_session.server_message("\x89PNG...", "image/png") == ""
    secret = live_session.server_message('{"message":"reset sent to a.b@x.co, code 123456, '
                                         'token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"}', "json")
    assert "a.b@x.co" not in secret and "123456" not in secret and "eyJ" not in secret
    assert len(live_session.server_message('{"error":"' + "x " * 500 + '"}', "json")) <= 200


def test_a_logged_path_is_redacted_and_keeps_the_query_names_only():
    assert live_session.log_path("http://x/rest/products/search?q=secret&page=2") == "/rest/products/search?q=<v>&page=<v>"
    assert live_session.log_path("http://x/api/Users/victim.person@example.com") == "/api/Users/<email>"
    assert "eyJ" not in live_session.log_path("http://x/rest/user/reset-password/eyJabcdefghijk.lmnopqrstuv.wx")
    assert live_session.log_path("http://x/app;jsessionid=0123456789abcdef0123456789abcdef/a") == "/app"
    line = live_session._failed_line(_request("/api/Users/victim.person@example.com", 404))
    assert line == "GET http://app.example/api/Users/<email> -> 404"


def test_a_step_says_what_it_set_off_and_the_hints_stay_hints():
    requests = [_request("/api/BasketItems/13", 400, method="PUT", message="You can order only up to 5 items."),
                _request("/rest/slow", 200, ms=3200),
                _request("/rest/poll", 500, message="busy"),                      # also seen idle
                _request("/x.js", 404, origin="https://cdn.example")]
    console = [{"type": "error", "text": "boom"}, {"type": "warning", "text": "careful"}]
    noise = {"requests": {"GET http://app.example/rest/poll"}}
    found = live_session.step_signals(console, requests, noise, ORIGIN, trusted=True)
    assert found["signals"] == {"console_errors": ["boom"],
                                "failed_requests": ["PUT http://app.example/api/BasketItems/13 -> 400"]}
    assert found["signals_weak"]["failed_requests"] == ["GET http://app.example/rest/poll -> 500",
                                                        "GET https://cdn.example/x.js -> 404"]
    # What the server said and the slow ones: trusted own-site requests only, no origin.
    assert found["server_said"] == ["PUT /api/BasketItems/13 -> 400: You can order only up to 5 items."]
    assert found["slow"] == ["GET /rest/slow took 3.2 s"]
    untrusted = live_session.step_signals(console, requests, noise, ORIGIN, trusted=False)
    assert "signals" not in untrusted and "server_said" not in untrusted and "slow" not in untrusted
    # One step's signals would repeat the test's, so a single-step test leaves them out.
    single = live_session.step_signals(console, requests, noise, ORIGIN, trusted=True, with_signals=False)
    assert "signals" not in single and single["server_said"]
    assert live_session.step_signals([], [_request("/ok", 200, ms=40)], {}, ORIGIN, trusted=True) == {}


def test_a_long_list_says_how_many_more():
    console = [{"type": "error", "text": f"e{n}"} for n in range(8)]
    found = live_session.step_signals(console, [], {}, ORIGIN, trusted=True)
    assert len(found["signals"]["console_errors"]) == 5 and found["signals"]["console_errors_more"] == 3


def test_the_request_log_lists_the_own_sites_requests_and_counts_the_rest():
    rows, static, others = live_session.request_log(
        [_request("/api/x?id=7", 200, ms=12), _request("/api/y", 500, ms=30, message="oops"),
         _request("/main.js", 200), _request("/missing.css", 404), _request("/a.js", 200, origin="https://cdn.example")],
        step=2, origin=ORIGIN)
    assert rows == [{"step": 2, "method": "GET", "path": "/api/x?id=<v>", "status": 200, "ms": 12},
                    {"step": 2, "method": "GET", "path": "/api/y", "status": 500, "ms": 30, "message": "oops"},
                    {"step": 2, "method": "GET", "path": "/missing.css", "status": 404}]
    assert (static, others) == (1, 1)                 # a static file that loaded fine is only counted


def test_a_failed_responses_body_is_read_only_when_finished_text_and_own():
    sess = live_session.Session.__new__(live_session.Session)
    sess._site = ORIGIN

    class Resp:
        def __init__(self, body, kind="application/json", size=None):
            self.body, self.headers = body, {"content-type": kind, **({"content-length": str(size)} if size else {})}

        def text(self):
            if self.body is None:
                raise RuntimeError("body is gone")
            return self.body
    requests = [_request("/api/a", 400, ms=5, _response=Resp('{"error":"no"}')),
                _request("/b.js", 404, ms=5, origin="https://cdn.example", _response=Resp("third party")),
                _request("/api/c", 500, ms=5, _response=Resp(None)),
                _request("/api/d", 500, _response=Resp('{"error":"unfinished"}')),           # no ms: still loading
                _request("/img", 404, ms=5, _response=Resp("binary", "image/png")),
                _request("/big", 500, ms=5, _response=Resp('{"error":"x"}', size=10_000_000))]
    sess._read_messages(requests)
    assert requests[0]["message"] == "no"
    assert not any("message" in r for r in requests[1:])
    assert "_response" in requests[3]                          # read later, once it has finished
    assert not any("_response" in r for i, r in enumerate(requests) if i != 3)


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
                                                  message="only 5")
        return record
    monkeypatch.setattr(sess, "_do_step", step)
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#a"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/")
    sess.careful = {"everywhere": False, "routes": [], "controls": []}
    result = sess.act_steps("st01", [{"do": "click", "role": "button", "name": "A"},
                                     {"do": "click", "role": "button", "name": "B"}])
    first, second = result["steps"]
    assert "server_said" not in first and "signals" not in first
    assert second["server_said"] == ["PUT /api/BasketItems/13 -> 400: only 5"]
    assert second["signals"]["failed_requests"] == ["PUT http://app.example/api/BasketItems/13 -> 400"]
    assert result["request_log"]["own_site"] == [{"step": 2, "method": "PUT", "path": "/api/BasketItems/13",
                                                  "status": 400, "ms": 20, "message": "only 5"}]
    # A step after a rest that didn't settle isn't trusted: its error is a hint.
    sess = _acting_session(monkeypatch, after)
    sess._site = ORIGIN
    monkeypatch.setattr(sess, "_do_step", step)
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: {"role": role, "name": name, "locator": "#a"})
    monkeypatch.setattr(sess, "_page_route", lambda: "/")
    rests = iter([False, True, True])
    monkeypatch.setattr(sess, "_rest", lambda: next(rests, True))
    sess.careful = {"everywhere": False, "routes": [], "controls": []}
    result = sess.act_steps("st01", [{"do": "click", "role": "button", "name": "A"},
                                     {"do": "click", "role": "button", "name": "B"}])
    second = result["steps"][1]
    assert "server_said" not in second and second["signals_weak"]["failed_requests"]


def test_the_driver_gets_the_short_form_and_the_report_the_log():
    entry = {"test_number": 1, "result": {"request_log": {"own_site": [{"step": 1, "method": "GET", "path": "/x",
                                                                         "status": 500, "ms": 9, "message": "oops"}],
                                                          "static_files": 4, "third_party": 2},
                                          "steps": [{"do": "click", "role": "button", "name": "A", "status": "done",
                                                     "server_said": ["GET /x -> 500: oops"]}]}}
    [redacted] = adp.redact_history_for_model([entry])
    assert "request_log" not in redacted["result"]
    assert redacted["result"]["steps"][0]["server_said"] == ["GET /x -> 500: oops"]
    html = adp._request_log_html(entry["result"])
    assert "<code>/x</code>" in html and "oops" in html
    assert "And 4 static file(s) that loaded fine, 2 request(s) to other sites, counted only." in html
    assert "the server said GET /x -&gt; 500: oops" in adp._steps_html(entry["result"]["steps"])


def test_console_warnings_are_hints_only():
    before = _Obs()
    after = _Obs(console=[{"type": "warning", "text": "deprecated API"}])
    signals, weak = live_session._signal_diff(before, after, [], {}, {}, True, True, {}, ORIGIN)
    assert "console_warnings" not in signals and weak["console_warnings"] == ["deprecated API"]
