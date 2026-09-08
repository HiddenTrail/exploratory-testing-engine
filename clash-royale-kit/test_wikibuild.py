"""What the wiki builder must get right, checked against a map small enough to reason about.

These are not snapshot tests. A snapshot would pass whenever the output is unchanged, which
is worthless here: the whole risk in this file is that a page states something the run did not
measure, and prose that is wrong in a stable way passes a snapshot forever. So each test names
a claim the builder makes and checks the arithmetic behind it against the fixture, where the
answer was worked out by hand.

Three of them are guarding against specific ways a generated wiki goes bad rather than against
regressions. `test_sink_is_named`, because a sink is the one graph shape that costs a run
something and it is invisible unless somebody computes it. `test_never_entered_is_not_called
_unreachable`, because those are different claims and collapsing them would overstate what the
map knows. And `test_described_elements_are_not_rendered_as_measured`, because that is the one
substitution that turns this wiki from cautious into confidently wrong.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wikibuild  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ontology.json"
AT = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """The fixture map, plus crop files written here rather than committed.

    t08 gets a byte-identical before/after pair while its map entry reports 14 cells changed,
    which is the contradiction the frames page exists to find. Writing it here rather than
    checking in two identical PNGs makes that an explicit fact of the test instead of
    something a reader has to notice about two binary files.
    """
    run = tmp_path / "recon-1"
    (run / "crops").mkdir(parents=True)
    (run / "images").mkdir()
    run.joinpath("ontology.json").write_bytes(FIXTURE.read_bytes())
    run.joinpath("report.md").write_text("# Recon\n\nSome prose the pass wrote.\n",
                                         encoding="utf-8")

    same = b"\x89PNG\r\n\x1a\n-identical-crop"
    for name in ("t08-before", "t08-after", "t06-before", "t06-after"):
        run.joinpath("crops", f"{name}.png").write_bytes(same)
    for name in ("t01-before", "t02-before", "t05-before"):
        run.joinpath("crops", f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n-before-" + name.encode())
    for name in ("t01-after", "t02-after", "t05-after"):
        run.joinpath("crops", f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n-after-" + name.encode())
    return run


@pytest.fixture
def built(run_dir: Path):
    return wikibuild.build(run_dir, run_dir.parent, generated_by="process:cr-kit@test", now=AT)


def page(built, rel: str) -> str:
    return (built.workspace / "wiki" / rel).read_text(encoding="utf-8")


# --- the graph --------------------------------------------------------------------------

def test_only_screen_changes_count_as_routes(built):
    """A variant or an inert input is not an exit, and counting it as one invents routes."""
    graph = built.facts.graph
    assert graph["variant_edges"] == 2 and graph["inert_edges"] == 1
    assert ("sc04", "sc04") not in graph["edges"]
    assert ("sc01", "sc01") not in graph["edges"]
    assert graph["distinct_edges"] == 5


def test_sink_is_named(built):
    """sc04 was entered from sc01 and never left, and the map has to say so."""
    assert built.facts.graph["sinks"] == ["sc04"]
    body = page(built, "concepts/navigation-map.md")
    assert "`sc04`" in body.split("### Sinks")[1].split("###")[0]


def test_never_entered_is_not_called_unreachable(built):
    """Two different claims about sc05, and the page must not conflate them.

    Nothing was seen to *enter* sc05, and separately no chain of edges reaches it from the
    start. The first is a gap in the record; the second is a statement about the graph. A page
    that reported only one would either overstate or understate what this map knows.
    """
    graph = built.facts.graph
    assert "sc05" in graph["never_entered"]
    assert graph["unreachable_from_start"] == ["sc05"]
    assert graph["isolated"] == ["sc05"]
    body = page(built, "concepts/navigation-map.md")
    assert "### Never entered" in body and "### Unreachable from the start screen" in body


def test_a_screen_with_no_exits_says_so_plainly(built):
    body = page(built, "entities/screen-sc04.md")
    assert "nothing was seen to leave this screen" in body


# --- coverage ---------------------------------------------------------------------------

def test_named_versus_pressed_is_counted_per_screen(built):
    """Six of sc01's seven named controls were probed; the season-pass banner was not."""
    row = built.facts.reach["per_screen"]["sc01"]
    assert (row["named"], row["activated"], row["probes"]) == (7, 6, 7)
    assert built.facts.reach["never_activated"] == built.facts.reach["named"] - \
        built.facts.reach["activated"]


