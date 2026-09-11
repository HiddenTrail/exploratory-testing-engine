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
    base = {"linked_hypothesis": "", "state_id": "st01", "control_key": "button:A",
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
