"""The sweep (issue #276): every reachable action once, as the same tab and as a new tab,
and the problems the harness observed, deduplicated. No browser: the session is faked."""

from engine.adapters.web_gui import sweep


def _result(route="/#/basket", console=(), failed=(), weak_failed=(), reached=True):
    return {"reached_target_state": reached, "verdict": "sent", "screen_after": f"{route}|button:x|",
            "signals": {"console_errors": list(console), "failed_requests": list(failed)},
            "signals_weak": {"failed_requests": list(weak_failed)}}


def test_a_results_problems_are_keyed_so_repeats_collapse():
    found = sweep.problems_in(_result(
        console=["ERROR TypeError: Cannot read properties of null (reading 'Products')\n    at x (main.js:1)"],
        failed=["GET http://127.0.0.1:3000/rest/basket/6?x=1 -> 500"], weak_failed=["GET https://cdn.example/a.js -> 404"]))
    assert found == [
        {"type": "console_error", "pattern": "ERROR TypeError: Cannot read properties of null (reading 'Products')",
         "tier": "trusted"},
        {"type": "failed_request", "pattern": "GET /rest/basket/6 -> 500", "tier": "trusted"},
        {"type": "failed_request", "pattern": "GET /a.js -> 404", "tier": "weak"},
    ]


class _Reference:
    def __init__(self, pairs):
        self._pairs = set(pairs)

    def pairs(self):
        return self._pairs


class _Session:
    """Answers act() from a table; a discovered screen joins the reference after its first act."""

    def __init__(self, reference, answers, discovers=None):
        self.reference, self.answers, self.discovers, self.calls = reference, answers, discovers, []

    def act(self, state_id, control, start_as="same_tab"):
        self.calls.append((state_id, control, start_as))
        if self.discovers and (state_id, control) == self.discovers[0]:
            self.reference._pairs.add(self.discovers[1])
        return self.answers.get((state_id, control, start_as), _result())


def test_the_sweep_runs_every_pair_both_ways_and_follows_discoveries():
    ref = _Reference([("st01", "button:Cart"), ("st02", "menuitem:Profile")])
    session = _Session(ref, {
        ("st01", "button:Cart", "new_tab"): _result(console=["ERROR TypeError: null 'Products'"]),
        ("st02", "menuitem:Profile", "same_tab"): _result(route="/profile", failed=["GET http://h/profile -> 403"]),
        ("st02", "menuitem:Profile", "new_tab"): _result(route="/profile", failed=["GET http://h/profile -> 403"]),
    }, discovers=(("st01", "button:Cart"), ("d1", "button:Checkout")))
    out = sweep.sweep(session, ref, new_tab=True, max_actions=100, log=lambda *a: None, follow_discoveries=True)
    assert [c[:2] for c in session.calls[::2]] == [("st01", "button:Cart"), ("st02", "menuitem:Profile"),
                                                   ("d1", "button:Checkout")]
    by_pattern = {p["pattern"]: p for p in out["problems"]}
    tab = by_pattern["ERROR TypeError: null 'Products'"]
    assert tab["new_tab_only"] is True and tab["start_as"] == ["new_tab"]
    forbidden = by_pattern["GET /profile -> 403"]
    assert "new_tab_only" not in forbidden and forbidden["times"] == 2 and forbidden["routes"] == ["/profile"]
    assert [p["id"] for p in out["problems"]] == ["P01", "P02"]


def test_actions_that_didnt_reach_their_state_are_listed_and_the_cap_holds():
    ref = _Reference([("st0%d" % i, "button:A") for i in range(5)])
    session = _Session(ref, {("st00", "button:A", "same_tab"): _result(reached=False)})
    out = sweep.sweep(session, ref, new_tab=False, max_actions=3, log=lambda *a: None)
    assert out["actions_run"] == 3 and out["pairs_left"] == 2
    assert out["unreached"] == ["st00 :: button:A (same_tab)"]


def test_discoveries_are_only_followed_on_request():
    # Juice Shop's language switch "discovers" a translated copy of every screen.
    ref = _Reference([("st01", "button:Cart")])
    session = _Session(ref, {}, discovers=(("st01", "button:Cart"), ("d1", "button:Checkout")))
    sweep.sweep(session, ref, new_tab=False, max_actions=10, log=lambda *a: None)
    assert session.calls == [("st01", "button:Cart", "same_tab")]