def test_the_reach_rule_is_printed_next_to_the_number(built):
    """A count produced by a tolerance has to show the tolerance, or it cannot be argued with."""
    body = page(built, "concepts/refused-and-unmodelled.md")
    assert str(wikibuild.REACH_TOLERANCE) in body
    assert "inside its measured box" in body


def test_refusals_and_unreached_controls_are_kept_apart(built):
    """The two numbers mean different things and the page must not merge them.

    Six inputs were declined; twelve named controls were never pressed. Presenting one total
    would read as "the safety layer blocked twelve controls", which is false for ten of them -
    the pass simply ran out of budget.
    """
    refusals = built.facts.refusals
    assert refusals["blocked_total"] == 6
    assert len(refusals["refused_by_model"]) == 4
    body = page(built, "concepts/refused-and-unmodelled.md")
    assert "was mostly not refused at all" in body


def test_the_model_s_own_reason_survives_into_the_page(built):
    """The reason is the finding. A count of refusals without it says nothing about the target."""
    body = page(built, "concepts/refused-and-unmodelled.md")
    assert "claiming a reward may consume progress currency or be irreversible" in body
    assert "live ladder match" in body


# --- evidence ---------------------------------------------------------------------------

def test_identical_crops_with_a_nonzero_count_are_reported(built):
    frames = built.facts.frames
    ids = [row["id"] for row in frames["identical_crops_nonzero_count"]]
    assert ids == ["t08"]
    # t06 has identical crops AND a zero count, so it is consistent and in neither table.
    assert frames["checked"] == 5
    body = page(built, "concepts/frames-vs-counts.md")
    assert "| t08 |" in body


def test_zero_count_with_differing_crops_is_a_separate_table(built):
    """t06 reports nothing changed and its crops are identical, so it belongs in neither table."""
    assert built.facts.frames["differing_crops_zero_count"] == []


def test_the_frames_page_does_not_overclaim(built):
    """Identical crops do not prove the frame held still, and the page has to say that.

    The count is whole-frame; the crop is a sub-region. Reading a byte-identical pair as proof
    that nothing moved would be the single easiest wrong conclusion in this wiki.
    """
    body = page(built, "concepts/frames-vs-counts.md")
    assert "do *not* prove the frame held still" in body
    assert "outside the crop" in body


def test_missing_crops_are_skipped_not_guessed(run_dir: Path, tmp_path: Path):
    """A run whose crops were never saved builds fine and reports nothing checked."""
    for path in (run_dir / "crops").iterdir():
        path.unlink()
    built = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    assert built.facts.frames["checked"] == 0
    assert "0 transitions had both crops on disk" in page(built, "concepts/frames-vs-counts.md")


# --- honesty ----------------------------------------------------------------------------

def test_described_elements_are_not_rendered_as_measured(built):
    """`located` is reproduced verbatim, because softening it is how this wiki goes wrong.

    sc01's Claim button has no box and was placed from a description. A page that showed it
    beside the measured ones without the distinction would present a guess as a measurement,
    and that is the one error here nobody downstream could detect.
    """
    body = page(built, "entities/screen-sc01.md")
    claim = [line for line in body.splitlines() if line.startswith("| Claim |")][0]
    assert "described" in claim
    assert "| - |" in claim                      # no rectangle invented for it
    assert "placed from a description alone" in body


def test_weak_identity_is_carried_into_the_screen_page(built):
    body = page(built, "entities/screen-sc03.md")
    assert "identity is flagged weak" in body
    assert "may belong" in body


def test_an_undescribed_screen_does_not_get_invented_content(built):
    """sc05 was reached and never described, and the page says exactly that."""
    body = page(built, "entities/screen-sc05.md")
    assert "named no elements" in body
    assert "nothing here says what is on it" in body


def test_the_overview_says_whose_account_this_is(built):
    body = page(built, "overview.md")
    assert "that account on that day" in body
    assert "should be read as a description of the game in general" in body


def test_no_refusals_is_not_reported_as_reassurance(run_dir: Path, tmp_path: Path):
    """A pass that reached nothing risky and a pass that found nothing risky read alike."""
    data = json.loads((run_dir / "ontology.json").read_text(encoding="utf-8"))
    data["blocked_actions"] = []
    for screen in data["screens"]:
        for verdict in screen["mouse_verdicts"].values():
            verdict["safe"] = True
    (run_dir / "ontology.json").write_text(json.dumps(data), encoding="utf-8")
    built = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    body = page(built, "concepts/refused-and-unmodelled.md")
    assert "not reassurance on its own" in body


