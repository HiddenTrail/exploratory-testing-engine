"""Stitch the frames of a scroll into one picture of the whole surface.

A scrollable surface is one place seen through a moving viewport. Recon saves the
full-res frame at each offset (`Screen.scroll_views`); this composites them back into
the single page they are windows onto: the fixed chrome (a top bar a feed scrolls
under) appears once, and each later frame contributes only the strip of content it
newly revealed.

The offset between two frames is found by correlating their profiles along the scroll
axis on a downscaled copy - the same reason `recon.scroll_shift` works on profiles
rather than cells: a real scroll moves a fractional number of pixels and exact matching
is defeated by resampling and by a moving background. A pair whose best alignment is
still poor (a near-duplicate, a failed scroll, a jump to different content) ends the
chain rather than splicing a bad seam.

Pillow is required to use this. Recon imports it lazily and skips the panorama if it is
absent, the same way the wiki's animation pictures are optional.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Fraction of the leading edge that is fixed chrome, excluded when measuring the offset
# so a bar that never moves cannot pull the match toward "no scroll".
CHROME_FRACTION = 0.14

# Downscale extent (px) along the non-scroll axis for the offset search: enough to align
# on, cheap to scan.
SEARCH_EXTENT = 80

# Mean per-pixel line distance above which two frames are not a clean continuation of
# the same scroll. The chain stops rather than splice a bad seam. Measured on a live
# feed: clean steps scored 2-15, a near-duplicate 30-38.
MAX_SEAM_SCORE = 22.0

# A step has to move at least this fraction of the scroll axis to be a real scroll worth
# appending; below it the frame is effectively a duplicate.
MIN_STEP_FRACTION = 0.03


def _profiles(gray: Image.Image, axis: str) -> tuple[int, list[list[int]]]:
    """A downscaled grayscale frame as profiles along the scroll `axis`.

    Returns (line_count_along_axis, lines) where each line is the pixels *across* the
    scroll axis at one position along it - a row for a vertical scroll, a column for a
    horizontal one. The offset search is then identical for both.
    """
    w, h = gray.size
    px = list(gray.get_flattened_data())
    if axis == "vertical":
        return h, [px[y * w:(y + 1) * w] for y in range(h)]
    return w, [[px[y * w + x] for y in range(h)] for x in range(w)]


def _downscaled(img: Image.Image, axis: str) -> Image.Image:
    """Grayscale, shrunk across the scroll axis to SEARCH_EXTENT for a cheap search."""
    w, h = img.size
    if axis == "vertical":
        return img.convert("L").resize((SEARCH_EXTENT, max(1, h * SEARCH_EXTENT // w)))
    return img.convert("L").resize((max(1, w * SEARCH_EXTENT // h), SEARCH_EXTENT))


def _line_distance(a: list[int], b: list[int]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _best_offset(before: Image.Image, after: Image.Image, axis: str) -> tuple[int, float]:
    """Full-res pixels the content moved toward the start, and how clean the match is.

    Scrolling on moves content toward the start of the axis (up / left), so after[i]
    aligns with before[i + d]. The fixed chrome band at the start is excluded from
    scoring so a bar that never moves cannot pull the match toward d=0. Returns
    (offset_full_res, score); score is inf when no offset could be judged.
    """
    full = before.size[1] if axis == "vertical" else before.size[0]
    n, lb = _profiles(_downscaled(before, axis), axis)
    _, la = _profiles(_downscaled(after, axis), axis)
    chrome = int(n * CHROME_FRACTION)

    best = None
    for d in range(1, n - chrome - 1):
        span = range(chrome, n - d)
        if len(span) < n * 0.2:
            break
        score = sum(_line_distance(la[i], lb[i + d]) for i in span) / len(span)
        if best is None or score < best[1]:
            best = (d, score)
    if best is None:
        return 0, float("inf")
    d_small, score = best
    return round(d_small * full / n), score


def _compose(frames: list[Image.Image], offsets: list[int], axis: str) -> Image.Image:
    """Frame 0 whole, then each later frame's newly-revealed end strip appended."""
    width, height = frames[0].size
    if axis == "vertical":
        canvas = Image.new("RGB", (width, height + sum(offsets)))
        canvas.paste(frames[0], (0, 0))
        y = height
        for i, d in enumerate(offsets, start=1):
            canvas.paste(frames[i].crop((0, height - d, width, height)), (0, y))
            y += d
        return canvas
    canvas = Image.new("RGB", (width + sum(offsets), height))
    canvas.paste(frames[0], (0, 0))
    x = width
    for i, d in enumerate(offsets, start=1):
        canvas.paste(frames[i].crop((width - d, 0, width, height)), (x, 0))
        x += d
    return canvas


def stitch(view_paths: list[str | Path], axis: str = "vertical") -> Image.Image | None:
    """One picture of the whole surface from its ordered scroll frames.

    `axis` is the surface's scroll axis. Returns None if there are no frames; a single
    frame is returned unchanged. A pair whose best alignment is poor (a near-duplicate,
    a failed scroll, a jump to different content) ends the chain rather than splicing a
    bad seam.
    """
    paths = list(view_paths)
    if not paths:
        return None
    frames = [Image.open(p).convert("RGB") for p in paths]
    if len(frames) == 1:
        return frames[0]

    extent = frames[0].size[1] if axis == "vertical" else frames[0].size[0]
    offsets: list[int] = []
    for i in range(1, len(frames)):
        d, score = _best_offset(frames[i - 1], frames[i], axis)
        if score > MAX_SEAM_SCORE or d < int(extent * MIN_STEP_FRACTION):
            break  # seam is not a clean continuation - stop rather than splice
        offsets.append(d)

    return _compose(frames[:len(offsets) + 1], offsets, axis)


def stitch_to_file(view_paths: list[str | Path], out_path: str | Path,
                   axis: str = "vertical") -> bool:
    """Stitch and save; return whether a panorama was written.

    Only writes when stitching actually combined more than one frame - a lone frame is
    already the screen's own image and needs no panorama.
    """
    if len(list(view_paths)) < 2:
        return False
    panorama = stitch(view_paths, axis=axis)
    if panorama is None:
        return False
    panorama.save(out_path)
    return True
