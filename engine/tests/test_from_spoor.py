"""The Spoor-map converter (issue #113), with fake page captures in place of a live
browser: replay paths, merging, dropping unstable pages, name matching, and what it
follows and keeps (#310). No browser, no LLM."""

from engine.adapters.web_gui import careful
from engine.adapters.web_gui.from_spoor import convert
from engine.adapters.web_gui.reference import Reference
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


def test_testing_fully_a_step_that_changes_data_is_followed_and_its_control_marked():
    # #310: Spoor feeds the context; the screens behind Add to Basket or Delete reach the map.
    followed = []
    ontology, report = convert(_exploration(), URL, lambda path: followed.append(path) or _observe(path))
    assert report["refused"] == [] and [s["name"] for s in followed[-1]] == ["Delete account"]
    delete = next(e for e in ontology["states"][0]["elements"] if e["name"] == "Delete account")
    assert delete["committing"] is True                       # the gate's verdict, kept as information
    help_button = next(e for e in ontology["states"][0]["elements"] if e["name"] == "school Help getting started")
    assert help_button["committing"] is False


def test_on_a_careful_part_or_to_log_out_a_step_isnt_followed():
    tags = {"everything": False, "routes": ["/"], "controls": []}
    _, report = convert(_exploration(), URL, _observe, tags)
    assert report["refused"] == ["button:Delete account (tagged careful, and the read-only gate wouldn't click it)"]
    pages = {(): Observation(url=URL + "/", title="Shop", headings=["x"], elements=[_button("Logout", "#out")])}
    exploration = {"states": [{"id": "S0"}, {"id": "S1"}],
                   "transitions": [{"from": "S0", "to": "S1", "action": {"role": "button", "name": "Logout"}}]}
    _, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)), careful.NOTHING)
    assert report["refused"] == ["button:Logout (it logs out)"]


def test_an_ambiguous_name_is_refused():
    pages = dict(PAGES)
    pages[()] = Observation(url=URL + "/", title="Shop", headings=["welcome"],
                            elements=[_button("Juice A", "#a"), _button("Juice B", "#b")])
    exploration = {"states": [{"id": "S0"}, {"id": "S1"}],
                   "transitions": [{"from": "S0", "to": "S1", "action": {"role": "button", "name": "Juice"}}]}
    ontology, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    assert report["refused"] == ["button:Juice (more than one on the live page)"]
    assert ontology["transitions"] == []


def test_a_name_only_the_accessibility_tree_has_is_followed_by_that_name():
    # #310: a Juice Shop product card is "button:Apple Juice (1000ml)" to Spoor, but an
    # unnamed button in the DOM capture. It's followed with no locator, so the replay
    # finds it by its accessible name.
    pages = {(): Observation(url=URL + "/", title="Shop", headings=["x"], elements=[_button("", "#card")]),
             ("Apple Juice (1000ml)",): Observation(url=URL + "/", title="Shop", headings=["apple juice"],
                                                    elements=[_button("Close Dialog", "#close")])}
    exploration = {"states": [{"id": "S0"}, {"id": "S1"}],
                   "transitions": [{"from": "S0", "to": "S1",
                                    "action": {"role": "button", "name": "Apple Juice (1000ml)"}}]}
    ontology, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    assert report["refused"] == [] and len(ontology["states"]) == 2
    assert ontology["transitions"][0]["action"] == {"kind": "click", "element_key": "button:Apple Juice (1000ml)",
                                                    "target": ""}
    _, careful_report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)),
                                careful.EVERYTHING)
    assert careful_report["refused"] == [
        "button:Apple Juice (1000ml) (tagged careful, and not in the page capture for the read-only gate to judge)"]


def test_a_page_that_doesnt_replay_is_dropped():
    def observe(path):
        return None if path else PAGES[()]
    ontology, report = convert(_exploration(), URL, observe)
    assert [s["id"] for s in ontology["states"]] == ["st01"]
    assert set(report["dropped_unstable"]) == {"S1", "S2", "S3"}


def test_a_control_spoor_couldnt_reach_is_kept_and_marked():
    # Issue #121: a modal dialog hides the page behind it from Spoor, but web-recon's DOM
    # capture still lists those controls. The sweep leaves them out (clicking them hit the
    # backdrop); the Driver's guide shows them, marked (#310).
    pages = dict(PAGES)
    pages[()] = Observation(url=URL + "/", title="Shop", headings=["welcome"],
                            elements=[_button("Close Banner", "#close"), _button("Open Sidenav", "#nav")])
    exploration = {"states": [{"id": "S0", "actions": [{"role": "button", "name": "Close Banner"}]}],
                   "transitions": []}
    ontology, report = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    by_name = {e["name"]: e.get("spoor_reached", True) for e in ontology["states"][0]["elements"]}
    assert by_name == {"Close Banner": True, "Open Sidenav": False}
    assert report["hidden_controls"] == 1
    reference = Reference({**ontology, "schema": "web-recon/1"})
    assert ("st01", "button:Open Sidenav") not in reference.pairs()
    assert "button:Open Sidenav (behind a dialog, or not reached by the recon)" in reference.driver_briefing()


def test_a_control_spoor_skipped_is_left_out():
    pages = {(): Observation(url=URL + "/", title="Shop", headings=["x"], elements=[_button("Next page", "#n")])}
    exploration = {"states": [{"id": "S0", "actions": [{"role": "button", "name": "Next page"}]}],
                   "transitions": [],
                   "skipped": [{"from": "S0", "action": {"role": "button", "name": "Next page"},
                                "reason": "blocked by an unresolved layer: div"}]}
    ontology, _ = convert(exploration, URL, lambda path: pages.get(tuple(s["name"] for s in path)))
    assert ontology["states"][0]["elements"][0]["spoor_reached"] is False


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


def test_the_summary_prints_on_a_console_that_cannot_encode_icon_characters():
    # Issue #150: PrestaShop's "All products " crashed the print on Windows (cp1252).
    import io

    from engine.adapters.web_gui.from_spoor import print_summary

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252")
    report = {"spoor_states": 5, "states": 2, "transitions": 1, "dropped_unstable": [], "refused_steps": 1,
              "hidden_controls": 0, "refused": ["link:All products "]}
    print_summary(report, "out.json", console)
    console.flush()
    assert "refused: link:All products ?" in raw.getvalue().decode("cp1252")
