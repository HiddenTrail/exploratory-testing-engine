"""The web-GUI adapter's pure parts: reading the carried reference into an action space,
the outcome envelope, and casting validation. No browser and no model - the live session is
exercised only behind a real run."""

from engine import outcome
from engine.adapters.web_gui import adapter as adp
from engine.adapters.web_gui import careful as careful_mod
from engine.adapters.web_gui import reference as ref_mod
from engine.adapters.web_gui import session as live_session


def _ontology() -> dict:
    """A tiny 3-state map: st01 (entry) -> st02 via 'A', a dead control on st01, Back on
    st02, and a committing 'Buy' on st02 the recon marked off-limits."""
    return {
        "target": {"url": "http://app.example/"},
        "states": [
            {"id": "st01", "url": "http://app.example/", "signature": "/|button:A;button:Dead|",
             "title": "Home", "first_seen": 0, "elements": [
                 {"key": "button:A", "role": "button", "name": "A", "locator": "#a", "committing": False},
                 {"key": "button:Dead", "role": "button", "name": "Dead", "locator": "#dead", "committing": False}]},
            {"id": "st02", "url": "http://app.example/p2", "signature": "/p2|button:Back|",
             "title": "Page 2", "first_seen": 1, "elements": [
                 {"key": "button:Back", "role": "button", "name": "Back", "locator": "#back", "committing": False},
                 {"key": "button:Buy", "role": "button", "name": "Buy", "locator": "#buy", "committing": True}]},
        ],
        "transitions": [
            {"source": "st01", "dest": "st02", "effect": "navigate",
             "action": {"kind": "click", "element_key": "button:A", "target": "#a"}},
            {"source": "st01", "dest": "st01", "effect": "dead",
             "action": {"kind": "click", "element_key": "button:Dead", "target": "#dead"}},
            {"source": "st02", "dest": "st01", "effect": "navigate",
             "action": {"kind": "click", "element_key": "button:Back", "target": "#back"}},
        ],
    }


# ---- reference -----------------------------------------------------------------------

def test_reference_entry_and_pairs():
    ref = ref_mod.Reference(_ontology())
    assert ref.entry() == "st01"
    assert ref.base_url == "http://app.example/"
    # Only non-committing controls on reachable states; 'Buy' is excluded (committing).
    assert ref.pairs() == {("st01", "button:A"), ("st01", "button:Dead"), ("st02", "button:Back")}


def test_reference_paths_and_actuation_plan():
    ref = ref_mod.Reference(_ontology())
    # st01 is the entry (empty path); st02 is reached by clicking A.
    assert ref.plan_for("st01", "button:A")["path"] == []
    plan = ref.plan_for("st02", "button:Back")
    assert plan["path"] == [{"role": "button", "name": "A", "locator": "#a"}]
    assert plan["target"] == {"role": "button", "name": "Back", "locator": "#back"}
    assert ref.plan_for("st02", "button:Buy") is None      # committing -> not in the catalogue


def test_reference_briefing_is_a_guide_with_routes():
    # #310: each screen with its route, then what the recon found on it, without the
    # screen id repeated on every line.
    briefing = ref_mod.Reference(_ontology()).driver_briefing()
    assert "  st01 (Home) - route / - the start screen\n      button:A\n" in briefing
    assert "  st02 (Page 2) - route /p2 - 1 navigation(s) from the start\n      button:Back" in briefing
    assert "button:Buy" not in briefing     # until #299, the read-only gate still refuses it


def test_reference_fails_closed_on_a_missing_committing_flag():
    data = _ontology()
    # An element with no 'committing' key (foreign/hand-edited ontology) must NOT be offered.
    data["states"][0]["elements"].append(
        {"key": "button:Mystery", "role": "button", "name": "Mystery", "locator": "#m"})
    assert ("st01", "button:Mystery") not in ref_mod.Reference(data).pairs()


def test_reference_ignores_states_unreachable_by_navigation():
    data = _ontology()
    data["states"].append({"id": "st09", "url": "u", "signature": "/orphan|button:X|", "first_seen": 9,
                            "elements": [{"key": "button:X", "role": "button", "name": "X",
                                          "locator": "#x", "committing": False}]})
    ref = ref_mod.Reference(data)   # st09 has no navigation into it -> no path -> not offered
    assert ("st09", "button:X") not in ref.pairs()


# ---- actuation: fill text controls, click the rest -----------------------------------

class _FakeLoc:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag

    def count(self):
        return 1

    def click(self, timeout=None):
        self.page.calls.append(("click_role", self.tag))

    def fill(self, value, timeout=None):
        self.page.calls.append(("fill_role", value))


class _FakePage:
    def __init__(self):
        self.calls = []

    def get_by_role(self, role, name, exact=False):
        return _FakeLoc(self, (role, name))

    def click(self, css, timeout=None, force=False):
        self.calls.append(("click_css", css))

    def fill(self, css, value, timeout=None):
        self.calls.append(("fill_css", value))


def _bare_session():
    sess = live_session.Session.__new__(live_session.Session)   # no browser launched
    sess.page = _FakePage()
    return sess


def test_actuate_fills_a_search_box_rather_than_clicking_it():
    sess = _bare_session()
    assert sess._actuate({"role": "textbox", "name": "Search postcodes", "locator": "#q"}) is True
    kind, val = sess.page.calls[-1][0], sess.page.calls[-1]
    assert kind in ("fill_role", "fill_css")   # a fill, not a click -> no false dead-control


def test_actuate_clicks_a_button_control():
    sess = _bare_session()
    assert sess._actuate({"role": "button", "name": "Zoom in", "locator": "#z"}) is True
    assert sess.page.calls[-1][0] in ("click_role", "click_css")


class _NoRolePage(_FakePage):
    """Playwright's role lookup finds nothing (it names by the accessibility tree), and
    the control now sits at a different selector than the saved one."""

    def get_by_role(self, role, name, exact=False):
        loc = _FakeLoc(self, (role, name))
        loc.count = lambda: 0
        return loc

    def evaluate(self, js):
        return [{"role": "button", "name": "school Help getting started", "locator": "#now"}]


def test_actuate_clicks_where_the_control_is_now_not_where_it_was_saved():
    # Issue #123: a toast shifts the saved positional selector.
    sess = live_session.Session.__new__(live_session.Session)
    sess.page = _NoRolePage()
    assert sess._actuate({"role": "button", "name": "school Help getting started", "locator": "#saved"})
    assert sess.page.calls == [("click_css", "#now")]


class _CoveredPage(_FakePage):
    """What's on top of the control, in the order the checks will see it (issue #130)."""

    def __init__(self, *covers):
        super().__init__()
        self.covers = list(covers)

    def evaluate(self, js, arg=None):
        if arg is None:   # the live element lookup: nothing found, so the saved selector is used
            return []
        return self.covers.pop(0) if len(self.covers) > 1 else self.covers[0]

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    def click(self, css, timeout=None, force=False):
        self.calls.append(("force_click" if force else "click_css", css))

    def dispatch_event(self, css, event, timeout=None):
        self.calls.append(("dispatch", css, event))


def _covered_session(*covers):
    sess = live_session.Session.__new__(live_session.Session)
    sess.page = _CoveredPage(*covers)
    return sess


def test_a_control_under_another_element_gets_the_click_event_and_says_what_covered_it():
    # A forced click lands on whatever is on top: on Juice Shop the cookie notice, so
    # "Next page" never paged.
    sess = _covered_session({"state": "covered", "by": "dialog 'cookieconsent'"})
    assert sess._actuate({"role": "button", "name": "Next page", "locator": "#next"})
    assert sess.page.calls[-1] == ("dispatch", "#next", "click")
    assert sess.last_covered_by == "dialog 'cookieconsent'"


def test_a_control_under_its_own_part_gets_a_forced_click_and_no_warning():
    sess = _covered_session({"state": "own"})
    assert sess._actuate({"role": "radio", "name": "English", "locator": "#en"})
    assert sess.page.calls == [("force_click", "#en")]
    assert sess.last_covered_by == ""


