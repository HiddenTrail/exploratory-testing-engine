"""What `battle.py` measures, and the three things it must not get wrong.

The driver has no model in it and almost no policy, so there is very little here that
could be subtly wrong about Clash Royale. What there is instead is a handful of thresholds
standing between a measurement and an action, and each of them has already failed once in
a live run:

- **The board.** The first version tapped its way to Training Camp without checking the
  window was in front, opened nothing, and deployed sixty-one gestures at the lobby. Every
  one of them was harmless and the log read exactly like a win.
- **The end.** The next version watched for the *lobby* to come back, which a finished
  match does not do - it stops on a result screen. Two runs spent their last minute
  dragging at a scoreboard.
- **The card.** Both versions counted gestures sent and called them cards played. An
  unaffordable card does not deploy, so those numbers were never the same number, and the
  difference is the whole of what "played better" could mean.

So these tests are about thresholds and the actions taken on them, and the fake window is
built to make each threshold reachable on demand: a frame is a flat buffer, and "half the
cells changed" is `mixed(cells, cells // 2)`. Nothing here knows what a card looks like,
which is the point - neither does `battle.py`.

Runs under pytest, or standalone with `python experiments/android-bot/test_battle.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

import pytest

from controller import Target  # noqa: E402
from target import DENYLISTS  # noqa: E402

import battle  # noqa: E402
from battle import (GRID_COLS, GRID_ROWS, PANEL_EDGES, SLOT_FIRST,  # noqa: E402
                    SLOT_PITCH, Match, gestures)

WHOLE_WINDOW = (0.0, 0.0, 1.0, 1.0)


def flat(cells: int, value: int = 0) -> bytes:
    return bytes([value, value, value, 255]) * cells


def mixed(cells: int, changed: int, value: int = 200) -> bytes:
    """A buffer whose first `changed` cells differ from `flat` by well over `cell_delta`.

    Which cells is arbitrary - `changed_cells` counts them, it does not care where they
    are - so the tests below can say "40% of this slot moved" and mean it exactly.
    """
    out = bytearray()
    for index in range(cells):
        v = value if index < changed else 0
        out += bytes([v, v, v, 255])
    return bytes(out)


class Clock:
    """A clock the test drives, because the loop's two stopping conditions are both about
    time and neither is worth waiting out. `sleep` advancing `monotonic` is not a
    simplification: it is what a real sleep does, and it is the only thing about real time
    that `play` depends on."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeWindow:
    """A window whose every frame is decided by the test.

    Regions are told apart by the tuple `battle.py` passes: the whole window for "is this
    the lobby", either of `PANEL_EDGES` for "is there still a card panel", `NEXT_CARD` for
    "did a card leave the hand", and a slot box for "did that slot change at all". The two
    card answers flip on every drag so that a `deploy`'s before-and-after pair always differ
    by `next_moves` and `slot_moves`, however many deploys have already happened.

    They are separate on purpose, because on the real window they disagree: a drag that
    fails to deploy leaves its card selected, so the slot changes and the next-card
    thumbnail does not. `slot_moves` defaults to 1.0 for that reason - the confounded
    reading is the one that says yes to everything.

    The two panel slivers answer *together* by default, which is the honest fake - on a real
    window they are grass together or panel together. `left_only` breaks that on purpose,
    for the one test that cares.
    """

    def __init__(self, next_moves: float = 1.0, agreement: float = 0.0,
                 panel_gone: float = 1.0, finish_after: int | None = None,
                 slot_moves: float = 1.0) -> None:
        self.target = Target(name="Clash Royale", exe="",
                             denylist=DENYLISTS["clashroyale"])
        self.hwnd = 1
        self.next_moves = next_moves
        self.slot_moves = slot_moves
        self.agreement = agreement
        self.panel_gone = panel_gone
        self.finish_after = finish_after
        self.finished = False
        self.panel_reads: list[bool] = []   # scripted answers, ahead of `finished`
        self.left_only = False              # only the left sliver stops being a panel
        self.gone = False
        self.dragged = 0
        self.drags: list[tuple] = []
        self.clicks: list[tuple[float, float]] = []
        self.focuses = 0

    # -- perception --
    def grab(self, cols: int, rows: int, region=WHOLE_WINDOW, verify: bool = True) -> bytes:
        cells = cols * rows
        if region in PANEL_EDGES:
            # Scripted per reading, not per sliver: `panel()` grabs both, and a test that
            # says "gone, then not gone" means two moments, not one moment's two ends.
            if region == PANEL_EDGES[0]:
                self.gone = (self.panel_reads.pop(0) if self.panel_reads
                             else self.finished)
            gone = self.gone and not (self.left_only and region != PANEL_EDGES[0])
            return mixed(cells, round(self.panel_gone * cells)) if gone else flat(cells)
        if region == WHOLE_WINDOW:
            return mixed(cells, round((1.0 - self.agreement) * cells))
        fraction = self.next_moves if region == battle.NEXT_CARD else self.slot_moves
        lit = round(fraction * cells)
        return mixed(cells, lit if self.dragged % 2 else 0)

    def capture(self, region=WHOLE_WINDOW, longest: int = 1400):
        return b"", 4, 4

    @staticmethod
    def write_capture(path: Path, frame) -> tuple[int, int]:
        return frame[1], frame[2]

    # -- action --
    def drag(self, start, end) -> None:
        self.drags.append((start, end))
        self.dragged += 1
        if self.finish_after is not None and self.dragged >= self.finish_after:
            self.finished = True

    def click(self, fx: float, fy: float) -> None:
        self.clicks.append((fx, fy))

    def focus(self) -> bool:
        self.focuses += 1
        return True

    def note(self, message: str) -> None:
        pass


