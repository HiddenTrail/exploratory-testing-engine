"""`stitch`: composing the frames of a scroll back into one picture of the surface.

Frames are sliced from a known tall (or wide) source with a fixed chrome band overlaid,
so the reconstruction can be checked against a ground truth with no client attached.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

import stitch  # noqa: E402

W, VIEW, STEP, N = 120, 300, 120, 5
CHROME = 40


def _pixel(x: int, y: int) -> tuple[int, int, int]:
    # Each row strongly distinct (so a vertical offset is unambiguous), with per-column
    # texture so a column offset is unambiguous too.
    return ((y * 37 + x * 7) % 256, (y * 53 + x * 11) % 256, (y * 97 + x * 3) % 256)


def _tall_source(height: int) -> Image.Image:
    img = Image.new("RGB", (W, height))
    img.putdata([_pixel(x, y) for y in range(height) for x in range(W)])
    return img


def _slice_vertical(source: Image.Image, out_dir: Path) -> list[Path]:
    """Overlapping viewports stepping down STEP px, each with a constant top chrome band."""
    paths = []
    chrome = Image.new("RGB", (W, CHROME), (10, 20, 30))
    for i in range(N):
        top = i * STEP
        frame = source.crop((0, top, W, top + VIEW)).copy()
        frame.paste(chrome, (0, 0))  # fixed bar that does not scroll
        p = out_dir / f"view-{i}.png"
        frame.save(p)
        paths.append(p)
    return paths


def test_stitch_reconstructs_the_scrolled_height(tmp_path):
    source = _tall_source(VIEW + (N - 1) * STEP + 10)
    paths = _slice_vertical(source, tmp_path)

    panorama = stitch.stitch(paths, axis="vertical")
    assert panorama is not None
    assert panorama.size[0] == W
    expected = VIEW + (N - 1) * STEP  # 300 + 4*120 = 780
    # Downscale rounding allows a few px of drift per seam.
    assert abs(panorama.size[1] - expected) <= 4 * N
    assert panorama.size[1] > VIEW  # it actually grew past a single frame


def test_single_frame_is_returned_unchanged(tmp_path):
    source = _tall_source(VIEW)
    p = tmp_path / "only.png"
    source.save(p)
    out = stitch.stitch([p])
    assert out.size == (W, VIEW)


def test_a_bad_seam_stops_the_chain(tmp_path):
    source = _tall_source(VIEW + 2 * STEP + 10)
    good = _slice_vertical(source, tmp_path)[:3]
    # An unrelated frame that no offset aligns: the chain should stop before it.
    junk = Image.new("RGB", (W, VIEW))
    junk.putdata([((x * 5) % 256, (x * 13) % 256, (x * 29) % 256) for _ in range(VIEW) for x in range(W)])
    junk_path = tmp_path / "junk.png"
    junk.save(junk_path)

    with_junk = stitch.stitch(good + [junk_path], axis="vertical")
    without = stitch.stitch(good, axis="vertical")
    assert with_junk.size == without.size  # junk frame was not appended


def _wide_source(width: int) -> Image.Image:
    img = Image.new("RGB", (width, W))  # W (120) is the fixed cross-axis height here
    img.putdata([_pixel(x, y) for y in range(W) for x in range(width)])
    return img


def _slice_horizontal(source: Image.Image, out_dir: Path) -> list[Path]:
    """Overlapping viewports stepping right STEP px, each with a constant left chrome band."""
    paths = []
    chrome = Image.new("RGB", (CHROME, W), (10, 20, 30))
    for i in range(N):
        left = i * STEP
        frame = source.crop((left, 0, left + VIEW, W)).copy()
        frame.paste(chrome, (0, 0))  # fixed bar down the left that does not scroll
        p = out_dir / f"hview-{i}.png"
        frame.save(p)
        paths.append(p)
    return paths


def test_horizontal_surface_is_stitched_wide(tmp_path):
    source = _wide_source(VIEW + (N - 1) * STEP + 10)
    paths = _slice_horizontal(source, tmp_path)

    panorama = stitch.stitch(paths, axis="horizontal")
    assert panorama is not None
    expected_w = VIEW + (N - 1) * STEP
    assert abs(panorama.size[0] - expected_w) <= 4 * N
    assert panorama.size[1] == W  # the non-scroll axis is preserved


def test_unalignable_frames_yield_no_panorama(tmp_path):
    # Two frames the first seam cannot align: there is no whole page to show, only the
    # viewport the screen already has an image of - so no panorama, not a lone frame.
    a = Image.new("RGB", (W, VIEW))
    a.putdata([_pixel(x, y) for y in range(VIEW) for x in range(W)])
    b = Image.new("RGB", (W, VIEW))
    b.putdata([((x * 5) % 256, (y * 13) % 256, (x * 29) % 256) for y in range(VIEW) for x in range(W)])
    pa, pb = tmp_path / "a.png", tmp_path / "b.png"
    a.save(pa)
    b.save(pb)

    assert stitch.stitch([pa, pb], axis="vertical") is None
    assert stitch.stitch_to_file([pa, pb], tmp_path / "out.png") is False
    assert not (tmp_path / "out.png").exists()


def test_stitch_to_file_needs_at_least_two_frames(tmp_path):
    source = _tall_source(VIEW)
    p = tmp_path / "only.png"
    source.save(p)
    assert stitch.stitch_to_file([p], tmp_path / "out.png") is False
    assert not (tmp_path / "out.png").exists()

    paths = _slice_vertical(_tall_source(VIEW + STEP + 5), tmp_path)[:2]
    assert stitch.stitch_to_file(paths, tmp_path / "out.png") is True
    assert (tmp_path / "out.png").exists()