def test_a_cover_that_fades_out_gets_a_normal_click():
    sess = _covered_session({"state": "covered", "by": "dialog 'x'"}, {"state": "clear"})
    assert sess._actuate({"role": "button", "name": "Next page", "locator": "#next"})
    assert ("wait", 200) in sess.page.calls
    assert sess.page.calls[-1][0] == "click_role"
    assert sess.last_covered_by == ""


def test_the_log_line_says_what_was_clicked_through():
    line = adp.describe_result_for_log({"result": {
        "verdict": "sent", "screen_was": "same_screen", "click": 1.2, "settle": 0.4,
        "reached_target_state": True, "covered_by": "dialog 'cookieconsent'"}})
    assert "clicked through dialog 'cookieconsent'" in line


def test_classify_same_known_new_screen():
    ref = ref_mod.Reference(_ontology())      # carried sigs: st01 and st02's signatures
    sess = live_session.Session.__new__(live_session.Session)
    sess.reference, sess.seen_signatures = ref, set()
    st01 = "/|button:A;button:Dead|"
    assert sess._classify(st01, st01) == "same_screen"               # signature unchanged
    assert sess._classify(st01, "/p2|button:Back|") == "known_screen"  # a carried signature
    assert sess._classify(st01, "brand-new") == "new_screen"          # unmapped, unseen
    sess.seen_signatures.add("seen-earlier")
    assert sess._classify(st01, "seen-earlier") == "known_screen"     # seen already this run


# ---- outcome envelope ----------------------------------------------------------------

def _result(**kw):
    base = {"action": "st01 :: button:A", "screen_before": "sigA", "screen_after": "sigA",
            "screen_was": "same_screen", "same_appearance": True, "was_measured_before": True,
            "verdict": "sent", "settle": 0.3}
    base.update(kw)
    return base


def test_outcome_dead_control_is_none_not_variant():
    o = adp.outcome_for(_result(screen_was="same_screen", same_appearance=True))
    assert o.effect == outcome.NONE and o.accepted is None


def test_outcome_same_screen_but_moved_is_variant():
    o = adp.outcome_for(_result(screen_was="same_screen", same_appearance=False))
    assert o.effect == outcome.VARIANT


def test_outcome_transition_carries_matched_prior():
    o = adp.outcome_for(_result(screen_was="known_screen", screen_after="sigB", was_measured_before=True))
    assert o.effect == outcome.TRANSITION and o.matched_prior is True
    assert o.state_before == "sigA" and o.state_after == "sigB"


def test_outcome_new_screen_records_recovery():
    o = adp.outcome_for(_result(screen_was="new_screen", screen_after="sigNew",
                                was_measured_before=False, recovered_to="sigA", recovered_ok=True))
    assert o.effect == outcome.TRANSITION and o.reset_attempted is True and o.reset_ok is True


def test_outcome_not_actuated_is_unknown_and_unaccepted():
    o = adp.outcome_for(_result(verdict="not_actuated"))
    assert o.effect == outcome.UNKNOWN and o.accepted is False


# ---- casting validation --------------------------------------------------------------

def _good_test(**kw):
    base = {"linked_hypothesis": "", "oracle_claim_id": "", "start": "st01",
            "steps": [{"do": "click", "role": "button", "name": "A"}],
            "predicted_screen": "known_screen", "predicted_outcome": "goes to page 2"}
    base.update(kw)
    return base


def test_validate_accepts_a_good_round_shape_only():
    assert adp.validate_casting_response({"give_up": False, "reasoning": "r",
                                          "candidate_tests": [_good_test()]}) == []


def test_validate_rejects_bad_prediction_and_missing_fields():
    errs = adp.validate_casting_response({"give_up": False, "reasoning": "r", "candidate_tests": [
        _good_test(predicted_screen="teleport"), {"start": "st01"}]})
    assert any("predicted_screen" in e for e in errs)
    assert any("missing" in e for e in errs)


def test_validate_allows_give_up_with_no_tests():
    assert adp.validate_casting_response({"give_up": True, "reasoning": "done", "candidate_tests": []}) == []


def test_the_map_doesnt_limit_what_a_test_may_touch():
    # #310: the map is a guide. A step on something the map doesn't have is a valid test;
    # if it isn't on the page, the result says so.
    tests = [_good_test(start="/#/basket", steps=[{"do": "click", "role": "button", "name": "Checkout"},
                                                  {"do": "fill", "role": "textbox", "name": "Coupon", "value": "-1"},
                                                  {"do": "goto", "value": "/#/profile"}, {"do": "back"}])]
    assert adp.validate_casting_response({"give_up": False, "reasoning": "r", "candidate_tests": tests}) == []


def test_each_step_has_what_its_kind_needs():
    batch = lambda *steps: {"give_up": False, "reasoning": "r", "candidate_tests": [_good_test(steps=list(steps))]}
    errors = adp.validate_casting_response(batch({"do": "teleport"}, {"do": "click", "name": "Go"},
                                                 {"do": "fill", "role": "textbox", "name": "Q"},
                                                 {"do": "goto", "value": "https://elsewhere.example"}))
    assert errors == [
        "candidate_tests[0].steps[0].do must be one of: click, fill, select, goto, back",
        "candidate_tests[0].steps[1] (click) needs a 'role'",
        "candidate_tests[0].steps[2] (fill) needs a 'value'",
        "candidate_tests[0].steps[3] (goto) needs a route on the site as its value, starting with '/' or '#'"]
    assert "1 to 6 steps" in adp.validate_casting_response(batch())[0]


class _SessionPage:
    def __init__(self):
        self.visited = []

    def on(self, event, handler):
        pass

    def goto(self, url, wait_until=None):
        self.visited.append(url)

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass


class _SessionContext:
    def __init__(self):
        self.page = _SessionPage()
        self.closed = False
        self.init_scripts = []
        self.guarded = []
        self.handlers = {}

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event, handler):
        self.handlers[event] = handler

    def new_cdp_session(self, page):
        context = self

        class _Cdp:
            sent = []

            def send(self, method, params=None):
                self.sent.append((method, params))
                if method == "Fetch.enable":
                    context.guarded.append(params)
                return {"frameTree": {"frame": {"id": "main"}}}

            def on(self, event, handler):
                pass
        return _Cdp()

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _SessionBrowser:
    def __init__(self):
        self.contexts = []

    def new_context(self, viewport=None, storage_state=None):
        self.contexts.append(_SessionContext())
        self.contexts[-1].storage_state = storage_state
        return self.contexts[-1]


def test_every_restart_starts_from_a_fresh_browser_session():
    # Issue #117: on a reused page, cookies carried over, so after Juice Shop's
    # welcome banner was dismissed every restart landed on a different screen.
    session = object.__new__(live_session.Session)
    session.base_url = "http://127.0.0.1:3000"
    session._browser = _SessionBrowser()
    session._context = None
    session._open_fresh_page()
    first = session._browser.contexts[0]

    session._reboot()
    session._reboot()

    contexts = session._browser.contexts
    assert len(contexts) == 3, "a new context for the start, and one per restart"
    assert first.closed and contexts[1].closed and not contexts[2].closed
    assert session.page is contexts[2].page
    assert contexts[2].page.visited == ["http://127.0.0.1:3000"]


def test_the_generic_oracle_is_in_the_evidence_and_can_be_switched_off(monkeypatch):
    # Issue #114: web_gui has no product claims yet, so its oracle is the generic
    # heuristics, ranked. WEB_GUI_ORACLE=off leaves it out, for comparing runs.
    import importlib

    import engine.adapters.web_gui.adapter as web_adapter

    monkeypatch.delenv("WEB_GUI_ORACLE", raising=False)
    on = importlib.reload(web_adapter)
    ids = [idea["id"] for idea in on.ADAPTER.onboarding_extra["oracle_ranked"]]
    assert ids and all(i.startswith("heuristic:") for i in ids)
    assert "oracle_claim_id" in on.CASTING_TOOL["input_schema"]["properties"]["candidate_tests"]["items"]["required"]

    monkeypatch.setenv("WEB_GUI_ORACLE", "off")
    off = importlib.reload(web_adapter)
    assert "oracle_ranked" not in off.ADAPTER.onboarding_extra
    monkeypatch.delenv("WEB_GUI_ORACLE")
    importlib.reload(web_adapter)