# --- the bundle contract ----------------------------------------------------------------

def _frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "every page needs a frontmatter block"
    return text.split("---", 2)[1]


def test_every_page_carries_a_non_empty_type(built):
    """The single field that decides OKF conformance. A page without it is dropped, not fixed."""
    for path in (built.workspace / "wiki").rglob("*.md"):
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        match = re.search(r"^type: (.+)$", fm, re.M)
        assert match and match.group(1).strip(), f"{path.name} has no type"


def test_generated_and_tags_contain_no_commas(built):
    """The renderer's flow-mapping unpacker splits on commas, so a comma silently truncates.

    Not a style rule: `unflow()` in `render-html.mjs` splits `{ by: x, at: y }` on commas, so
    a comma inside either value produces a mangled actor or a mangled timestamp, and the page
    still renders.
    """
    for path in (built.workspace / "wiki").rglob("*.md"):
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        line = re.search(r"^generated: \{(.+)\}$", fm, re.M)
        assert line, f"{path.name} has no generated mapping"
        assert line.group(1).count(",") == 1, f"{path.name}: extra comma inside generated"


def test_nothing_written_carries_a_carriage_return(built):
    """A CRLF page hangs the renderer, which is a much worse failure than it sounds.

    `render-html.mjs` splits a body on `"\\n"`, so with CRLF every line keeps a trailing `\\r`.
    Its list branch then matches a bullet with one regex and re-matches it with a second ending
    `(.*)$` - and in JavaScript `.` does not match `\\r`, so the line passes the first test,
    fails the second, advances nothing, and the loop pushes until the array hits its length
    limit. What it prints is `RangeError: Invalid array length` at a `push` call, which names
    neither the file nor the line ending, on a bundle `rebuild-index.mjs` had just accepted.

    Every file the builder writes, which includes the log and `qpf.config.yml` - the latter
    gates both node scripts, so a mangled one stops the render before a page is read. The
    pass's own `report.md` is not checked: it is an input, and it is read back through
    `read_text`, which normalises line endings on the way in.
    """
    written = list((built.workspace / "wiki").rglob("*.md")) + \
        [built.workspace / "qpf.config.yml"]
    for path in written:
        assert b"\r" not in path.read_bytes(), f"{path.name} was written with CRLF"


def test_descriptions_are_one_line_and_unquoted_inside(built):
    for path in (built.workspace / "wiki").rglob("*.md"):
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        for field in ("title", "description"):
            match = re.search(rf'^{field}: "(.*)"$', fm, re.M)
            assert match, f"{path.name}: {field} is missing or not a quoted single line"
            assert '"' not in match.group(1)
            assert match.group(1).strip()


def test_image_links_resolve_from_the_page_that_carries_them(built, run_dir: Path):
    """A link is only right relative to its own directory, and entity pages sit one deeper."""
    body = page(built, "entities/screen-sc01.md")
    link = re.search(r"!\[sc01\]\((.+?)\)", body).group(1)
    assert link.startswith("../../recon-1/")
    resolved = (built.workspace / "wiki" / "entities" / link.replace("%20", " ")).resolve()
    assert resolved == (run_dir / "images" / "sc01-v1.png").resolve()


# --- where a screen animates on its own --------------------------------------------

def test_adjacent_and_diagonal_cells_join_one_box():
    """A ring of cells around a moving icon is visually one region, not eight."""
    cells = {(2, 2), (2, 3), (3, 2), (3, 3)}   # a 2x2 block, diagonal-adjacent throughout
    boxes = wikibuild._cluster_cells(cells)
    assert boxes == [(2, 2, 4, 4)]


def test_cells_too_far_apart_stay_separate_boxes():
    far = {(0, 0), (10, 10)}
    boxes = wikibuild._cluster_cells(far)
    assert sorted(boxes) == [(0, 0, 1, 1), (10, 10, 11, 11)]


