"""That a frame saved to disk comes back as the same frame.

`write_png` has been in this file for a long time and needed no tests: its output is looked
at by eye, and a wrong PNG is a wrong picture. `read_png` is different. It exists so that
thresholds can be developed against real game frames with no game running - which means
every number a detector is tuned on passes through it, and a decoder that is subtly wrong
produces frames that still look like frames and thresholds that are quietly off.

Two things are worth testing and one is not. Not worth testing: that the pixels are pretty.
Worth testing: that the round trip is **exact**, because approximate is indistinguishable
from correct by eye; and that the decoder **refuses** what it cannot do, because the
alternative is a paletted screenshot silently read as garbage.

The filter reconstruction gets its own tests even though nothing in this repo writes a
filtered PNG. `write_png` emits filter 0 on every row, so `_unfilter` only ever runs on a
file from somewhere else - a screenshot tool, a saved frame from a browser - which is
exactly the case with no eyes on it.

Runs under pytest, or standalone with
`python experiments/game-screen-probe/test_png.py`.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from probe import read_png, thumbnail_from_bgra, write_png  # noqa: E402


def bgra(*pixels: tuple[int, int, int]) -> bytes:
    """A BGRA buffer from (blue, green, red) triples, alpha opaque throughout."""
    return b"".join(bytes((b, g, r, 255)) for b, g, r in pixels)


def build_png(width: int, height: int, rows: list[tuple[int, bytes]],
              depth: int = 8, colour: int = 2, interlace: int = 0) -> bytes:
    """A PNG assembled by hand, so a test can choose the filter type of every row.

    `rows` is one `(filter type, raw scanline)` pair per row, already in whatever encoding
    that filter type implies - the test does the filtering, the decoder does the undoing,
    and neither can accidentally agree with the other through shared code.
    """
    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body)))

    raw = b"".join(bytes([kind]) + line for kind, line in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">2I5B", width, height, depth, colour,
                                         0, 0, interlace))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


# --- the round trip ----------------------------------------------------------

def test_a_frame_written_and_read_back_is_the_same_frame(tmp_path):
    """Exactly the same, byte for byte, not merely similar. Every threshold developed
    offline is a number measured through this path, so "close enough" here is a systematic
    error in every one of them."""
    frame = bgra((0, 0, 0), (255, 255, 255), (10, 20, 30), (200, 100, 50),
                 (1, 2, 3), (255, 0, 0))
    path = tmp_path / "frame.png"

    write_png(str(path), frame, 3, 2)
    back, width, height = read_png(str(path))

    assert (width, height) == (3, 2)
    assert back == frame


def test_the_channels_do_not_get_swapped(tmp_path):
    """The mistake this decoder is one typo away from, and the one no size or length check
    would catch. A PNG is RGB and a frame here is BGRA, so the reader reverses three bytes
    per pixel - reversed the wrong way, red and blue trade places and every frame still
    decodes, still has the right dimensions, and still looks like a game."""
    pure_red_in_bgra = bgra((0, 0, 255))
    path = tmp_path / "red.png"
    write_png(str(path), pure_red_in_bgra, 1, 1)

    # Red in the file, because the PNG spec's byte order is R, G, B - so the round trip
    # cannot pass by reversing twice.
    assert zlib.decompress(idat_of(path.read_bytes())) == b"\x00\xff\x00\x00"

    assert read_png(str(path))[0] == pure_red_in_bgra


def idat_of(blob: bytes) -> bytes:
    """The compressed scanlines of a PNG, found by walking the chunks rather than by
    assuming an offset - `write_png`'s header is a fixed size today and need not stay one."""
    at, out = 8, bytearray()
    while at + 8 <= len(blob):
        length, tag = struct.unpack(">I4s", blob[at:at + 8])
        if tag == b"IDAT":
            out += blob[at + 8:at + 8 + length]
        at += 12 + length
    return bytes(out)


def test_a_real_game_frame_off_disk_decodes(tmp_path):
    """The frames this whole capability exists for. Skipped rather than failed when they are
    not there: `out/` is gitignored, so a fresh clone has no frames, and a test that fails
    for lack of a file nobody committed is noise."""
    frame = (Path(__file__).resolve().parents[1] / "android-bot" / "out"
             / "battle-m1-t120.png")
    if not frame.exists():
        pytest.skip(f"no live frame at {frame} - run battle.py to make one")

    pixels, width, height = read_png(str(frame))

    assert (width, height) == (393, 700)
    assert len(pixels) == width * height * 4
    assert pixels[3::4] == b"\xff" * (width * height), "alpha should be opaque throughout"
    assert len(set(pixels[0::4])) > 20, "a real frame is not a flat fill"