class _WaitingPage:
    def __init__(self):
        self.calls = []

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))


def test_a_capture_taken_while_the_page_still_loads_is_taken_again(monkeypatch):
    # Issue #131: Juice Shop's paginator renders after the product list, so a capture
    # a moment early read as another state.
    captures = iter(["loading", "loading", "ready"])
    monkeypatch.setattr(live_session, "capture", lambda page, col: next(captures))
    monkeypatch.setattr(live_session, "signature", lambda obs: obs)
    sess = live_session.Session.__new__(live_session.Session)
    sess.page, sess.col = _WaitingPage(), None
    assert sess._capture_expecting("ready") == "ready"
    assert sess.page.calls.count(("wait", live_session._RECAPTURE_WAIT_MS)) == 2


def test_a_state_that_stays_different_is_reported_as_it_is(monkeypatch):
    monkeypatch.setattr(live_session, "capture", lambda page, col: "elsewhere")
    monkeypatch.setattr(live_session, "signature", lambda obs: obs)
    sess = live_session.Session.__new__(live_session.Session)
    sess.page, sess.col = _WaitingPage(), None
    assert sess._capture_expecting("ready") == "elsewhere"


# ---- rested reads and the signal diff (issue #143) -------------------------------------

class _Obs:
    def __init__(self, elements=(), console=(), network=()):
        self.url, self.headings, self.text, self.title = "http://x/#/", [], "", ""
        self.elements, self.console, self.network = list(elements), list(console), list(network)


ORIGIN = "http://x"


def _req(method, url, status, **kw):
    return {"t": 0, "method": method, "url": url, "status": status, **kw}


def test_only_signals_that_pass_every_trust_check_count_as_facts():
    before = _Obs(elements=[{"role": "button", "name": "Close"}])
    after = _Obs(elements=[{"role": "button", "name": "Menu"}],
                 console=[{"type": "error", "text": "TypeError: x is undefined"},
                          {"type": "error", "text": "poll 17 failed"}, {"type": "log", "text": "hi"}])
    requests = [_req("GET", "http://x/api/a", 200),                               # fine: not a signal
                _req("POST", "http://x/api/b", 500),                              # trusted
                _req("GET", "http://ads.example/pixel", 0, failure="net::ERR"),   # third-party: weak
                _req("GET", "http://x/api/poll?t=99#secret", 503),                # seen idle: weak
                _req("GET", "http://x/api/slow", None)]                           # still pending: ignored
    noise = {"requests": {"GET http://x/api/poll"}, "console": {"poll # failed"}, "storage": {"local:clock"}}
    signals, weak = live_session._signal_diff(
        before, after, requests, {"local:clock": 1, "local:b": 2}, {"local:clock": 2, "local:b": 3, "cookie:c": 4},
        True, True, noise, ORIGIN)
    assert signals == {
        "settled_before": True, "settled_after": True,
        "console_errors": ["TypeError: x is undefined"],
        "failed_requests": ["POST http://x/api/b -> 500"],
        "storage_added": ["cookie:c"], "storage_changed": ["local:b"],
        "controls_added": ["button:menu"], "controls_removed": ["button:close"],
    }
    assert weak == {
        "console_errors": ["poll 17 failed"],
        "failed_requests": ["GET http://ads.example/pixel -> net::ERR", "GET http://x/api/poll -> 503"],
        "storage_changed": ["local:clock"],
    }


def test_nothing_read_from_an_unsettled_page_is_trusted():
    before, after = _Obs(), _Obs(console=[{"type": "error", "text": "boom"}])
    signals, weak = live_session._signal_diff(before, after, [], {}, {}, True, False, {}, ORIGIN)
    assert signals == {"settled_before": True, "settled_after": False}
    assert weak == {"console_errors": ["boom"]}


def test_a_quiet_action_has_only_the_settled_flags():
    obs = _Obs(elements=[{"role": "button", "name": "Close"}])
    assert live_session._signal_diff(obs, obs, [], {}, {}, True, True, {}, ORIGIN) == (
        {"settled_before": True, "settled_after": True}, {})


class _MutatingPage:
    """A page whose DOM mutation count follows `counts`, then stays at the last one."""

    def __init__(self, counts):
        self.counts = list(counts)

    def evaluate(self, js):
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    def wait_for_timeout(self, ms):
        pass


def _resting_session(page, monkeypatch, max_ms=300):
    monkeypatch.setattr(live_session, "_REST_QUIET_MS", 50)
    monkeypatch.setattr(live_session, "_REST_MAX_MS", max_ms)
    sess = live_session.Session.__new__(live_session.Session)
    sess.page, sess._inflight = page, set()
    return sess


def test_a_page_that_stops_changing_rests(monkeypatch):
    assert _resting_session(_MutatingPage([1, 5, 9, 9]), monkeypatch)._rest() is True


def test_a_page_that_never_stops_changing_is_flagged_not_waited_on_forever(monkeypatch):
    import itertools
    page = _MutatingPage([0])
    counter = itertools.count()
    page.evaluate = lambda js: next(counter)
    assert _resting_session(page, monkeypatch, max_ms=150)._rest() is False


def test_a_request_in_flight_keeps_the_page_busy(monkeypatch):
    sess = _resting_session(_MutatingPage([3]), monkeypatch, max_ms=150)
    sess._inflight.add(1)
    assert sess._rest() is False


def test_the_log_line_names_errors_failures_and_an_unsettled_read():
    line = adp.describe_result_for_log({"result": {
        "verdict": "sent", "screen_was": "same_screen", "click": 0.1, "settle": 0.4, "reached_target_state": True,
        "signals": {"settled_before": True, "settled_after": False, "console_errors": ["a", "b"],
                    "failed_requests": ["GET /x -> 500"], "storage_added": ["cookie:x"]},
        "signals_weak": {"failed_requests": ["GET http://ads/p -> 0"]}}})
    assert "2 console error(s)" in line and "1 failed request(s)" in line
    assert "storage changed" in line and "UNSETTLED" in line and "1 weak signal(s)" in line


# ---- review fixes on #146: Copilot's comments and the 3-site signal audit -------------

def test_nothing_is_trusted_when_the_action_was_not_sent():
    # Copilot on #146: a drifted path or a failed click still produced trusted facts.
    before = _Obs(elements=[{"role": "button", "name": "Close"}])
    after = _Obs(elements=[], console=[{"type": "error", "text": "boom"}])
    signals, weak = live_session._signal_diff(before, after, [], {}, {"cookie:c": 1}, True, True, {}, ORIGIN,
                                              sent=False)
    assert signals == {"settled_before": True, "settled_after": True}
    assert weak == {"console_errors": ["boom"], "storage_added": ["cookie:c"], "controls_removed": ["button:close"]}


def test_controls_that_change_on_their_own_are_noise():
    # PrestaShop's home page carousel: its slide links come and go with no action.
    before = _Obs(elements=[{"role": "link", "name": "Slide 1"}, {"role": "button", "name": "Close"}])
    after = _Obs(elements=[{"role": "link", "name": "Slide 2"}])
    signals, weak = live_session._signal_diff(
        before, after, [], {}, {}, True, True, {"controls": {"link:slide 1", "link:slide 2"}}, ORIGIN)
    assert signals == {"settled_before": True, "settled_after": True, "controls_removed": ["button:close"]}
    assert weak == {"controls_added": ["link:slide 2"], "controls_removed": ["link:slide 1"]}


def test_a_malformed_url_in_the_product_is_its_own_request_not_a_third_party():
    # PrestaShop requests http://modules/... on every load: a broken relative URL.
    own = live_session._own_request
    assert own({"url": "http://modules/blockreassurance/parcel.svg"}, "http://127.0.0.1:8080")
    assert own({"url": "http://127.0.0.1:8080/api/x"}, "http://127.0.0.1:8080")
    assert not own({"url": "https://www.google-analytics.com/collect"}, "http://127.0.0.1:8080")
    assert not own({"url": "http://localhost:9999/x"}, "http://127.0.0.1:8080")