def test_red_is_fast_orange_is_the_slow_tiers_own_contribution():
    """The two colours are `map_animation`'s two tiers, not degrees of one measurement -
    see `animation_regions`'s docstring for why they are kept apart. `animated_map` is
    always the union (recon.py's own invariant - see `test_animated_is_the_union_not_a
    _replacement` in test_animation_tiers.py), so orange is never computed from anything
    but that union minus the fast tier's own finding."""
    screen = {
        "animated_map": [       # the union: both tiers found something here
            "#.",
            ".#",
        ],
        "animated_fast_map": [  # the fast tier's own finding, a subset of the above
            "..",
            ".#",
        ],
    }
    regions = wikibuild.animation_regions(screen, grid=(2, 2))
    assert regions["red"] == [(0.5, 0.5, 1.0, 1.0)]      # the fast cell at (1,1)
    assert regions["orange"] == [(0.0, 0.0, 0.5, 0.5)]   # the union's (0,0), which the
                                                          # fast tier never found


def test_no_maps_at_all_is_not_a_crash():
    """A screen from before these maps existed, or one with genuinely nothing volatile."""
    assert wikibuild.animation_regions({}, grid=(32, 18)) == {"red": [], "orange": []}


def test_the_screen_page_skips_the_section_when_nothing_animates(built):
    """Every fixture screen is fully still, so none of them should claim otherwise."""
    for sid in ("sc01", "sc02", "sc03", "sc04", "sc05"):
        assert "Where this screen animates" not in page(built, f"entities/screen-{sid}.md")


def _with_animated_cells(run_dir: Path) -> dict:
    """Two fast cells at row 5, plus one slow-only cell at row 10 that the fast tier
    never found - `animated_map` (the union) has to carry both for `animated_map` to
    stay the invariant `recon.py` promises, even though this file hand-writes the
    ontology rather than getting it from a real pass."""
    data = json.loads((run_dir / "ontology.json").read_text(encoding="utf-8"))
    fast_row = "..##" + "." * 28
    slow_row = "..#." + "." * 28
    data["screens"][0]["animated_fast_map"] = ["." * 32] * 5 + [fast_row] + ["." * 32] * 12
    data["screens"][0]["animated_map"] = (["." * 32] * 5 + [fast_row]
                                          + ["." * 32] * 4 + [slow_row] + ["." * 32] * 7)
    (run_dir / "ontology.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def test_the_screen_page_reports_animation_coordinates_without_a_real_image(
        run_dir: Path, tmp_path: Path):
    """The fixture's `images/` directory is empty - no test here writes a real, decodable
    PNG - so this is also the "screen has an image path recorded but the file is not on
    disk" case, and it should degrade exactly like a missing Pillow would: coordinates
    still render, no broken image link is emitted."""
    _with_animated_cells(run_dir)
    built = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    body = page(built, "entities/screen-sc01.md")
    assert "Where this screen animates on its own" in body
    assert "| red | 0.062 | 0.278 | 0.125 | 0.333 |" in body
    assert "| orange | 0.062 | 0.556 | 0.094 | 0.611 |" in body
    assert "No picture here" in body
    assert "pip install Pillow" in body
    assert "animation map]" not in body


def test_the_screen_page_embeds_the_picture_when_pillow_and_an_image_are_both_present(
        run_dir: Path, tmp_path: Path):
    Image = pytest.importorskip("PIL.Image")
    _with_animated_cells(run_dir)
    Image.new("RGB", (786, 1400), (10, 20, 30)).save(run_dir / "images" / "sc01-v1.png")

    built = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    body = page(built, "entities/screen-sc01.md")
    assert "animation map]" in body
    out = run_dir / "images" / "sc01-animation-map.png"
    assert out.exists()
    assert Image.open(out).size == (786, 1400)


def test_the_log_grows_rather_than_being_replaced(run_dir: Path, tmp_path: Path):
    """The log is the audit trail, so a second build on the same day appends to it."""
    first = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    before = first.log_entry.read_text(encoding="utf-8")
    second = wikibuild.build(run_dir, tmp_path, generated_by="process:cr-kit@test", now=AT)
    after = second.log_entry.read_text(encoding="utf-8")
    assert after.startswith(before) and len(after) > len(before)
    assert after.count("- **Build**:") == 2


def test_a_missing_ontology_says_what_that_means(tmp_path: Path):
    with pytest.raises(FileNotFoundError) as caught:
        wikibuild.build(tmp_path, tmp_path, generated_by="process:cr-kit@test", now=AT)
    assert "died before it wrote one" in str(caught.value)


def test_the_workspace_gets_the_config_the_renderer_needs(built):
    assert (built.workspace / "qpf.config.yml").exists()