def test_an_alpha_channel_is_read_and_then_ignored(tmp_path):
    """Colour type 6 is what an ordinary screenshot tool writes. The alpha in it is not
    carried through, and that is deliberate rather than an oversight: `grab_thumbnail`
    leaves the alpha byte undefined and `changed_cells` skips it, so a frame off disk that
    *did* carry alpha would be the one frame in the system whose fourth byte meant
    something."""
    rgba = bytes((10, 20, 30, 128)) + bytes((40, 50, 60, 0))
    path = tmp_path / "rgba.png"
    path.write_bytes(build_png(2, 1, [(0, rgba)], colour=6))

    pixels, width, height = read_png(str(path))

    assert (width, height) == (2, 1)
    assert pixels == bgra((30, 20, 10), (60, 50, 40))


# --- the filters -------------------------------------------------------------

@pytest.mark.parametrize("kind", [1, 2, 3, 4])
def test_every_filter_type_reconstructs_the_original(kind, tmp_path):
    """Filters 1-4 as the spec defines them, encoded here and decoded there.

    The encoding is written out longhand rather than shared with `_unfilter`, because a test
    that filters using the same arithmetic as the code it tests passes on any consistent
    arithmetic, including wrong arithmetic.
    """
    width, height, bpp = 4, 3, 3
    original = bytes(((x * 37 + y * 91 + c * 13) % 256
                      for y in range(height) for x in range(width) for c in range(bpp)))

    rows = []
    for y in range(height):
        line = original[y * width * bpp:(y + 1) * width * bpp]
        prior = original[(y - 1) * width * bpp:y * width * bpp] if y else bytes(width * bpp)
        encoded = bytearray()
        for x in range(width * bpp):
            left = line[x - bpp] if x >= bpp else 0
            up = prior[x]
            upleft = prior[x - bpp] if x >= bpp else 0
            if kind == 1:
                predictor = left
            elif kind == 2:
                predictor = up
            elif kind == 3:
                predictor = (left + up) // 2
            else:
                peer = left + up - upleft
                a, b, c = abs(peer - left), abs(peer - up), abs(peer - upleft)
                predictor = left if a <= b and a <= c else (up if b <= c else upleft)
            encoded.append((line[x] - predictor) & 0xFF)
        rows.append((kind, bytes(encoded)))

    path = tmp_path / f"filter{kind}.png"
    path.write_bytes(build_png(width, height, rows))
    pixels, _, _ = read_png(str(path))

    expected = bgra(*[(original[i + 2], original[i + 1], original[i])
                      for i in range(0, len(original), bpp)])
    assert pixels == expected


def test_filters_can_be_mixed_row_by_row(tmp_path):
    """Which real encoders do - they pick the cheapest filter per row - so a decoder that
    reads the filter byte once and applies it to everything would work on most files."""
    width = 3
    plain = bytes((5, 5, 5, 9, 9, 9, 13, 13, 13))
    # Row 1 filtered Up against row 0, so its raw bytes are the difference.
    second = bytes((7, 7, 7, 7, 7, 7, 7, 7, 7))
    path = tmp_path / "mixed.png"
    path.write_bytes(build_png(width, 2, [(0, plain), (2, second)]))

    pixels, _, height = read_png(str(path))

    assert height == 2
    assert pixels[width * 4:] == bgra((12, 12, 12), (16, 16, 16), (20, 20, 20))


# --- what it refuses ---------------------------------------------------------

@pytest.mark.parametrize("why,kwargs", [
    ("16-bit", dict(depth=16)),
    ("paletted", dict(colour=3)),
    ("greyscale", dict(colour=0)),
    ("interlaced", dict(interlace=1)),
])
def test_what_it_cannot_decode_it_refuses(why, kwargs, tmp_path):
    """A decoder that guesses is worse than one that refuses. Each of these would otherwise
    produce a buffer of the right length full of the wrong pixels - and a frame that is the
    right size and wrong is the failure this repo keeps meeting: it looks like success."""
    path = tmp_path / f"{why}.png"
    path.write_bytes(build_png(2, 1, [(0, bytes(6))], **kwargs))

    with pytest.raises(ValueError, match="only 8-bit non-interlaced"):
        read_png(str(path))