class _IdlePage:
    """A page whose controls follow `frames`, one per look, like a carousel."""

    def __init__(self, frames):
        self.frames = list(frames)

    def evaluate(self, js, arg=None):
        if js is live_session.ELEMENTS_JS:
            return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return {}

    def wait_for_timeout(self, ms):
        pass


class _Drained:
    def drain(self):
        return [], []


def test_the_idle_watch_learns_controls_that_come_and_go():
    sess = live_session.Session.__new__(live_session.Session)
    sess.page = _IdlePage([[{"role": "link", "name": "Slide 1"}], [{"role": "link", "name": "Slide 1"}],
                           [{"role": "link", "name": "Slide 2"}]])
    sess.col, sess._requests, sess._context = _Drained(), {}, None
    noise = sess._idle_noise()
    assert noise["controls"] == {"link:slide 1", "link:slide 2"}


def test_a_baseline_is_learned_only_for_a_state_the_replay_really_reached(monkeypatch):
    # Copilot on #146: a drifted first replay attached another page's noise to the state.
    ref = ref_mod.Reference(_ontology())
    sess = live_session.Session.__new__(live_session.Session)
    sess.reference, sess.base_url, sess._noise = ref, "http://app.example/", {}
    sess.seen_signatures, sess.entry_signature, sess.last_covered_by, sess.last_rest = set(), "", "", True
    sess.page, sess.col, sess._requests = None, None, {}
    monkeypatch.setattr(sess, "_reboot", lambda: None)
    monkeypatch.setattr(sess, "_actuate", lambda step: True)
    monkeypatch.setattr(sess, "_rest", lambda: True)
    monkeypatch.setattr(sess, "_storage", lambda: {})
    monkeypatch.setattr(sess, "_shot", lambda: None)
    monkeypatch.setattr(sess, "recover", lambda: "")
    watched = []
    monkeypatch.setattr(sess, "_idle_noise", lambda: watched.append(1) or {})
    elsewhere = _Obs(elements=[{"role": "button", "name": "Somewhere else"}])
    monkeypatch.setattr(sess, "_capture_expecting", lambda expected: elsewhere)
    monkeypatch.setattr(live_session, "capture", lambda page, col: elsewhere)
    sess.act("st02", "button:Back")
    assert watched == [] and "st02" not in sess._noise


def test_after_learning_a_baseline_the_state_is_reached_afresh(monkeypatch):
    # #146 audit rerun: PrestaShop's slider turned during the idle watch, so a read
    # taken after the watch no longer matched the state.
    ref = ref_mod.Reference(_ontology())
    ref._by_id["st02"]["signature"] = "/p2|button:back|"   # what the fake page below reads as
    sess = live_session.Session.__new__(live_session.Session)
    sess.reference, sess.base_url, sess._noise, sess._site = ref, "http://app.example/", {}, "http://app.example"
    sess.seen_signatures, sess.entry_signature, sess.last_covered_by, sess.last_rest = set(), "", "", True
    sess.page, sess.col, sess._requests = None, None, {}
    reboots = []
    monkeypatch.setattr(sess, "_reboot", lambda: reboots.append(1))
    monkeypatch.setattr(sess, "_actuate", lambda step: True)
    monkeypatch.setattr(sess, "_rest", lambda: True)
    monkeypatch.setattr(sess, "_storage", lambda: {})
    monkeypatch.setattr(sess, "_shot", lambda: None)
    monkeypatch.setattr(sess, "_idle_noise", lambda: {})
    monkeypatch.setattr(sess, "recover", lambda: "")
    page2 = _Obs(elements=[{"role": "button", "name": "Back", "locator": "#back"}])
    page2.url, page2.title = "http://app.example/p2", "Page 2"
    monkeypatch.setattr(sess, "_capture_expecting", lambda expected: page2)
    monkeypatch.setattr(live_session, "capture", lambda page, col: page2)
    first = sess.act("st02", "button:Back")
    assert len(reboots) == 2 and first["reached_target_state"] is True   # watched, then reached afresh
    reboots.clear()
    sess.act("st02", "button:Back")
    assert len(reboots) == 1                                              # baseline already known


# ---- Copilot on #152 ---------------------------------------------------------------------

def test_the_origin_match_is_exact_not_a_prefix():
    own = live_session._own_request
    assert own({"url": "https://example.com/api"}, "https://example.com")
    assert own({"url": "https://example.com:443/api"}, "https://example.com")       # default port
    assert not own({"url": "https://example.com.evil/x"}, "https://example.com")
    assert not own({"url": "http://127.0.0.1:80801/x"}, "http://127.0.0.1:8080")
    assert not own({"url": "http://[::1]/x"}, "http://127.0.0.1:8080")             # IPv6 isn't single-label


def test_a_cut_list_says_how_many_more_in_both_tiers_and_the_report():
    after = _Obs(console=[{"type": "error", "text": f"e{i}"} for i in range(8)])
    signals, weak = live_session._signal_diff(_Obs(), after, [], {}, {}, True, False, {}, ORIGIN)
    assert weak["console_errors"] == ["e0", "e1", "e2", "e3", "e4"] and weak["console_errors_more"] == 3
    html = adp._signals_html({"signals": signals, "signals_weak": weak})
    assert "and 3 more" in html


def test_a_failed_actions_weak_signals_are_in_the_report():
    entry = {"request": {"state": "st01", "control": "button:A"}, "result": {
        "verdict": "not_actuated", "signals": {"settled_before": True, "settled_after": True},
        "signals_weak": {"console_errors": ["boom"]}}}
    assert "boom" in adp.render_test_entry(entry)


# ---- saved sessions (issue #154) ----------------------------------------------------------

def test_every_fresh_context_is_loaded_from_the_saved_session():
    session = object.__new__(live_session.Session)
    session.base_url, session._browser, session._context = "http://127.0.0.1:3000", _SessionBrowser(), None
    session.session_file = "logged-in.json"
    session._open_fresh_page()
    session._reboot()
    assert [c.storage_state for c in session._browser.contexts] == ["logged-in.json", "logged-in.json"]


def test_without_a_session_contexts_start_empty():
    session = object.__new__(live_session.Session)
    session.base_url, session._browser, session._context, session.session_file = "http://x", _SessionBrowser(), None, None
    session._open_fresh_page()
    assert session._browser.contexts[0].storage_state is None


