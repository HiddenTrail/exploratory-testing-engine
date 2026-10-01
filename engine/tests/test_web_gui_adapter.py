"""The web-GUI adapter's pure parts: reading the carried reference into an action space,
the outcome envelope, and casting validation. No browser and no model - the live session is
exercised only behind a real run."""

from engine import outcome
from engine.adapters.web_gui import adapter as adp
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


def test_reference_briefing_lists_the_action_space_only():
    briefing = ref_mod.Reference(_ontology()).driver_briefing()
    assert "st01 :: button:A" in briefing and "st02 :: button:Back" in briefing
    assert "button:Buy" not in briefing                    # the committing control is never offered


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
    base = {"linked_hypothesis": "", "oracle_claim_id": "", "state_id": "st01", "control_key": "button:A",
            "predicted_screen": "known_screen", "predicted_outcome": "goes to page 2"}
    base.update(kw)
    return base


def test_validate_accepts_a_good_round_shape_only():
    # No live session -> pairs check is skipped, shape must still pass.
    assert adp.validate_casting_response({"give_up": False, "reasoning": "r",
                                          "candidate_tests": [_good_test()]}) == []


def test_validate_rejects_bad_prediction_and_missing_fields():
    errs = adp.validate_casting_response({"give_up": False, "reasoning": "r", "candidate_tests": [
        _good_test(predicted_screen="teleport"), {"state_id": "st01"}]})
    assert any("predicted_screen" in e for e in errs)
    assert any("missing" in e for e in errs)


def test_validate_allows_give_up_with_no_tests():
    assert adp.validate_casting_response({"give_up": True, "reasoning": "done", "candidate_tests": []}) == []


def test_validate_enforces_the_carried_map_when_a_session_is_live(monkeypatch):
    monkeypatch.setattr(live_session, "valid_pairs", lambda: {("st01", "button:A")})
    ok = adp.validate_casting_response({"give_up": False, "reasoning": "r",
                                        "candidate_tests": [_good_test()]})
    assert ok == []
    bad = adp.validate_casting_response({"give_up": False, "reasoning": "r",
                                         "candidate_tests": [_good_test(control_key="button:Ghost")]})
    assert any("not a (state, control) pair" in e for e in bad)


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

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _SessionBrowser:
    def __init__(self):
        self.contexts = []

    def new_context(self, viewport=None):
        self.contexts.append(_SessionContext())
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
        self.url, self.headings, self.text = "http://x/#/", [], ""
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