def test_a_file_that_is_not_a_png_is_not_read(tmp_path):
    path = tmp_path / "nope.png"
    path.write_bytes(b"this is not a PNG at all")

    with pytest.raises(ValueError, match="not a PNG"):
        read_png(str(path))


def test_an_unknown_filter_type_is_named_rather_than_skipped(tmp_path):
    """Filter type 5 does not exist. A decoder that treated it as None would return a frame
    with one corrupt row, which is invisible in a 700-row picture."""
    path = tmp_path / "bogus.png"
    path.write_bytes(build_png(2, 1, [(5, bytes(6))]))

    with pytest.raises(ValueError, match="unknown PNG filter type 5"):
        read_png(str(path))


def test_a_truncated_frame_is_caught_before_it_is_decoded(tmp_path):
    """Short scanline data means a partly-written file or a truncated download, and the
    length check is what stops it becoming a frame that is mostly black at the bottom."""
    path = tmp_path / "short.png"
    path.write_bytes(build_png(4, 4, [(0, bytes(12))]))

    with pytest.raises(ValueError, match="bytes of scanline, expected"):
        read_png(str(path))


# --- downsampling off a buffer ----------------------------------------------

def test_a_thumbnail_off_a_buffer_has_a_live_grabs_shape():
    """Interchangeable with `grab_thumbnail`'s output or it is no use: `changed_cells` walks
    it four bytes at a time and every threshold in the drivers is a fraction of `cols *
    rows`."""
    frame = bgra(*[(0, 0, 0)] * 64)

    cells = thumbnail_from_bgra(frame, 8, 8, 4, 2)

    assert len(cells) == 4 * 2 * 4
    assert cells[3::4] == b"\xff" * 8, "alpha opaque, as GDI's is not but the shape needs"


def test_each_cell_is_the_average_of_the_block_under_it():
    """Averaging rather than sampling, because a single sampled pixel makes a thumbnail that
    flickers on one troop's outline and a whole quadrant that reads busy for nothing."""
    #  a 2x2 image, one flat colour per pixel, downsampled to one cell
    frame = bgra((0, 0, 0), (100, 100, 100), (200, 200, 200), (255, 255, 255))

    cell = thumbnail_from_bgra(frame, 2, 2, 1, 1)

    average = (0 + 100 + 200 + 255) // 4
    assert cell == bgra((average, average, average))


def test_a_region_crops_before_it_downsamples():
    """The arena box is a region, so a region that was applied after downsampling - or not
    at all - would average the card panel into the bottom row of the board."""
    #  Left half black, right half white, in a 4x1 strip.
    frame = bgra((0, 0, 0), (0, 0, 0), (255, 255, 255), (255, 255, 255))

    left = thumbnail_from_bgra(frame, 4, 1, 1, 1, region=(0.0, 0.0, 0.5, 1.0))
    right = thumbnail_from_bgra(frame, 4, 1, 1, 1, region=(0.5, 0.0, 0.5, 1.0))

    assert left == bgra((0, 0, 0))
    assert right == bgra((255, 255, 255))


def test_more_cells_than_pixels_still_yields_one_cell_each():
    """Asking for a finer grid than the source has pixels is not an error, it is a caller
    that cropped a small region - and the answer has to be the right length regardless, or
    `changed_cells` walks off the end of it."""
    frame = bgra((10, 20, 30), (40, 50, 60))

    cells = thumbnail_from_bgra(frame, 2, 1, 6, 3)

    assert len(cells) == 6 * 3 * 4


def test_a_real_frame_downsamples_to_something_a_change_test_can_read():
    """The end-to-end use: a saved frame, decoded, reduced to the grid `arena.py` reads. The
    assertion is only that the result has structure - a flat grid would mean the crop or the
    averaging collapsed, which is the failure that reads downstream as "nothing ever
    happens on this board"."""
    frame = (Path(__file__).resolve().parents[1] / "android-bot" / "out"
             / "battle-m1-t120.png")
    if not frame.exists():
        pytest.skip(f"no live frame at {frame} - run battle.py to make one")
    pixels, width, height = read_png(str(frame))

    cells = thumbnail_from_bgra(pixels, width, height, 12, 20,
                               region=(0.040, 0.085, 0.920, 0.724))

    assert len(cells) == 12 * 20 * 4
    assert len(set(cells[1::4])) > 10, "the arena downsampled to a flat green is wrong"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