@pytest.fixture
def quiet(monkeypatch, tmp_path):
    """No real window, no real clock, no real files. Returns the clock, because half the
    tests below want to say how much time passed."""
    clock = Clock()
    monkeypatch.setattr(battle.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(battle.time, "sleep", clock.sleep)
    monkeypatch.setattr(battle, "is_foreground", lambda hwnd: True)
    monkeypatch.setattr(battle, "OUT", tmp_path)
    return clock


# --- the gestures ------------------------------------------------------------

def test_each_deploy_picks_its_card_up_in_the_middle_of_its_own_slot():
    """The grab point and the slot watched for the card leaving have to be the same card.

    Worth its own test because a version of this file got it wrong in the way that is
    hardest to see: it read the card row as a 0.167 pitch starting at 0.204, which put
    slot 4's grab point at 0.788 - a gap between two cards. Every drag from that slot
    picked up nothing, and every one of them was logged as "no elixir", because a gesture
    that grabs air and a gesture that grabs an unaffordable card are the same picture.
    The live run that exposed it played 4 of 4 from slot 1 and 0 of 4 from slot 4.
    """
    for deploy in gestures():
        left, _, width, _ = deploy.box
        assert deploy.grab[0] == pytest.approx(left + width / 2)
        assert deploy.box[1] <= deploy.grab[1] <= deploy.box[1] + deploy.box[3]
    # And the row has to be a row: four cards at one pitch, none of them overlapping, no
    # grab point in a gap. Checked over all four even though two are unreachable, because
    # what went wrong was the arithmetic of the row, not the choice of slots.
    centres = [SLOT_FIRST + k * SLOT_PITCH for k in range(4)]
    assert centres[-1] + battle.SLOT_WIDTH / 2 < 1.0, "slot 4 runs off the window"
    assert battle.SLOT_WIDTH < SLOT_PITCH, "the cards would overlap"


def test_every_gesture_this_file_can_send_is_clear_of_every_box():
    """The floor under everything else here. Checked against the real denylist, not a
    stand-in, because the numbers are the point: these are the coordinates that get sent."""
    target = Target(name="Clash Royale", exe="", denylist=DENYLISTS["clashroyale"])
    for deploy in gestures():
        assert target.forbids(*deploy.grab) is None
        assert target.forbids(*deploy.drop) is None
        assert target.forbids_path(deploy.grab, deploy.drop) is None
    for point in (battle.MENU, battle.TRAINING_CAMP, battle.CONFIRM, battle.RESULT_OK):
        assert target.forbids(*point) is None


def test_slot_2_can_reach_no_lane_and_slot_3_can_reach_only_one():
    """Which cards are playable is a fact about the denylist and the card row, not a
    preference, so it is asserted rather than described.

    Slot 2 sits above the Battle button's box and cannot leave the panel without crossing
    it, whichever bridge it is aimed at. Slot 3 clears the box's right edge by about four
    pixels, so it can go right and not left - and that asymmetry is the whole reason this
    file sends two gestures down the right lane and one down the left.

    If a change to the card-row measurement eats slot 3's clearance this test fails, and so
    does `vet_the_gestures` at the top of the next run. That is the order it should happen
    in: the geometry being wrong must never be something a live match discovers.
    """
    target = Target(name="Clash Royale", exe="", denylist=DENYLISTS["clashroyale"])
    lane = {slot: (x, battle.DEPTH) for slot, x in
            (("left", battle.LANES[1]), ("right", battle.LANES[4]))}

    def grab_at(slot):
        return (SLOT_FIRST + (slot - 1) * SLOT_PITCH, 0.873)

    assert target.forbids_path(grab_at(2), lane["left"])
    assert target.forbids_path(grab_at(2), lane["right"])
    assert target.forbids_path(grab_at(3), lane["left"])
    assert target.forbids_path(grab_at(3), lane["right"]) is None
    assert 3 in battle.LANES and battle.LANES[3] == battle.LANES[4]
    assert 2 not in battle.LANES


def test_a_deeper_drop_is_still_a_legal_path():
    """`--depth` moves the drop point, and a drop point is half of a vetted path. The
    guard checks paths at run time either way, but a flag whose ordinary values are all
    refused is a flag that does not work."""
    target = Target(name="Clash Royale", exe="", denylist=DENYLISTS["clashroyale"])
    for depth in (0.470, 0.520, 0.560, 0.600):
        for deploy in gestures(depth):
            assert deploy.drop[1] == depth
            assert target.forbids_path(deploy.grab, deploy.drop) is None


# --- the cadence -------------------------------------------------------------

def test_the_cadence_is_flat_and_fast_enough_to_outrun_the_elixir_bar():
    """There is no loop to test any more, so what is asserted is why there is not.

    An earlier version moved the interval on the measured landing rate. That rate turned
    out to be confounded - see `deploy` - and all the loop did with a signal stuck near
    100% was drive itself to its own floor. A flat cadence is already there, and it is
    correct for a cheaper reason: an attempt that cannot be paid for costs a drag and no
    elixir, so there is nothing to save by waiting.

    What the number does have to clear is the drag itself, or `play` would be sleeping
    less than one gesture takes and the interval would stop meaning anything. Elixir
    arrives about every 2.8s in a normal match, and three gestures per interval is
    deliberately more than the bar can fund.
    """
    assert battle.CADENCE > 0.51, "a drag takes about half a second on its own"
    assert battle.CADENCE < 2.8, "slower than the elixir rate would leave elixir unspent"
    assert isinstance(battle.CADENCE, float)


# --- the card ----------------------------------------------------------------

def test_a_hand_that_did_not_change_is_not_a_card_played(quiet):
    """The measurement the whole "played better" claim rests on. A drag was sent either
    way - `drags` proves it - and the difference is whether the hand advanced."""
    window = FakeWindow(next_moves=0.0)

    played, next_moved, _ = battle.deploy(window, gestures()[0])

    assert len(window.drags) == 1
    assert played is False and next_moved == 0.0


def test_the_next_card_advancing_is_a_card_played(quiet):
    window = FakeWindow(next_moves=1.0)

    for _ in range(3):              # repeatedly, because the fake alternates its frames
        played, next_moved, _ = battle.deploy(window, gestures()[0])
        assert played is True and next_moved == pytest.approx(1.0)


def test_a_thumbnail_that_barely_moved_is_below_the_threshold(quiet):
    """Half the thumbnail is a different card in it; a tenth is the sort of change the
    little elixir cost badge makes when the number under it changes colour."""
    assert battle.deploy(FakeWindow(next_moves=0.10), gestures()[0])[0] is False
    assert battle.deploy(FakeWindow(next_moves=0.50), gestures()[0])[0] is True


def test_the_slot_reading_is_kept_but_not_believed(quiet):
    """The confound, asserted rather than only written down. A drag that fails to deploy
    leaves its card selected - drawn larger and lit - so the slot changes and stays
    changed while the hand did not move at all. A live run measuring the slot read twenty
    of its first twenty-one attempts as played, which no elixir budget allows.

    So the slot number is still taken, still logged, and has no say in `played`.
    """
    window = FakeWindow(next_moves=0.0, slot_moves=1.0)

    played, next_moved, slot_moved = battle.deploy(window, gestures()[0])

    assert played is False, "a selected card is not a played card"
    assert next_moved == 0.0 and slot_moved == pytest.approx(1.0)


def test_the_thumbnail_is_outside_every_card_slot():
    """It has to be a different thing from the hand, or it would carry the same confound.
    `NEXT_CARD` sits left of the row, in the corner where the game shows what is coming."""
    fx, fy, fw, fh = battle.NEXT_CARD
    for deploy in gestures():
        left, _, width, _ = deploy.box
        assert fx + fw <= left or fx >= left + width, (
            f"the thumbnail at x {fx}..{fx + fw} overlaps slot {deploy.slot}")
    assert fx + fw <= SLOT_FIRST - battle.SLOT_WIDTH / 2, "it must be left of the row"


# --- the end of the match ----------------------------------------------------

def test_the_watched_slivers_hold_no_cards_and_no_elixir_bar():
    """The false-fire that cost a match, as geometry rather than as a threshold.

    A run watching the whole bottom strip called the match over after twenty-two seconds
    and left the trainer to win 3-0 unopposed, because ordinary play drifts the strip: the
    cards turn over and the elixir bar fills. The fix is not a higher threshold, it is
    watching a part of the panel that play never touches - so the test is that the slivers
    do not overlap the card row, and do not reach down into the elixir bar.
    """
    row_left = SLOT_FIRST - battle.SLOT_WIDTH / 2
    row_right = SLOT_FIRST + 3 * SLOT_PITCH + battle.SLOT_WIDTH / 2
    for fx, fy, fw, fh in PANEL_EDGES:
        assert fx + fw <= row_left or fx >= row_right, (
            f"the sliver at x {fx}..{fx + fw} overlaps the card row "
            f"{row_left:.3f}..{row_right:.3f}, so a card turning over moves it")
        assert fy >= battle.SLOT_ROW_TOP, "a sliver reaching above the panel sees the board"


def test_the_match_ends_when_the_card_panel_stops_being_a_card_panel(quiet):
    """The fix for two runs' worth of wasted minutes. A three-crown win ends a match on
    the spot, and what is left is a scoreboard with grass where the cards were - so the
    loop stops on the panel going away, not on its own timer."""
    window = FakeWindow(finish_after=4)
    panel_ref = battle.panel(window)
    match = Match(number=1)

    battle.play(window, match, seconds=1000, panel_ref=panel_ref,
                cadence=2.5, deploys=gestures())

    assert "both ends of the card panel are gone" in match.ended
    assert match.attempts == 4, "it should stop at the first reading after the end"
    assert match.seconds < 1000


def test_one_end_of_the_panel_going_away_is_not_the_match_ending(quiet):
    """Both slivers or neither, and the asymmetric case is what an obstruction looks like:
    something covering one corner of the window, a notification, a cursor tooltip. On a
    real ending they are grass together, so requiring both costs nothing."""
    window = FakeWindow(finish_after=2)
    window.left_only = True
    panel_ref = battle.panel(window)
    match = Match(number=1)

    battle.play(window, match, seconds=12.0, panel_ref=panel_ref,
                cadence=2.5, deploys=gestures())

    assert "ran out with the match still on" in match.ended


def test_a_window_that_went_behind_something_is_not_a_finished_match(quiet, monkeypatch,
                                                                    capsys):
    """The confound the probe that designed this check ran into itself: every region of an
    occluded window reads 100% changed, because the frame is a picture of whatever is in
    front. Indistinguishable from a result screen in the numbers, so it is distinguished by
    asking Windows instead - between the two readings, where the answer still matters.
    """
    window = FakeWindow()
    panel_ref = battle.panel(window)
    window.finished = True             # every sliver now reads 100% changed
    monkeypatch.setattr(battle, "is_foreground", lambda hwnd: False)

    over, gone = battle.match_is_over(window, panel_ref)

    assert over is False and gone == pytest.approx(1.0)
    assert window.focuses == 1, "and it should pull the window back to the front"
    assert "went behind something" in capsys.readouterr().out


def test_one_covered_frame_does_not_end_the_match(quiet):
    """Confirmed twice, `END_CONFIRM` apart, because ending a live match early means
    tapping the result screen's OK coordinate onto a board - where it is a card, not a
    button. A spell or a tower collapse can cover the strip for one frame."""
    window = FakeWindow(finish_after=None)
    panel_ref = battle.panel(window)
    window.panel_reads = [True, False]      # gone, then not gone: a flicker
    match = Match(number=1)

    battle.play(window, match, seconds=12.0, panel_ref=panel_ref,
                cadence=2.5, deploys=gestures())

    assert "window ran out" in match.ended
    assert match.attempts > 1


def test_the_timer_is_the_backstop_when_the_end_goes_unnoticed(quiet):
    """The panel test is a threshold and thresholds can be wrong, so the timer stays. A
    match that never reads as finished stops on the clock, with a count to report."""
    window = FakeWindow()
    panel_ref = battle.panel(window)
    match = Match(number=1)

    battle.play(window, match, seconds=10.0, panel_ref=panel_ref,
                cadence=2.5, deploys=gestures())

    assert "ran out with the match still on" in match.ended
    # Four, exactly: a flat 2.5s cadence puts attempts at 0.0, 2.5, 5.0 and 7.5, and the
    # check at 10.0 finds the window spent. The count being arithmetic rather than a
    # measurement is the point of a flat cadence - the version this replaced fitted a fifth
    # attempt in the same ten seconds by tightening itself mid-window on a bad signal.
    assert match.attempts == 4 and match.seconds >= 10.0


def test_the_slots_are_cycled_in_turn_and_the_right_lane_gets_two_of_every_three(quiet):
    """The rotation is 1, 3, 4 and it has to stay that way round.

    Not because the order matters in itself, but because two of the three gestures feed the
    right bridge and one feeds the left - so cycling is what turns three legal drags into a
    push weighted two to one on one side, and a bug that starved a slot would show up here
    as a lane getting nothing rather than as a slightly worse match.
    """
    window = FakeWindow()
    match = Match(number=1)

    battle.play(window, match, seconds=15.0, panel_ref=battle.panel(window),
                cadence=2.5, deploys=gestures())

    slots = [g.slot for g in (gestures() * 10)][:len(window.drags)]
    assert slots == [1, 3, 4] * (len(slots) // 3) + [1, 3, 4][:len(slots) % 3]
    lanes = [end[0] for _, end in window.drags]
    assert lanes == [battle.LANES[s] for s in slots]
    assert lanes.count(battle.LANES[4]) > lanes.count(battle.LANES[1])
    assert set(match.per_slot) == {1, 3, 4}


# --- getting back to the lobby ----------------------------------------------

def test_a_result_screen_already_gone_is_not_tapped(quiet):
    """`dismiss_result` is called after every match, including one that ended on the timer
    with the lobby already back. Tapping OK's coordinate on the lobby lands on the bottom
    navigation bar, which is harmless - but a driver that presses buttons it has no reason
    to press is one edit away from pressing a costly one."""
    window = FakeWindow(agreement=1.0)
    reference = window.grab(GRID_COLS, GRID_ROWS)

    said = battle.dismiss_result(window, reference)

    assert window.clicks == []
    assert "the lobby is back" in said


def test_the_result_is_tapped_until_the_lobby_comes_back(quiet):
    window = FakeWindow(agreement=0.0)
    window.agreement = 1.0
    reference = window.grab(GRID_COLS, GRID_ROWS)
    window.agreement = 0.2                      # a result screen

    def relent(fx, fy):
        window.clicks.append((fx, fy))
        window.agreement = 1.0                  # the tap worked

    window.click = relent

    assert "the lobby is back" in battle.dismiss_result(window, reference)
    assert window.clicks == [battle.RESULT_OK]


def test_a_screen_that_will_not_go_away_stops_the_run(quiet, capsys):
    """Three tries, then a photograph and a stop. The alternative is a loop pressing one
    coordinate on a screen it has never seen, which is the shape of every accident this
    project's denylist exists to prevent - the difference between a driver that gives up
    and one that keeps going is not politeness, it is whether an unknown screen gets
    pressed thirty times or three."""
    window = FakeWindow(agreement=1.0)
    reference = window.grab(GRID_COLS, GRID_ROWS)
    window.agreement = 0.1

    with pytest.raises(SystemExit, match="STOPPING"):
        battle.dismiss_result(window, reference)

    assert window.clicks == [battle.RESULT_OK] * battle.DISMISS_TRIES
    assert "battle-stuck.png" in capsys.readouterr().out


def test_a_dialog_in_front_of_the_lobby_stops_the_next_match(quiet):
    """The lobby picture is taken once, before the first match, so this check can fail. A
    reference re-taken at the top of each match is a picture of whatever is on screen, and
    would pass on a chest-opening dialog as readily as on the lobby."""
    window = FakeWindow(agreement=1.0)
    lobby = window.grab(GRID_COLS, GRID_ROWS)

    battle.require_lobby(window, lobby, 2)      # still the lobby: no complaint

    window.agreement = 0.5
    with pytest.raises(SystemExit, match="something is in front of it"):
        battle.require_lobby(window, lobby, 2)


def test_the_board_is_required_before_a_single_card_is_dragged(quiet):
    """The first run's failure, as a test. `require_board` is the only thing between a
    silent no-op and a log that reads like a win."""
    window = FakeWindow(agreement=1.0)
    lobby = window.grab(GRID_COLS, GRID_ROWS)

    with pytest.raises(SystemExit, match="REFUSED to play"):
        battle.require_board(window, lobby)

    window.agreement = 0.3                      # a board looks nothing like the lobby
    battle.require_board(window, lobby)
    assert window.drags == []


# --- what the run reports ---------------------------------------------------

def test_a_matchs_own_line_says_what_it_did():
    """Including the reading it does not believe. The slot number stays in the line so
    that the next run's log can be compared against the one that got this wrong, rather
    than the comparison having to be reconstructed from a commit message."""
    match = Match(number=3, attempts=50, played=20, slot_said=48,
                  per_slot={1: 12, 4: 8}, seconds=142.0,
                  ended="both ends of the card panel are gone")

    line = match.line()

    assert "match 3" in line and "20 of 50 cards played (40%)" in line
    assert "slot 1: 12" in line and "slot 4: 8" in line
    assert "142s" in line
    assert "over-reports, said 48" in line


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