def test_a_missing_or_malformed_session_file_fails_loudly(tmp_path):
    import json as json_mod
    import pytest
    with pytest.raises(SystemExit, match="does not exist"):
        live_session.load_session_file(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="isn't valid JSON"):
        live_session.load_session_file(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json_mod.dumps({"cookies": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="isn't a Playwright session"):
        live_session.load_session_file(wrong)
    good = tmp_path / "logged-in.json"
    good.write_text(json_mod.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    assert live_session.load_session_file(good) == str(good)
    assert live_session.session_name(good) == "logged-in"


def test_the_map_records_which_session_it_was_made_with():
    data = _ontology()
    assert ref_mod.Reference(data).session_name == ""
    data["session"] = {"session_name": "logged-in"}
    assert ref_mod.Reference(data).session_name == "logged-in"


# ---- screens beyond the map (issue #157) -------------------------------------------------

def test_a_discovered_screen_is_a_map_state_with_its_controls_through_the_safety_gate():
    # Shaped like perceive's capture, which the safety gate reads (type, href, disabled).
    obs = _Obs(elements=[{"role": "button", "name": "Show orders", "tag": "button", "type": "", "href": "",
                          "disabled": False, "locator": "#orders"},
                         {"role": "button", "name": "Delete account", "tag": "button", "type": "", "href": "",
                          "disabled": False, "locator": "#delete"}])
    obs.title = "Orders"
    path = [{"role": "button", "name": "Account", "locator": "#account"}]
    found = live_session.discovery(obs, "/|menuitem:orders|", path, "st02", "button:Account", "http://x")
    assert found["id"] == live_session.discovery_id("/|menuitem:orders|") and found["id"].startswith("d")
    committing = {e["key"]: e["committing"] for e in found["elements"]}
    assert committing == {"button:Show orders": False, "button:Delete account": True}
    assert found["controls_offered"] == 1 and found["path"] == path and found["from_state"] == "st02"


def _acting_session(monkeypatch, after):
    ref = ref_mod.Reference(_ontology())
    sess = live_session.Session.__new__(live_session.Session)
    sess.reference, sess.base_url, sess._noise, sess._site = ref, "http://app.example/", {"st01": {}}, "http://app.example"
    sess.seen_signatures, sess.entry_signature, sess.last_covered_by, sess.last_rest = set(), "", "", True
    sess.page, sess.col, sess._requests = None, None, {}
    for name, fn in (("_reboot", lambda: None), ("_actuate", lambda step: True), ("_rest", lambda: True),
                     ("_storage", lambda: {}), ("_shot", lambda: None), ("recover", lambda: "")):
        monkeypatch.setattr(sess, name, fn)
    start = _Obs(elements=[{"role": "button", "name": "A", "locator": "#a"},
                           {"role": "button", "name": "Dead", "locator": "#dead"}])
    start.url = "http://app.example/"
    ref._by_id["st01"]["signature"] = live_session.signature(start)   # names are lowercased in a signature
    monkeypatch.setattr(sess, "_capture_expecting", lambda expected: start)
    monkeypatch.setattr(live_session, "capture", lambda page, col: after)
    return sess


def test_reaching_a_screen_the_map_lacks_records_it_and_a_mapped_one_does_not(monkeypatch):
    unmapped = _Obs(elements=[{"role": "button", "name": "Brand new", "locator": "#new"}])
    unmapped.url, unmapped.title = "http://app.example/new", "New"
    result = _acting_session(monkeypatch, unmapped).act("st01", "button:A")
    assert result["discovered"]["url"] == "http://app.example/new"
    assert result["discovered"]["path"][-1]["locator"] == "#a"        # the action is the last step
    mapped = _Obs(elements=[{"role": "button", "name": "Back", "locator": "#back"}])
    mapped.url = "http://app.example/p2"
    sess = _acting_session(monkeypatch, mapped)
    sess.reference.carried_signatures.add(live_session.signature(mapped))   # it's in the carried map
    assert "discovered" not in sess.act("st01", "button:A")


def test_the_driver_sees_a_discoverys_controls_the_first_time_and_then_just_its_id():
    # #158: the controls it may now act on, once; #157: never the full record.
    record = {"id": "d1234abcd", "controls_offered": 1, "in_run_map": True, "path": [{"name": "A"}],
              "elements": [{"key": "button:Go", "name": "Go", "committing": False},
                           {"key": "button:Delete", "name": "Delete", "committing": True}]}
    log = [{"round_reasoning": "r", "result": {"screen_was": "new_screen", "discovered": dict(record)}},
           {"round_reasoning": "r", "result": {"screen_was": "known_screen", "discovered": dict(record)}}]
    redacted = adp.redact_history_for_model(log)
    assert redacted[0]["result"]["discovered"] == {"id": "d1234abcd", "controls": ["button:Go"]}
    assert redacted[1]["result"]["discovered"] == {"id": "d1234abcd"}
    assert "elements" in log[0]["result"]["discovered"]           # output.json keeps the full record


# ---- acting on discovered screens (issue #158) -------------------------------------------

def _record(sig="/new|button:go|", steps=2):
    return {"id": live_session.discovery_id(sig), "signature": sig, "url": "http://app.example/new", "title": "New",
            "from_state": "st02", "via": "button:Back", "controls_offered": 1,
            "path": [{"role": "button", "name": f"S{i}", "locator": f"#s{i}"} for i in range(steps)],
            "elements": [{"key": "button:Go", "role": "button", "name": "Go", "locator": "#go", "committing": False},
                         {"key": "button:Buy", "role": "button", "name": "Buy", "locator": "#buy", "committing": True}]}


def test_a_discovered_screen_joins_the_runs_map_with_its_path_and_cleared_controls():
    ref = ref_mod.Reference(_ontology())
    record = _record()
    sid = ref.add_discovery(record, max_steps=6)
    assert sid == record["id"]
    assert (sid, "button:Go") in ref.pairs() and (sid, "button:Buy") not in ref.pairs()   # same gate as the map
    assert ref.plan_for(sid, "button:Go") == {"path": record["path"],
                                              "target": {"role": "button", "name": "Go", "locator": "#go"}}
    assert ref.controls_on(sid) == ["button:Go"] and ref.is_known(record["signature"])
    assert ref.add_discovery(record, max_steps=6) == sid                                  # adding twice is harmless
    assert record["signature"] not in ref.carried_signatures                             # still counted as a discovery


def test_a_mapped_screen_or_one_too_deep_does_not_join():
    ref = ref_mod.Reference(_ontology())
    mapped = _record(sig=ref._by_id["st02"]["signature"])
    assert ref.add_discovery(mapped, max_steps=6) is None
    assert ref.add_discovery(_record(sig="/deep|", steps=7), max_steps=6) is None


def test_a_test_on_a_discovered_screen_is_valid_once_it_joined(monkeypatch):
    ref = ref_mod.Reference(_ontology())
    sid = ref.add_discovery(_record(), max_steps=6)
    sess = live_session.Session.__new__(live_session.Session)
    sess.reference = ref
    monkeypatch.setattr(live_session, "_SESSION", sess)
    data = {"give_up": False, "reasoning": "go deeper", "candidate_tests": [
        _good_test(start=sid, steps=[{"do": "click", "role": "button", "name": "Go"}], predicted_screen="new_screen")]}
    assert adp.validate_casting_response(data) == []
    assert sess.is_start(sid) and sess.is_start("/#/anything") and not sess.is_start("nowhere")


# ---- starting from earlier runs' discoveries (issue #159) ----------------------------------

def test_a_screen_from_an_earlier_run_joins_as_carried_and_is_labelled():
    ref = ref_mod.Reference(_ontology())
    record = _record()
    sid = ref.add_discovery(record, max_steps=6, earlier_run=True)
    assert (sid, "button:Go") in ref.pairs()
    assert record["signature"] in ref.carried_signatures        # reaching it again isn't a new discovery
    assert f"{sid} (/new, found by an earlier run)" in ref.driver_briefing()


def test_earlier_discoveries_join_only_when_they_still_replay():
    ref = ref_mod.Reference(_ontology())
    good, gone = _record(sig="/a|button:go|"), _record(sig="/b|button:go|")
    mapped, deep = _record(sig=ref._by_id["st02"]["signature"]), _record(sig="/deep|", steps=7)
    session = type("S", (), {"reference": ref, "reaches": lambda self, path, sig: sig == good["signature"]})()
    outcome = live_session.join_earlier_discoveries(session, [gone, good, mapped, deep])
    assert outcome == {"joined": [good["id"]], "not_reached": [gone["id"]], "already_in_map": [mapped["id"]],
                       "too_deep": [deep["id"]]}
    assert (good["id"], "button:Go") in ref.pairs() and (gone["id"], "button:Go") not in ref.pairs()


def test_at_most_twenty_earlier_discoveries_are_checked_the_most_reached_first():
    ref = ref_mod.Reference(_ontology())
    records = [{**_record(sig=f"/p{i}|button:go|"), "times_reached": i} for i in range(25)]
    checked = []
    session = type("S", (), {"reference": ref, "reaches": lambda self, path, sig: checked.append(sig) or True})()
    assert len(live_session.join_earlier_discoveries(session, records)["joined"]) == 20
    assert checked[0] == "/p24|button:go|" and "/p0|button:go|" not in checked


def test_the_report_lists_the_screens_from_earlier_runs():
    html = adp.render_onboarding_section("S", {"earlier_discoveries": {"joined": ["d1"], "not_reached": ["d2"]}}, {})
    assert "Screens from earlier runs" in html and "joined:</strong> d1" in html and "not reached:</strong> d2" in html


def _session_with(tmp_path, cookies=(), storage=()):
    import json as json_mod
    path = tmp_path / "logged-in.json"
    path.write_text(json_mod.dumps({"cookies": list(cookies), "origins": [
        {"origin": "http://x", "localStorage": list(storage)}]}), encoding="utf-8")
    return path


def _jwt(claims):
    import base64
    import json as json_mod
    body = base64.urlsafe_b64encode(json_mod.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{body}.sig"


def test_an_expired_credential_cookie_stops_the_run_before_it_starts(tmp_path):
    # The milestone run (#227): the token cookie expired overnight, the page still looked
    # logged in, and the server's 500 was reported as a bug.
    import pytest
    path = _session_with(tmp_path, cookies=[
        {"name": "token", "value": "abc", "expires": 1000},
        {"name": "welcomebanner_status", "value": "dismiss", "expires": 1000},   # not a credential
    ])
    assert live_session.session_expiry(path, now=2000) == {"expired": ["cookie token"], "soon": []}
    with pytest.raises(SystemExit, match=r"has expired \(cookie token\)"):
        live_session.check_session_fresh(path, now=2000)


def test_a_jwt_in_storage_is_judged_by_its_exp_claim(tmp_path):
    path = _session_with(tmp_path, storage=[{"name": "auth", "value": _jwt({"exp": 5000})},
                                           {"name": "theme", "value": "dark"}])
    assert live_session.check_session_fresh(path, now=1000) is None
    assert "expires within 30 minutes (storage auth (its JWT))" in live_session.check_session_fresh(path, now=4000)
    assert live_session.session_expiry(path, now=6000)["expired"] == ["storage auth (its JWT)"]


def test_session_cookies_without_a_date_and_jwts_without_exp_pass(tmp_path):
    # A browser-session cookie (expires -1) and a JWT with no exp can't be judged by date;
    # WEB_GUI_SESSION_CHECK is the check for those.
    path = _session_with(tmp_path, cookies=[{"name": "sessionid", "value": "abc", "expires": -1}],
                         storage=[{"name": "token", "value": _jwt({"iat": 1})}])
    assert live_session.session_expiry(path, now=10**10) == {"expired": [], "soon": []}


def test_the_expiry_message_names_credentials_never_their_values(tmp_path):
    import pytest
    path = _session_with(tmp_path, cookies=[{"name": "sid", "value": "SECRET-VALUE", "expires": 1}])
    with pytest.raises(SystemExit) as stopped:
        live_session.check_session_fresh(path, now=2)
    assert "SECRET-VALUE" not in str(stopped.value) and "cookie sid" in str(stopped.value)


def _ran(screen_after="/profile||page", reached=True, verdict="sent", settled=True, **signals):
    return {"result": {"reached_target_state": reached, "verdict": verdict, "screen_after": screen_after,
                       "signals": {"settled_before": settled, "settled_after": settled, **signals}}}


def test_a_replay_with_the_same_screen_and_trusted_signals_reproduces():
    failed = ["GET http://127.0.0.1:3000/profile -> 500"]
    original = _ran(failed_requests=failed)
    replayed = {**_ran(failed_requests=failed), "signals_weak": {"failed_requests": ["GET https://cdn/x -> 404"]}}
    assert adp.compare_replay(original, replayed)["same"] is True


def test_a_replay_missing_the_failed_request_doesnt_reproduce():
    # The milestone run (#177): a stale session's 500, gone with a fresh session.
    same = adp.compare_replay(_ran(failed_requests=["GET http://127.0.0.1:3000/profile -> 500"]), _ran())
    assert same["same"] is False and "failed_requests no longer has GET http://127.0.0.1:3000/profile -> 500" in same["detail"]
    moved = adp.compare_replay(_ran(), _ran(screen_after="/login||page"))
    assert moved["same"] is False and "landed on /login, not /profile" in moved["detail"]
    changed = adp.compare_replay(_ran(screen_after="/profile||500 error", failed_requests=["GET /profile -> 500"]),
                                 _ran(screen_after="/profile|button:save|user profile"))
    assert changed["detail"] == ("/profile now shows the controls button:save; /profile no longer shows the "
                                 "landmarks 500 error; /profile now shows the landmarks user profile; "
                                 "failed_requests no longer has GET /profile -> 500")


def test_a_replay_that_couldnt_act_or_rest_says_neither_way():
    assert adp.compare_replay(_ran(), _ran(reached=False))["same"] is None
    assert adp.compare_replay(_ran(reached=False), _ran())["original_ran"] is False
    assert "original_ran" not in adp.compare_replay(_ran(), _ran(reached=False))
    assert adp.compare_replay(_ran(), _ran(verdict="not_actuated"))["same"] is None
    assert adp.compare_replay(_ran(), _ran(settled=False))["same"] is None
    assert adp.compare_replay(_ran(), {"skipped": True, "skip_reason": "not a pair"})["same"] is None


def test_replays_are_blocked_while_the_saved_session_has_expired(tmp_path, monkeypatch):
    path = _session_with(tmp_path, cookies=[{"name": "token", "value": "abc", "expires": 1}])
    monkeypatch.setattr(live_session, "live", lambda: type("S", (), {"session_file": str(path)})())
    assert "has expired (cookie token)" in live_session.replay_blocker()
    monkeypatch.setattr(live_session, "live", lambda: type("S", (), {"session_file": None})())
    assert live_session.replay_blocker() is None


def test_saved_sessionstorage_goes_back_into_every_fresh_context(tmp_path):
    # #228: restored by an init script, since Playwright's storage_state can't.
    path = _session_with(tmp_path)
    assert live_session.session_storage_script(path) is None
    import json as json_mod
    data = json_mod.loads(path.read_text(encoding="utf-8"))
    data["origins"][0]["sessionStorage"] = [{"name": "bid", "value": "6\"'</script>"}]
    path.write_text(json_mod.dumps(data), encoding="utf-8")
    script = live_session.session_storage_script(path)
    assert json_mod.dumps({"http://x": [["bid", "6\"'</script>"]]}) in script
    assert "if (sessionStorage.length) return;" in script   # never overwrites what the app wrote


def test_a_jwt_in_saved_sessionstorage_is_judged_by_its_exp_claim_too(tmp_path):
    import json as json_mod
    path = _session_with(tmp_path)
    data = json_mod.loads(path.read_text(encoding="utf-8"))
    data["origins"][0]["sessionStorage"] = [{"name": "auth", "value": _jwt({"exp": 5})}]
    path.write_text(json_mod.dumps(data), encoding="utf-8")
    assert live_session.session_expiry(path, now=10)["expired"] == ["storage auth (its JWT)"]


def test_each_fresh_context_gets_the_sessionstorage_script():
    session = object.__new__(live_session.Session)
    session.base_url, session._browser, session._context = "http://x", _SessionBrowser(), None
    session.session_file, session._session_storage_js = "logged-in.json", "restore();"
    session._open_fresh_page()
    session._reboot()
    assert [c.init_scripts[-1] for c in session._browser.contexts] == ["restore();", "restore();"]


def test_a_session_check_that_isnt_a_product_path_is_refused(monkeypatch):
    # #243: Git Bash turned /profile into C:/Program Files/Git/profile, Juice Shop answered
    # 200 for it, and the check passed without checking anything.
    import pytest
    for bad in ("C:/Program Files/Git/profile", "profile", "http://evil.test/profile", "//evil.test/x"):
        monkeypatch.setenv("WEB_GUI_SESSION_CHECK", bad)
        with pytest.raises(SystemExit, match="isn't a path on the product"):
            live_session.session_check_path()
    for good in ("/profile", "/rest/user/whoami?x=1:2"):
        monkeypatch.setenv("WEB_GUI_SESSION_CHECK", good)
        assert live_session.session_check_path() == good
    monkeypatch.delenv("WEB_GUI_SESSION_CHECK")
    assert live_session.session_check_path() == ""


# ---- starting a test as a new tab (issue #249) ---------------------------------------------

def test_validate_checks_start_as(monkeypatch):
    monkeypatch.setattr(live_session, "_SESSION", object())     # a session is live
    monkeypatch.setattr(live_session, "has_session", lambda: True)
    batch = lambda **kw: {"give_up": False, "reasoning": "r", "candidate_tests": [_good_test(**kw)]}
    assert adp.validate_casting_response(batch(start_as="new_tab")) == []
    assert any("start_as must be one of" in e for e in adp.validate_casting_response(batch(start_as="incognito")))
    monkeypatch.setattr(live_session, "has_session", lambda: False)
    assert any("no saved session" in e for e in adp.validate_casting_response(batch(start_as="new_tab")))


def test_a_new_tab_context_gets_no_sessionstorage_but_the_same_tab_does():
    session = object.__new__(live_session.Session)
    session.base_url, session._browser, session._context = "http://x", _SessionBrowser(), None
    session.session_file, session._session_storage_js = "logged-in.json", "restore();"
    session._start_as = "new_tab"
    session._reboot()
    session._start_as = "same_tab"
    session._reboot()
    new_tab, same_tab = session._browser.contexts
    assert "restore();" not in new_tab.init_scripts and new_tab.storage_state == "logged-in.json"
    assert "restore();" in same_tab.init_scripts


def test_act_marks_a_new_tab_test_and_goes_back_to_the_same_tab_after(monkeypatch):
    session = object.__new__(live_session.Session)
    seen = []
    def fake_act(start, steps):
        seen.append(session._start_as)
        return {"action": f"{start} :: {steps[0]['role']}:{steps[0]['name']}", "verdict": "sent"}
    session._act = fake_act
    step = [{"do": "click", "role": "button", "name": "A"}]
    assert session.act_steps("st01", step, "new_tab")["started_as"] == "new_tab"
    assert "started_as" not in session.act_steps("st01", step)
    assert seen == ["new_tab", "same_tab"] and session._start_as == "same_tab"


def test_a_new_tab_test_is_its_own_action_and_says_so(monkeypatch):
    class Live:
        def is_start(self, start):
            return True

        def act_steps(self, start, steps, start_as, test_number=None):
            r = _result()
            return {**r, "started_as": start_as} if start_as != "same_tab" else r
    monkeypatch.setattr(live_session, "live", lambda: Live())
    entry = adp.execute_test({**_good_test(), "start_as": "new_tab"}, 1)
    assert entry["request"]["start_as"] == "new_tab"
    assert entry["outcome"]["action_id"].endswith("(as a new tab)")
    assert "start_as" not in adp.execute_test(_good_test(), 2)["request"]
    assert "(as a new tab)" in adp.describe_test_for_log({**_good_test(), "start_as": "new_tab"})


def test_a_start_the_run_doesnt_know_is_a_result_not_a_retry(monkeypatch):
    monkeypatch.setattr(live_session, "live", lambda: type("L", (), {"is_start": lambda self, s: False})())
    entry = adp.execute_test(_good_test(start="basket"), 3)
    assert entry["skipped"] and "neither a route on the site" in entry["skip_reason"]
    assert entry["request"] == {"start": "basket", "steps": [{"do": "click", "role": "button", "name": "A"}]}


def test_a_test_cast_before_310_still_runs_as_one_step(monkeypatch):
    seen = {}

    class Live:
        def is_start(self, start):
            return True

        def act_steps(self, start, steps, start_as, test_number=None):
            seen.update(start=start, steps=steps)
            return _result()
    monkeypatch.setattr(live_session, "live", lambda: Live())
    adp.execute_test({"state_id": "st01", "control_key": "textbox:Search", "predicted_screen": "same_screen",
                      "predicted_outcome": "x"}, 1)
    assert seen == {"start": "st01", "steps": [{"do": "fill", "role": "textbox", "name": "Search"}]}


def test_the_schema_doc_and_the_carried_map_are_folded_in_the_report():
    # #251: each runs to hundreds of lines and pushed the checkpoints far down the page.
    import re
    html = adp.render_onboarding_section("SCHEMA", {"carried_map": "st01 :: button:A", "baseline": "ok"}, {})
    for title in ("What the Driver was told", "Carried map (a guide to the screens)"):
        assert re.search(r'<details class="fold exhibit">\s*<summary>' + re.escape(title) + "</summary>", html)
    assert "<details open" not in html


def test_a_map_saved_with_a_users_email_matches_any_user_once_loaded():
    # #303: the basket's signature held the user's email, so a map made as one throwaway
    # user never matched a run logged in as another. The session rewrites a loaded map's signatures.
    data = _ontology()
    data["states"][1]["signature"] = "/|button:checkout|your basket (qes-147eb336@example.test)"
    ref = ref_mod.Reference(data)
    ref.rewrite_signatures(live_session.impersonal)
    assert ref.is_known("/|button:checkout|your basket (<email>)")
    assert "/|button:checkout|your basket (<email>)" in ref.carried_signatures
    assert not any("@" in s for s in ref.known_signatures)


def test_the_browser_never_leaves_the_site_even_through_a_redirect():
    # #308: "./redirect?to=https://github.com/..." is on the site, so the safety gate let
    # it through, and Juice Shop sent the logged-in test browser to GitHub.
    site = "http://127.0.0.1:3000"
    go = live_session.off_site_target
    assert go("https://github.com/x", 0, None, site) == "https://github.com/x"
    assert go(f"{site}/redirect?to=https://github.com/x", 302, "https://github.com/x", site) == "https://github.com/x"
    assert go(f"{site}/a", 302, "/b", site) is None                     # a redirect on the site is fine
    assert go(f"{site}/#/about", 200, None, site) is None
    assert go("http://localhost:3000/", 0, None, site) == "http://localhost:3000/"   # another origin is another site


class _Cdp:
    def __init__(self):
        self.sent = []

    def send(self, method, params):
        self.sent.append((method, params["requestId"]))


def _paused(url, frame="main", status=None, location=None):
    event = {"requestId": url, "request": {"url": url}, "frameId": frame}
    if status is not None:
        event["responseStatusCode"] = status
        event["responseHeaders"] = [{"name": "Location", "value": location}] if location else []
    return event


def test_the_guard_stops_the_main_frame_leaving_the_site_and_lets_the_rest_through():
    session = object.__new__(live_session.Session)
    session._site, session.blocked_off_site = "http://127.0.0.1:3000", []
    cdp = _Cdp()
    for event in (_paused("http://127.0.0.1:3000/"), _paused("http://127.0.0.1:3000/", status=200),
                  _paused("http://127.0.0.1:3000/redirect?to=https://github.com/j", status=302,
                          location="https://github.com/j"),
                  _paused("https://github.com/k"),
                  _paused("https://www.youtube.com/embed/x", frame="an-embed")):
        session._on_document(cdp, "main", event)
    assert [m for m, _ in cdp.sent] == ["Fetch.continueRequest", "Fetch.continueRequest", "Fetch.failRequest",
                                         "Fetch.failRequest", "Fetch.continueRequest"]
    assert session.blocked_off_site == ["https://github.com/j", "https://github.com/k"]


def test_every_page_of_every_fresh_context_is_guarded():
    session = object.__new__(live_session.Session)
    session.base_url = "http://127.0.0.1:3000"
    session._browser = _SessionBrowser()
    session._context = None
    session._open_fresh_page()
    context = session._browser.contexts[0]
    [patterns] = context.guarded
    assert [p["requestStage"] for p in patterns["patterns"]] == ["Request", "Response"]
    assert all(p["resourceType"] == "Document" for p in patterns["patterns"])
    assert context.handlers["page"] == session._guard_page      # a tab a click opens is guarded too
    context.handlers["page"](session.page)                       # the event fires for this page too
    assert len(context.guarded) == 1, "guarded once"


def test_a_blocked_trip_off_the_site_shows_in_the_log_and_the_report():
    entry = {"test_number": 4, "request": {"state": "st07", "control": "link:GitHub"}, "predicted_outcome": "p",
             "predicted_screen": "new_screen", "actual_screen": "new_screen", "prediction_matched": True,
             "result": {"verdict": "sent", "reached_target_state": True, "screen_was": "new_screen", "settle": 1,
                        "blocked_off_site": ["https://github.com/juice-shop/juice-shop"]}}
    assert "stopped from leaving the site for https://github.com/juice-shop/juice-shop" in \
        adp.describe_result_for_log(entry)
    assert "stopped from leaving the site</span> https://github.com/juice-shop/juice-shop" in adp.render_test_entry(entry)


def test_the_log_line_counts_weak_signals_that_were_cut_short():
    # A cut list carries an int "<key>_more" beside it; counting it with len() crashed (#308's check).
    entry = {"result": {"verdict": "sent", "screen_was": "new_screen", "settle": 1,
                        "signals_weak": {"controls_added": ["a", "b"], "controls_added_more": 263}}}
    assert "2 weak signal(s)" in adp.describe_result_for_log(entry)


def test_a_request_our_guard_stopped_is_not_the_product_failing():
    session = object.__new__(live_session.Session)
    blocked = type("R", (), {"failure": "net::ERR_BLOCKED_BY_CLIENT"})()
    real = type("R", (), {"failure": "net::ERR_CONNECTION_REFUSED"})()
    session._inflight, session._requests = {id(blocked), id(real)}, {id(blocked): {"url": "a"}, id(real): {"url": "b"}}
    session._on_request_failed(blocked)
    session._on_request_failed(real)
    assert id(blocked) not in session._requests and session._requests[id(real)]["status"] == 0
    assert session._inflight == set()


# ---- a test is a start and steps on the live page (#310) ----------------------------------

def _stepping_session(monkeypatch, on_page, tags=None, route="/#/"):
    """A session whose page has the elements in `on_page`, at `route`; records what was
    pressed and typed."""
    sess = live_session.Session.__new__(live_session.Session)
    sess._site, sess.base_url, sess.blocked_off_site = "http://app.example", "http://app.example/", []
    sess.careful = tags if tags is not None else dict(careful_mod.NOTHING)
    pressed = []
    monkeypatch.setattr(sess, "_find_live", lambda role, name, nth=1: next(
        (e for e in on_page if e["role"] == role and e["name"] == name), None))
    monkeypatch.setattr(sess, "_actuate", lambda step: pressed.append(step) or True)
    monkeypatch.setattr(sess, "_fill", lambda role, name, css, value: pressed.append({"filled": name, "value": value}) or True)
    monkeypatch.setattr(sess, "_page_route", lambda: route)
    return sess, pressed


_ON_PAGE = [{"role": "button", "name": "Next page", "locator": "#n"},
            {"role": "button", "name": "Checkout", "locator": "#c"},
            {"role": "button", "name": "Logout", "locator": "#out"},
            {"role": "searchbox", "name": "Search", "locator": "#s"},
            {"role": "textbox", "name": "Quantity", "locator": "#q"}]


def test_testing_fully_any_step_may_run_except_logging_out(monkeypatch):
    # #299: the default. Checkout, typing -1 into a quantity, any route.
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE)
    assert sess._do_step({"do": "click", "role": "button", "name": "Checkout"})["status"] == "done"
    assert sess._do_step({"do": "fill", "role": "textbox", "name": "Quantity", "value": "-1"})["status"] == "done"
    assert pressed[-1] == {"filled": "Quantity", "value": "-1"}
    assert sess._do_step({"do": "goto", "value": "/#/payment"})["status"] == "done"
    assert sess._do_step({"do": "click", "role": "button", "name": "Ghost"})["status"] == "not_found"
    for step in ({"do": "click", "role": "button", "name": "Logout"}, {"do": "goto", "value": "/logout"}):
        refused = sess._do_step(step)
        assert refused["status"] == "refused" and "ends the session" in refused["detail"]
    assert sess._do_step({"do": "back"})["status"] == "done" and pressed[-1] == {"back": True}


def test_where_tagged_careful_the_read_only_gate_decides(monkeypatch):
    sess, pressed = _stepping_session(monkeypatch, _ON_PAGE, tags=dict(careful_mod.EVERYTHING))
    assert sess._do_step({"do": "click", "role": "button", "name": "Next page"})["status"] == "done"
    refused = sess._do_step({"do": "click", "role": "button", "name": "Checkout"})
    assert refused["status"] == "refused" and "tagged careful" in refused["detail"] and "mutating verb" in refused["detail"]
    assert sess._do_step({"do": "fill", "role": "searchbox", "name": "Search", "value": "apple"})["status"] == "done"
    assert pressed[-1] == {"filled": "Search", "value": "apple"}        # the Driver's value, not "test"
    assert sess._do_step({"do": "fill", "role": "textbox", "name": "Quantity", "value": "-1"})["status"] == "refused"
    # Careful only on one route: the same click runs elsewhere.
    tags = {"everything": False, "routes": ["/#/basket"], "controls": []}
    on_basket, _ = _stepping_session(monkeypatch, _ON_PAGE, tags=tags, route="/#/basket")
    assert on_basket._do_step({"do": "click", "role": "button", "name": "Checkout"})["status"] == "refused"
    elsewhere, _ = _stepping_session(monkeypatch, _ON_PAGE, tags=tags, route="/#/search")
    assert elsewhere._do_step({"do": "click", "role": "button", "name": "Checkout"})["status"] == "done"
    assert elsewhere._do_step({"do": "goto", "value": "/#/basket"})["status"] == "done"   # a GET, read-only


def test_a_session_nobody_set_up_is_careful_everywhere():
    sess = live_session.Session.__new__(live_session.Session)
    assert getattr(sess, "careful", careful_mod.EVERYTHING)["everything"]


def test_steps_read_as_labels_and_replay_as_path_steps():
    label = live_session._step_label
    assert label({"do": "click", "role": "button", "name": "Next"}) == "button:Next"
    assert label({"do": "fill", "role": "textbox", "name": "Coupon", "value": "-1"}) == "textbox:Coupon = '-1'"
    assert label({"do": "goto", "value": "/#/basket"}) == "goto /#/basket" and label({"do": "back"}) == "back"
    sess = live_session.Session.__new__(live_session.Session)
    sess.base_url = "http://app.example/"
    assert live_session._replay_step({"do": "goto", "value": "#/basket"}, {}, sess) == {"goto": "http://app.example/#/basket"}
    assert live_session._replay_step({"do": "fill", "role": "textbox", "name": "Q", "value": "2"}, {}, sess) == \
        {"role": "textbox", "name": "Q", "value": "2"}


def test_a_screen_reached_by_a_route_and_back_joins_the_map_too():
    # #310: a path can start with a route and end with "back", so its last step has no locator.
    ref = ref_mod.Reference(_ontology())
    record = {**_record(), "from_state": "/#/about", "via": "back",
              "path": [{"goto": "http://app.example/#/about"}, {"back": True}]}
    sid = ref.add_discovery(record, max_steps=6)
    assert sid and ref._paths[sid] == record["path"]
    assert ref.transitions[-1]["action"]["target"] == ""


def test_the_log_says_why_nothing_ran():
    entry = {"result": {"verdict": "not_actuated", "steps": [
        {"do": "click", "role": "button", "name": "Checkout", "status": "refused"}]}}
    assert adp.describe_result_for_log(entry) == "NOT RUN - button:Checkout: refused"
    assert "never reached its start" in adp.describe_result_for_log({"result": {"verdict": "not_actuated"}})


def test_an_element_without_a_name_can_be_picked_by_its_place(monkeypatch):
    # #310's run: the Driver wanted "link:" (a product image), and an empty name was refused.
    assert adp.validate_casting_response({"give_up": False, "reasoning": "r", "candidate_tests": [
        _good_test(steps=[{"do": "click", "role": "link", "name": "", "nth": 3}])]}) == []
    sess = live_session.Session.__new__(live_session.Session)
    page = [{"role": "link", "name": "", "locator": f"#img{i}"} for i in range(1, 5)] + \
           [{"role": "link", "name": "About", "locator": "#about"}]
    sess.page = type("P", (), {"evaluate": lambda self, js: page})()
    assert sess._find_live("link", "", 3)["locator"] == "#img3"
    assert sess._find_live("link", "")["locator"] == "#img1"
    assert sess._find_live("link", "", 9) is None
    assert sess._find_live("link", "about")["locator"] == "#about"
    assert live_session._step_label({"do": "click", "role": "link", "name": "", "nth": 3}) == "link: #3"

