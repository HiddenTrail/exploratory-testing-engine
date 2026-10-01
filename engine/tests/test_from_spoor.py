"""The Spoor-map converter (issue #113), with fake page captures in place of a live
browser: replay paths, merging, dropping unstable pages, name matching, and the
safety gate. No browser, no LLM."""

from engine.adapters.web_gui.from_spoor import convert
from perceive import Observation  # web-recon, on the path via engine.adapters.web_gui.session

URL = "http://127.0.0.1:3000"


def _button(name, locator):
    return {"role": "button", "name": name, "locator": locator, "tag": "button", "href": "", "type": "button"}


# What the browser shows after each path, keyed by the path's step names.
PAGES = {
    (): Observation(url=URL + "/", title="Shop", headings=["welcome"],
                    elements=[_button("school Help getting started", "#help"), _button("Close Banner", "#close"),
                              _button("Delete account", "#del")]),
    ("Help getting started",): Observation(url=URL + "/", title="Shop", headings=["help"],
                                           elements=[_button("Next", "#next")]),
    ("Close Banner",): Observation(url=URL + "/", title="Shop", headings=["help"],   # same page as the one above
                                   elements=[_button("Next", "#next")]),
}


def _exploration(extra_transitions=()):
    return {
        "states": [{"id": "S0", "actions": [{"role": "button", "name": n} for n in
                                            ("Help getting started", "Close Banner", "Delete account")]},
                   {"id": "S1", "actions": [{"role": "button", "name": "Next"}]}, {"id": "S2"}, {"id": "S3"}],
        "transitions": [
            {"from": "S0", "to": "S1", "action": {"role": "button", "name": "Help getting started"}},
            {"from": "S0", "to": "S2", "action": {"role": "button", "name": "Close Banner"}},
            {"from": "S0", "to": "S3", "action": {"role": "button", "name": "Delete account"}},
            {"from": "S0", "to": "S0", "action": {"role": "button", "name": "Close Banner"}},
            *extra_transitions,
        ],
    }


def _observe(path):
    return PAGES.get(tuple(step["name"] for step in path))


def test_paths_are_replayed_and_pages_with_one_signature_are_merged():
    ontology, report = convert(_exploration(), URL, _observe)
    assert ontology["schema"] == "web-recon/1" and ontology["target"]["url"] == URL
    # S1 and S2 show the same page, so they become one state; the self-loop is dropped.
    assert [s["id"] for s in ontology["states"]] == ["st01", "st02"]
    assert [(t["source"], t["dest"], t["action"]["element_key"]) for t in ontology["transitions"]] == [
        ("st01", "st02", "button:school Help getting started"),
        ("st01", "st02", "button:Close Banner"),
    ]


def test_a_spoor_name_can_match_a_longer_dom_name():
    # "Help getting started" in Spoor is "school Help getting started" to web-recon.
    ontology, _ = convert(_exploration(), URL, _observe)
    step = ontology["transitions"][0]["action"]
    assert step["target"] == "#help"


def test_a_destructive_step_is_refused_and_its_control_marked_committing():
    ontology, report = convert(_exploration(), URL, _observe)
    assert "button:Delete account" in report["refused"]
    delete = next(e for e in ontology["states"][0]["elements"] if e["name"] == "Delete account")
    assert delete["committing"] is True
    help_button = next(e for e in ontology["states"][0]["elements"] if e["name"] == "school Help getting started")
    assert help_button["committing"] is False


def test_an_ambiguous_name_is_refused():
    pages = dict(PAGES)
    pages[()] = Observation(url=URL + "/", title="Shop", headings=["welcome"],
                            elements=[_button("Juice A", "#a"), _button("Juice B", "#b")])
    exploration = {"states": [{"id": "S0"}, {"id": "S1"}],
                   "transitions": [{"from": "S0", "to": "S1", "action": {"role": "button", "name": "Juice"}}]}
    ontology, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    assert report["refused"] == ["button:Juice"] and ontology["transitions"] == []


def test_a_page_that_doesnt_replay_is_dropped():
    def observe(path):
        return None if path else PAGES[()]
    ontology, report = convert(_exploration(), URL, observe)
    assert [s["id"] for s in ontology["states"]] == ["st01"]
    assert set(report["dropped_unstable"]) == {"S1", "S2"}


def test_a_control_spoor_couldnt_reach_is_left_out():
    # Issue #121: a modal dialog hides the page behind it from Spoor, but web-recon's DOM
    # capture still lists those controls. Offering them meant clicking the backdrop.
    pages = dict(PAGES)
    pages[()] = Observation(url=URL + "/", title="Shop", headings=["welcome"],
                            elements=[_button("Close Banner", "#close"), _button("Open Sidenav", "#nav")])
    exploration = {"states": [{"id": "S0", "actions": [{"role": "button", "name": "Close Banner"}]}],
                   "transitions": []}
    ontology, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    by_name = {e["name"]: e["committing"] for e in ontology["states"][0]["elements"]}
    assert by_name == {"Close Banner": False, "Open Sidenav": True}
    assert report["hidden_controls"] == 1


def test_a_control_spoor_skipped_is_left_out():
    pages = {(): Observation(url=URL + "/", title="Shop", headings=["x"], elements=[_button("Next page", "#n")])}
    exploration = {"states": [{"id": "S0", "actions": [{"role": "button", "name": "Next page"}]}],
                   "transitions": [],
                   "skipped": [{"from": "S0", "action": {"role": "button", "name": "Next page"},
                                "reason": "blocked by an unresolved layer: div"}]}
    ontology, _ = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    assert ontology["states"][0]["elements"][0]["committing"] is True


def test_map_errors_accepts_the_format_and_names_what_changed():
    # Issue #144: the contract with Spoor's saved map. A renamed field is a clear
    # message, not a KeyError deep in the converter.
    from engine.adapters.web_gui.from_spoor import map_errors

    good = {"states": [{"id": "s1", "actions": [{"role": "button", "name": "Go"}]}],
            "transitions": [{"from": "s1", "to": "s2", "action": {"role": "button", "name": "Go"}}],
            "skipped": [{"from": "s1", "action": {"role": "link", "name": "Out"}, "reason": "r"}]}
    assert map_errors(good) == []
    renamed = {**good, "transitions": [{"source": "s1", "to": "s2", "action": {"role": "button", "name": "Go"}}]}
    assert map_errors(renamed) == ["transitions[0] isn't {from, to, action: {role, name}}"]
    assert "exploration.skipped is missing or not a list" in map_errors({"states": [], "transitions": []})
