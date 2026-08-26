"""Play a real game: launch cold, score up to level 2, take the reward, quit.

    py play_level.py              # the whole thing, cold disk to no process
    py play_level.py --recon      # launch, dump crops and readings, stop
    py play_level.py --test-push  # push once from each side, dump each board
    py play_level.py --types      # is a cleared quad a type that cannot score?
    py play_level.py --finish     # skip playing: exit button twice, then close

Two measured runs, cold: main menu in 8.0s and 8.3s, then 7 pushes for 100 points
and 10 pushes for 50, `Level up! - level 2` detected on the push that caused it
both times, a card taken off the reward panel, two clicks on the exit icon,
`WM_CLOSE`. The board box reads 2113-2145 ink of 2304 while a board is up and 206
or 306 under the panel, so the stop condition has an order of magnitude of margin
rather than a tuned threshold.

Unlike the shuffle loop, this has to *understand* the board, so it began as a
recon mode whose only job was to produce images to design against. That paid for
itself immediately: the first recon read caught the board mid-slide, because
`new_game()` returns as soon as the shuffle label appears, and the tiles looked
like an irregular non-3x3 layout. A very convincing wrong conclusion, and free to
avoid by looking at a picture before writing a planner.

Geometry below is measured off that crop, not guessed. The board is a 3x3 of
~148px tiles with twelve arrows around it, three per side.

The three things that were genuinely hard are documented where they live, because
each one is a different kind of mistake: classify() on choosing a *feature* rather
than a metric, scoring_moves() on a lookahead that scored the wrong shape, and
panel_up() on a detector that was pointed in the wrong direction entirely.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import bench_shuffle as bench  # noqa: E402
import game_session as gs  # noqa: E402
from probe import grab_thumbnail, mouse_move_to, set_dpi_aware, write_png  # noqa: E402

OUT = Path("C:/Users/pmarj/AppData/Local/Temp/tt/level")

# Measured off surround.png: the tiles occupy this box, slightly wider than the
# benchmark's BOARD (which only had to detect *motion*, not identify cells).
TILES = (0.2413, 0.3912, 0.1188, 0.2134)
COLS = ROWS = 3
COL_X = tuple(0.2413 + (i + 0.5) * 0.1188 / COLS for i in range(COLS))
ROW_Y = tuple(0.3912 + (i + 0.5) * 0.2134 / ROWS for i in range(ROWS))

# The twelve arrows. Confirmed against the crop: the top arrows sit on the column
# centres and the side arrows on the row centres, so only one offset per side is
# an independent measurement.
ARROW_TOP_Y, ARROW_BOTTOM_Y = 0.3370, 0.6615
ARROW_LEFT_X, ARROW_RIGHT_X = 0.2081, 0.3911

# The next tile has no box of its own - see staged_stats(). It is drawn beside
# whichever arrow the cursor hovers, so reading it means parking on a chosen one.
# The square's edges were found by scanning the crop for non-background columns
# and rows rather than read off a screenshot by eye: eyeballing put its centre 22px
# out and its width 26px over, which is a quarter of a tile in each direction.
REF_SIDE, REF_INDEX = "left", 1
STAGED_OFFSET = 127.5 / 3840              # arrow centre -> tile centre, outward
STAGED_Y = 0.5000                         # measured; not quite the arrow's own row
STAGED_W, STAGED_H = 144 / 3840, 144 / 2160
STAGED_VIEW = (0.133, 0.438, 0.080, 0.120)   # for --recon dumps only

# Inset *inside* the bar's dashed border. Spanning the border instead reads its
# dashes as fill in every column and reports a full bar at score zero - the same
# mistake the deck counter made before its box was tightened.
PROGRESS_BAR = (0.152, 0.0530, 0.298, 0.0220)
SCORE = (0.045, 0.040, 0.045, 0.045)      # the running score, top left
EXIT_BUTTON = (0.9063, 0.9097)            # two clicks; authorized for this run

# The four card *slots* on the level-up panel, measured off two dumps. Slots, not
# cards: level 2 offered "mud, sea, +10, autumn forest" on one run and "mud, +10,
# autumn forest, sea" on the next, so **the order is randomized per level-up** and
# a fixed coordinate takes whatever happens to be sitting there. Which matters,
# because the four are not equivalent - three add a tile type and every extra type
# makes a 2x2 rarer on nine cells, while "+10" is free score. Choosing on purpose
# means reading the card labels, which this run has no need to do; it just needs the
# panel gone. So this takes slot 3 and reports nothing about what it took.
#
# Tried in order rather than trusted: a click that misses a card changes nothing,
# and if the screen was actually CHALLENGES the first click lands on the main menu,
# which is self-identifying. Guessing is how the slots got measured at all - an
# earlier run's (0.500, 0.520) fell in the gap between two of them and did nothing.
REWARD_CANDIDATES = ((0.566, 0.520), (0.300, 0.520), (0.431, 0.520),
                     (0.698, 0.520))

BACKGROUND = (196, 228, 243)              # cream, in BGR

# Tile classification. Every number here is measured off one board whose nine
# tiles were identified by eye from a full-resolution dump, so the margins are
# known rather than assumed - see classify() for the readings themselves.
SAMPLE = 0.80             # fraction of a tile to read: inside its border, most of its art
LEAF_G = 70               # green ceiling for "this pixel is a forest leaf"
FOREST_DARK = 0.22        # leaf-dark fraction: forest >= 0.30, bush <= 0.14
ANIMAL_G, ANIMAL_B = 140, 110   # the magenta animal: red over green, and dark with it
WARM_R, GREEN_G = 140, 95       # split the two green tiles off from sand/dirt/unknown
SAME_TILE = 24.0          # BGR distance, for the non-green types that colour handles
MAX_MOVES = 150   # a match refills the deck, so a good run is not deck-bounded

# A panel is up when the ink inside the board box falls below this fraction of
# what a full board reads. See panel_up() for why the test runs in that direction.
PANEL_FRACTION = 0.45


def log(message: str) -> None:
    print(message, flush=True)


# --- reading ----------------------------------------------------------------

def region_px(region) -> tuple[int, int, int, int]:
    left, top, width, height = bench.rect
    fx, fy, fw, fh = region
    return (left + int(width * fx), top + int(height * fy),
            max(1, int(width * fw)), max(1, int(height * fh)))


def dump(name: str, region, longest: int = 900) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    rx, ry, rw, rh = region_px(region)
    scale = min(1.0, longest / max(rw, rh))
    ow, oh = max(1, int(rw * scale)), max(1, int(rh * scale))
    path = OUT / f"{name}.png"
    write_png(str(path), grab_thumbnail(rx, ry, rw, rh, ow, oh), ow, oh)
    log(f"  {name}: {ow}x{oh} of {rw}x{rh}")
    return path


CELL_W, CELL_H = 0.1188 / COLS, 0.2134 / ROWS


def patch_stats(region) -> tuple[tuple[float, float, float], float]:
    """(mean BGR, fraction of leaf-dark pixels) over a patch, sampled **1:1**.

    Native resolution is not an optimisation to skip. Every other reader here
    downsamples through `StretchBlt` with HALFTONE, which averages each output
    pixel over its source block - and averaging is precisely what destroys the
    dark-pixel fraction below, because a few very dark leaf pixels blended with
    their bright grass neighbours land in the middle and are counted as neither."""
    rx, ry, rw, rh = region_px(region)
    buf = grab_thumbnail(rx, ry, rw, rh, rw, rh)
    n = rw * rh
    total = [0, 0, 0]
    dark = 0
    for i in range(0, len(buf), 4):
        total[0] += buf[i]
        total[1] += buf[i + 1]
        total[2] += buf[i + 2]
        if buf[i + 1] < LEAF_G:
            dark += 1
    return (total[0] / n, total[1] / n, total[2] / n), dark / n


def distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def cell_stats(col: int, row: int):
    x0, y0 = 0.2413 + col * CELL_W, 0.3912 + row * CELL_H
    return patch_stats((x0 + (1 - SAMPLE) / 2 * CELL_W,
                        y0 + (1 - SAMPLE) / 2 * CELL_H,
                        SAMPLE * CELL_W, SAMPLE * CELL_H))


def staged_stats():
    """The next tile - read beside a reference arrow, because it has no home.

    There is no staged-tile box. The next tile is drawn *adjacent to whichever
    arrow the cursor is hovering*, one tile's width further out, and nowhere at
    all when the cursor is elsewhere. Two earlier reads of a fixed dashed box on
    the left were coincidences of where the mouse happened to be parked; the third
    returned pure cream and duly clustered the background as a tile type. So park
    on a known arrow - the middle-left one, chosen because its tile lands clear of
    both the board and the score row - and read the fixed offset beside it.

    Its square is 144px where a board cell is 152px, so the patch is expressed in
    the staged tile's own size rather than in `CELL_W`; sampling the same relative
    slice of each tile is what lets one classifier serve both."""
    ax, ay = arrow_point(REF_SIDE, REF_INDEX)
    mouse_move_to(*bench.at(ax, ay))
    time.sleep(0.22)
    cx, cy = ax - STAGED_OFFSET, STAGED_Y
    return patch_stats((cx - SAMPLE / 2 * STAGED_W, cy - SAMPLE / 2 * STAGED_H,
                        SAMPLE * STAGED_W, SAMPLE * STAGED_H))


def classify(samples: list) -> list[str]:
    """Label every reading of one board, plus the staged tile, in one pass.

    The mean colour cannot do this job alone, and the measurements say so
    plainly. Over the same patch, five forest cells read a mean of (34-38,
    115-123, 94-99) and two bush cells (42-49, 125-135, 103-114): the classes
    overlap once a cell's grass shows through, and the staged forest tile landed
    almost exactly on the midpoint between the two centroids. Distance to a
    reference colour therefore decides forest-vs-bush by a coin flip, which is how
    a whole deck got spent on 2x2s the game did not agree existed. Two earlier
    attempts to fix this by changing the *comparison* - chromaticity, then
    majority voting over patches - both made it worse, because the problem was
    never the metric.

    The fraction of leaf-dark pixels is not a better metric, it is a different
    measurement, and it separates the two with room to spare: forest 0.30-0.41,
    bush 0.04-0.14. Forest tiles carry three big near-black leaves; bush tiles
    carry small mid-green clumps and simply have no pixels that dark. So the tone
    decides only the green pair, where it is decisive, and colour still handles
    everything else - sand, dirt, and whatever later levels add - by clustering,
    where it was never in trouble."""
    labels: list[str] = []
    others: list[tuple[float, float, float]] = []
    animals = 0
    for mean, dark in samples:
        b, g, r = mean
        if r > g and g < ANIMAL_G and b < ANIMAL_B:
            # The wandering animal, not a tile. Each gets a *distinct* label so
            # it is equal to nothing, including to another obscured cell.
            animals += 1
            labels.append(f"*{animals}")
        elif r < WARM_R and g > GREEN_G:
            labels.append("f" if dark > FOREST_DARK else "b")
        else:
            for i, centroid in enumerate(others):
                if distance(mean, centroid) < SAME_TILE:
                    labels.append(f"t{i}")
                    break
            else:
                others.append(mean)
                labels.append(f"t{len(others) - 1}")
    return labels


def read_state() -> tuple[list[list[str]], str]:
    """(board labels, staged label), from one consistent pass over ten patches."""
    samples = [cell_stats(c, r) for r in range(ROWS) for c in range(COLS)]
    samples.append(staged_stats())
    labels = classify(samples)
    board = [labels[r * COLS:(r + 1) * COLS] for r in range(ROWS)]
    return board, labels[-1]


def report_cells() -> None:
    """Print each patch's raw measurements beside its label, so a dump of the
    board can be checked against the reading by eye. Every classifier bug so far
    has been invisible in the labels alone and obvious within seconds of the
    numbers sitting next to the picture."""
    samples = [cell_stats(c, r) for r in range(ROWS) for c in range(COLS)]
    samples.append(staged_stats())
    labels = classify(samples)
    for r in range(ROWS):
        parts = []
        for c in range(COLS):
            (b, g, rr), dark = samples[r * COLS + c]
            parts.append(f"{labels[r * COLS + c]:>3} ({b:5.1f},{g:5.1f},{rr:5.1f}) d{dark:.3f}")
        log("    " + "  ".join(parts))
    (b, g, rr), dark = samples[-1]
    log(f"    staged {labels[-1]:>3} ({b:5.1f},{g:5.1f},{rr:5.1f}) d{dark:.3f}")


def dark_ink(region, w: int, h: int, ceiling: int = 180) -> int:
    """Count of pixels darker than `ceiling` on the green channel.

    Deliberately not a fill fraction. The level bar's dashed border leaves an
    interior gap only ~9px tall at 4K, so any strip thick enough to sample
    reliably also contains dashes, and a 'rightmost non-background column' read
    reports a full bar at score zero. Counting ink over the whole box instead
    ignores the border tone entirely and still moves when the bar fills."""
    rx, ry, rw, rh = region_px(region)
    buf = grab_thumbnail(rx, ry, rw, rh, w, h)
    return sum(1 for i in range(0, len(buf), 4) if buf[i + 1] < ceiling)


def bar_fill() -> int:
    """Percent of the level bar that is blue - progress toward the next level.

    Counting *blue* pixels rather than dark ones is what makes this readable at
    all. The bar sits inside a dashed tan border, and any strip thick enough to
    sample reliably also contains dashes, so a darkness count reported a full bar
    at score zero and a fill-to-the-rightmost-non-background column did the same.
    Blue is the one thing on that row the border cannot fake: everything in this
    game's palette is warm, so `blue > red` selects the fill and nothing else, and
    the border tone stops mattering."""
    rx, ry, rw, rh = region_px(PROGRESS_BAR)
    buf = grab_thumbnail(rx, ry, rw, rh, 128, 8)
    blue = sum(1 for i in range(0, len(buf), 4) if buf[i] - buf[i + 2] > 30)
    return round(100 * blue / (128 * 8))


def score_ink() -> int:
    """Ceiling raised well above `dark_ink`'s default: the score numerals are
    light tan on cream, not dark ink, so a threshold sized for the deck counter's
    grey digits reads a flat zero no matter what the score is. It read 0 for four
    scoring pushes in a row, which is indistinguishable from 'nothing scored' -
    the exact reading that sent the last debugging session after the wrong bug."""
    return dark_ink(SCORE, 24, 16, ceiling=215)


def board_ink() -> int:
    """Dark pixels inside the board box, out of 48x48 sampled.

    Nine tiles of saturated art with borders between them give a high, stable
    count. Every panel this game draws is cream, so anything opening over the board
    makes this collapse - which is the only direction worth testing, see
    panel_up()."""
    return dark_ink(TILES, 48, 48, ceiling=200)


def panel_up(full_board: int) -> tuple[bool, int]:
    """(is a panel covering the board, the ink reading that says so).

    Exists because **`on_game_screen()` does not go false on a level up.** The
    panel opens over the board while the shuffle label stays visible behind it, so
    the one detector the loop had kept answering "still playing" - and since there
    is no neutral click on this screen, the next planned push spent itself picking a
    reward at random and play carried on past the thing the run existed to reach.
    That is the same shape of mistake as reading a window that is merely occluded:
    the check was truthful about the wrong question.

    The first attempt at a fix asked whether ink had *appeared* over the play area,
    reasoning that a panel covers a lot of ground that was empty. It fired at 10
    cells against a threshold of 20 on the one turn a panel was genuinely up,
    because **every panel in this game is cream**: score 90's CHALLENGES screen is
    a light card on a light background, and the level-up card is the same. Drawn
    over a board of saturated tiles it *removes* ink. So the whole test was pointing
    the wrong way, and no threshold on it would have worked.

    Two independent conditions, because one of them alone is not safe. A match
    clears its quad before refilling it, so up to four of nine cells can be
    momentarily blank and drag the ink down on a perfectly live board - hence the
    re-read after a pause, and hence the second condition: a real board always shows
    at least one forest or bush tile, and a cream panel shows none. Colour and
    density fail differently, which is the point of asking both."""
    ink = board_ink()
    if ink > full_board * PANEL_FRACTION:
        return False, ink
    time.sleep(0.7)          # let a clear-and-refill animation finish
    ink = board_ink()
    if ink > full_board * PANEL_FRACTION:
        return False, ink
    board, _ = read_state()
    greens = sum(1 for row in board for value in row if value in ("f", "b"))
    return greens == 0, ink


# --- planning ---------------------------------------------------------------

MOVES = ([("top", c) for c in range(COLS)] + [("bottom", c) for c in range(COLS)]
         + [("left", r) for r in range(ROWS)] + [("right", r) for r in range(ROWS)])


def arrow_point(side: str, index: int) -> tuple[float, float]:
    if side == "top":
        return COL_X[index], ARROW_TOP_Y
    if side == "bottom":
        return COL_X[index], ARROW_BOTTOM_Y
    if side == "left":
        return ARROW_LEFT_X, ROW_Y[index]
    return ARROW_RIGHT_X, ROW_Y[index]


def simulate(board, side: str, index: int, tile: int):
    """Push `tile` in from one edge. Insert at the near edge, shift the line away,
    the far tile drops off - the board is not addressable by cell."""
    out = [row[:] for row in board]
    if side in ("top", "bottom"):
        column = [out[r][index] for r in range(ROWS)]
        column = ([tile] + column[:-1]) if side == "top" else (column[1:] + [tile])
        for r in range(ROWS):
            out[r][index] = column[r]
    else:
        row = out[index]
        out[index] = ([tile] + row[:-1]) if side == "left" else (row[1:] + [tile])
    return out


def quads(board) -> int:
    return sum(1 for r in range(ROWS - 1) for c in range(COLS - 1)
               if board[r][c] == board[r][c + 1] == board[r + 1][c] == board[r + 1][c + 1])


def scoring_moves(board, types) -> int:
    """How many (tile type, push) pairs would complete a quad on this board.

    This replaced a count of 2x2 windows holding three of a kind, which sounds
    like the same thing and is not - it is the reason a run reached level 1 and
    stopped. On a 3x3 board **no push can fill one cell of a 2x2 without moving
    another cell of the same 2x2**: inserting at an edge shifts the whole line, so
    filling (0,0) from the top displaces (0,0) into (1,0). A window needing exactly
    one tile is therefore not one move from scoring, and a planner rewarded for
    building them spends the deck assembling positions it can never close.

    What does score is a push that shifts an existing pair *into* place at the same
    time as it inserts the third - an L of three, not a square of three. Rather
    than characterise those shapes, this simulates every tile the deck can deal
    against every push and counts the ones that land a quad. Same 3x3 mechanics as
    the real move, so it cannot disagree with them."""
    return sum(1 for tile in types for side, index in MOVES
               if quads(simulate(board, side, index, tile)))


def matchable(board, staged: str) -> list[str]:
    """The tile types in play, unknown cells excluded.

    Read off the board rather than hardcoded, so the lookahead stays honest if a
    later level introduces a fourth type - and so an unknown cell contributes
    nothing, since a type nobody has seen cannot be dealt on purpose."""
    seen = {value for row in board for value in row} | {staged}
    return sorted(v for v in seen if not v.startswith(("*", "?")))


def adjacencies(board) -> int:
    total = 0
    for r in range(ROWS):
        for c in range(COLS):
            if c + 1 < COLS and board[r][c] == board[r][c + 1]:
                total += 1
            if r + 1 < ROWS and board[r][c] == board[r + 1][c]:
                total += 1
    return total


def plan(board, tile: str, avoid=None):
    """Take a match now; failing that, leave the board one push from a match.

    Two plies, and the second one is over the *unknown* next tile rather than a
    guessed one: the deck is not visible, so the useful question is not "what is
    the best follow-up" but "how many of the tiles the deck could deal would let me
    score", which is what `scoring_moves` counts. Cheap - 12 candidate pushes times
    three types times 12 follow-ups is a few hundred list copies - and it needs no
    lookahead into the tile queue, which is drawn too small to read reliably.

    `avoid` is the previous move and is only ever the last tiebreak. Twelve moves
    scored on a coarse scale tie constantly, and breaking ties by list order picks
    `top 0` every time, which pushes down the same column repeatedly and can sit in
    a cycle until the deck is gone."""
    types = matchable(board, tile)
    scored = []
    for side, index in MOVES:
        after = simulate(board, side, index, tile)
        scored.append(((quads(after), scoring_moves(after, types),
                        adjacencies(after), 0 if (side, index) == avoid else 1),
                       side, index))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0]


# --- acting -----------------------------------------------------------------

def push(side: str, index: int) -> None:
    bench.click(bench.at(*arrow_point(side, index)), hover=0.25, hold=0.08)
    bench.wait_stable()


def board_text(board) -> str:
    return " / ".join(",".join(row) for row in board)


def merge_prediction(board, predicted):
    """Fill animal-obscured cells with what the previous push predicted is there.

    One cell per read is drawn over by the wandering animal, and an unknown cell is
    a hole in all four quads it touches: the planner can neither see a match it
    already holds nor build one through that square, so a third of the board is
    periodically unusable. The push rules are deterministic, though, so last turn's
    simulation already says what is underneath.

    Only sound when that push scored nothing - a match refills its quad from the
    deck, which is deliberately not modelled - so the caller drops the prediction
    on any turn that matched. A cell whose prediction is *itself* unknown gets a
    freshly numbered label instead of the stale one: reusing `*1` across turns would
    let two cells that are both merely unknown compare equal and fake a quad."""
    if not predicted:
        return board
    unknown = 0
    out = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            value = board[r][c]
            if value.startswith("*"):
                value = predicted[r][c]
                if value.startswith(("*", "?")):
                    unknown += 1
                    value = f"?{unknown}"
            row.append(value)
        out.append(row)
    return out


def play(limit: int = MAX_MOVES) -> str:
    """Push tiles until a panel comes up over the board or the game ends.

    Returns why it stopped. The board is re-read every turn rather than tracked
    forward from the simulation, because a match refills its cleared quad from the
    deck - state the simulation deliberately does not model. The one thing carried
    across turns is the prediction for cells the animal is standing on, which the
    camera cannot see and the rules can."""
    log(f"\n{'move':>4}  {'next':>5}  {'bar':>4}  {'deck':>4}  {'ink':>5}  "
        f"{'board':<26}  move            plan")
    full_board = board_ink()
    log(f"a full board reads {full_board} ink of 2304; "
        f"a panel is anything under {full_board * PANEL_FRACTION:.0f}")
    last, predicted, best_bar = None, None, 0
    for move in range(1, limit + 1):
        if not bench.on_game_screen():
            # The game-over CHALLENGES screen: the board is gone entirely.
            return "left the board"
        board, tile = read_state()
        board = merge_prediction(board, predicted)
        (immediate, near, adj, _), side, index = plan(board, tile, avoid=last)
        after = simulate(board, side, index, tile)
        bar, deck = bar_fill(), bench.counter_ink()
        push(side, index)
        last = (side, index)
        predicted = after if immediate == 0 else None
        # Checked after *every* push, not once per iteration at the top. The level
        # up is the thing this run exists to reach and it arrives as an overlay in
        # the middle of a turn - and since no click on this screen is neutral,
        # noticing it one push late does not mean pushing into it, it means the
        # push silently picks a reward and the panel is gone before it was ever
        # seen. That is exactly how the first working run sailed past level 2.
        panel, ink = panel_up(full_board)
        log(f"{move:>4}  {tile:>5}  {bar:>3}%  {deck:>4}  {ink:>5}  "
            f"{board_text(board):<26}  {side:>6} {index}  "
            f"match {immediate}, near {near}, adj {adj}")
        if panel:
            log(f"  panel over the board after move {move}: "
                f"{ink} ink of {full_board}, no green tiles")
            return "level up"
        # A bar that jumps backwards is a level threshold being crossed, and it is
        # the one signal here with a meaning rather than a calibration. Reported
        # even when the panel test already stopped the run, because the two
        # disagreeing is worth knowing about.
        if bar + 8 < best_bar:
            log(f"  level bar dropped {best_bar}% -> {bar}% at move {move} "
                f"without the panel test firing")
            return "bar reset"
        best_bar = max(best_bar, bar)
    return "move limit"


def take_reward() -> str:
    """Clear whatever screen has come up over the board, and report which it was.

    Two can appear and they are not distinguishable by any reading calibrated so
    far: the level-up reward choice, and the game-over CHALLENGES panel. Rather
    than calibrate a discriminator against a screen this run has to reach before
    it can be measured, click and let the *destination* identify the origin - a
    reward choice returns to the board, CHALLENGES goes to the main menu. Both are
    already readable with existing detectors, and a stray click on either is
    harmless, which is what makes the guessing safe. The dump is the point at
    which the reward cards can finally be located properly."""
    dump("levelup", (0.0, 0.0, 1.0, 1.0), 1400)
    for point in REWARD_CANDIDATES:
        bench.click(bench.at(*point), hover=0.30, hold=0.10)
        time.sleep(1.3)
        if bench.highlighted_row() >= 0:
            log("  landed on the main menu - that screen was CHALLENGES, not a level up")
            return "menu"
        if on_real_board():
            log(f"  reward taken at ({point[0]:.3f}, {point[1]:.3f}); back on the board")
            return "board"
    return "unknown"


def on_real_board() -> bool:
    """A live board, not merely something with enough blue in the right place.

    `on_game_screen()` measures the blueness of one region and nothing else, and it
    answered "board" on the main menu once - after a click that had in fact left
    CHALLENGES - which then sent a level-2 verdict into a run that had scored zero.
    A board is identified by what only a board has: green tiles. The menu is warm
    tan throughout and every panel is cream."""
    if not bench.on_game_screen():
        return False
    board, _ = read_state()
    return any(value in ("f", "b") for row in board for value in row)


def finish() -> None:
    """Two clicks on the exit button, as instructed for this run."""
    log("\nexit button, two clicks")
    for attempt in (1, 2):
        if not bench.find_game():
            log(f"  window already gone before click {attempt}")
            return
        bench.click(bench.at(*EXIT_BUTTON), hover=0.30, hold=0.10)
        time.sleep(1.2)
        log(f"  click {attempt} done")
    # Only worth capturing if there is still a window; otherwise the same call
    # returns the desktop that is now behind it, which is entry 10 all over again.
    if bench.find_game():
        dump("after_exit", (0.0, 0.0, 1.0, 1.0), 1200)
    else:
        log("  game closed itself")


def test_push() -> None:
    """Verify the actuation primitive before trusting any planner built on it.

    The first play run scored 0 in eight moves and two consecutive turns read
    identical boards, which means the pushes were not landing - so the planner's
    predictions were never the thing being tested. This pushes one tile from each
    side in turn and dumps the board before and after each, which answers three
    questions at once: are the arrow coordinates right, does one click place a
    tile, and does the line shift in the direction the simulation assumes."""
    bench.wait_stable()
    time.sleep(0.5)
    dump("push0", TILES, 500)
    board, tile = read_state()
    log(f"  start        {board_text(board)}  staged {tile}")
    report_cells()
    for step, (side, index) in enumerate((("top", 0), ("left", 1),
                                          ("right", 2), ("bottom", 0)), start=1):
        point = arrow_point(side, index)
        log(f"  push {side} {index} at ({point[0]:.4f}, {point[1]:.4f})")
        push(side, index)
        time.sleep(0.5)
        dump(f"push{step}", TILES, 500)
        board, tile = read_state()
        log(f"  after        {board_text(board)}  staged {tile}  "
            f"score {score_ink()}  deck {bench.counter_ink()}")


def survey_types() -> None:
    """Ask whether a cleared quad leaves a type behind that cannot score.

    Ran to settle a suspicion that turned out to be false, and worth keeping for
    the answer. The premise was that a match clears its 2x2 to inert dirt - which
    must be inert, or the first match would cascade forever - and that dirt is tan
    like sand, so the two would land in one cluster and hand the planner a
    matchable type that can never score. Indistinguishable from bad luck in a move
    log, hence a run of its own.

    **There is no dirt.** The cleared quad refills with fresh tiles, and level 1
    deals exactly three types: forest, bush and sand, all matchable. The design is
    sound; the fresh/after dumps below are what showed it, since a fresh board
    cannot contain dirt by construction and the after board never grew a fourth
    cluster."""
    bench.new_game()
    bench.wait_stable()
    log("fresh board - any tan tile here is sand, because nothing has cleared yet")
    dump("types_fresh", TILES, 456)
    report_cells()

    before = bar_fill()
    last = None
    for move in range(1, 15):
        if not bench.on_game_screen():
            log(f"  left the board after {move - 1} moves without a match")
            return
        board, tile = read_state()
        (immediate, near, adj, _), side, index = plan(board, tile, avoid=last)
        log(f"  {move:>2}  bar {bar_fill():>3}%  {board_text(board):<26}  "
            f"next {tile}  ->  {side} {index} (match {immediate})")
        push(side, index)
        last = (side, index)
        if bar_fill() > before:
            log(f"\nbar moved {before}% -> {bar_fill()}% on move {move}: "
                "the cleared quad below is dirt")
            dump("types_dirt", TILES, 456)
            report_cells()
            return
    log("  no match in 14 moves")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play up to level 2, then quit.")
    parser.add_argument("--recon", action="store_true")
    parser.add_argument("--test-push", action="store_true",
                        help="push once from each side and dump the board each time")
    parser.add_argument("--types", action="store_true",
                        help="measure whether cleared dirt reads apart from sand")
    parser.add_argument("--finish", action="store_true",
                        help="skip playing: exit button, then close")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--exe")
    args = parser.parse_args()

    set_dpi_aware()
    existing = bench.find_game()
    if existing:
        hwnd, pid, t0 = existing, gs.window_pid(existing), 0.0
        log(f"attaching to window {hwnd}, pid {pid}")
    else:
        hwnd, pid, t0 = gs.start(gs.find_exe(args.exe))
    if t0:
        gs.wait_ready(hwnd, t0)
    if not gs.focus(hwnd):
        raise SystemExit("game will not take the foreground")

    try:
        if args.finish:
            finish()
        elif args.test_push:
            if not bench.on_game_screen():
                bench.new_game()
            test_push()
            return
        elif args.types:
            survey_types()
            return
        elif args.recon:
            if not bench.on_game_screen():
                bench.new_game()
            bench.wait_stable()
            time.sleep(0.6)
            dump("full", (0.0, 0.0, 1.0, 1.0), 1600)
            dump("surround", (0.020, 0.280, 0.400, 0.420), 1100)
            mouse_move_to(*bench.at(*arrow_point(REF_SIDE, REF_INDEX)))
            time.sleep(0.3)
            dump("staged", STAGED_VIEW, 400)
            dump("bar", (0.140, 0.045, 0.330, 0.035), 900)
            board, tile = read_state()
            log(f"  board {board_text(board)}  staged {tile}  "
                f"bar {bar_fill()}%  score {score_ink()}")
            report_cells()
            return
        else:
            # Always a fresh game, even when attaching to one in progress: a
            # part-played board has an unknown score and a nearly empty deck, so
            # "play to level 2" from there is not the same task and can be
            # arithmetically impossible. new_game() drains and resets whatever is
            # up, which is the only reset this game offers.
            bench.new_game()
            bench.wait_stable()
            why = play()
            log(f"\nstopped: {why}")
            if why == "move limit":
                dump("reached", (0.0, 0.0, 1.0, 1.0), 1200)
                log("no level up within the move limit - leaving the exit button alone")
                return
            where = take_reward()
            if where != "board":
                log(f"ended on the {where} screen, so level 2 was not reached")
                return
            finish()
    finally:
        if args.keep_open or args.recon or args.test_push or args.types:
            log("leaving the game running")
        else:
            log(f"closed via {gs.close(hwnd, pid)}")


if __name__ == "__main__":
    main()
