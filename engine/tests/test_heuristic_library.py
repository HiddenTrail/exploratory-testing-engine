"""The heuristic library (issue #128): every entry is complete and uses the fixed
vocabulary, and the Oracle picks from it by surface and feature."""

import re

from engine.ontology import oracle_creator

LIBRARY = oracle_creator.load_heuristics()
VOCABULARY = oracle_creator.load_vocabulary()
ALL_TAGS = {tag for facet in VOCABULARY["tags"].values() for tag in facet}


def test_every_entry_is_complete_and_uses_the_vocabulary():
    for h in LIBRARY:
        where = h.get("id")
        assert re.fullmatch(r"[a-z][a-z0-9_]*", h["id"]), where
        for field in ("name", "description", "apply", "source"):
            assert isinstance(h[field], str) and h[field].strip(), (where, field)
        assert h["kind"] in VOCABULARY["kinds"], where
        assert h["tags"] and set(h["tags"]) <= ALL_TAGS, (where, set(h["tags"]) - ALL_TAGS)
        assert h["base_weight"] in (1, 2, 3), where


def test_ids_are_unique_across_every_source_file():
    ids = [h["id"] for h in LIBRARY]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_the_original_ids_are_kept_so_old_runs_and_context_still_match():
    ids = {h["id"] for h in LIBRARY}
    assert {"goldilocks", "boundary_edges", "zero_and_negative", "alphabet_soup", "monetary_precision",
            "empty_and_null", "duplicate_replay", "ordering_race", "sensitive_data_exposure"} <= ids
    # self_consistency is an oracle principle, so it moved to the seeds with its id (issue #138).
    from engine.ontology.seeder import load_seeds
    assert "self_consistency" in {s["id"] for s in load_seeds()}
    assert "self_consistency" not in ids


def test_no_long_dashes_in_the_text():
    for h in LIBRARY:
        for field in ("name", "description", "apply", "source"):
            assert "—" not in h[field] and "–" not in h[field], (h["id"], field)


def _ids(picked):
    return [h["id"] for h, _ in picked]


def test_a_heuristic_for_another_surface_is_left_out():
    gui_only = {"id": "g", "tags": ["gui", "usability"], "base_weight": 2}
    anywhere = {"id": "a", "tags": ["boundary"], "base_weight": 2}
    assert _ids(oracle_creator.select_heuristics([gui_only, anywhere], surfaces=("api",))) == ["a"]
    assert _ids(oracle_creator.select_heuristics([gui_only, anywhere], surfaces=None)) == ["g", "a"]


def test_own_surface_and_features_rank_higher_and_limit_caps():
    plain = {"id": "plain", "tags": ["boundary"], "base_weight": 2}
    gui = {"id": "gui", "tags": ["gui"], "base_weight": 2}
    login = {"id": "login", "tags": ["login"], "base_weight": 2}
    picked = oracle_creator.select_heuristics([plain, gui, login], surfaces=("gui",), features=("login",))
    assert _ids(picked) == ["login", "gui", "plain"]
    assert _ids(oracle_creator.select_heuristics([plain, gui, login], surfaces=("gui",), limit=1)) == ["gui"]


def test_every_heuristic_stays_below_every_grounded_claim():
    best = max(score for _, score in oracle_creator.select_heuristics(
        LIBRARY, surfaces=("gui",), features=tuple(VOCABULARY["tags"]["feature"])))
    assert best < oracle_creator.GROUNDED_BASE_SCORE
