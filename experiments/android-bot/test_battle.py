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
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

import pytest

import controller  # noqa: E402
from controller import Target  # noqa: E402
from target import DENYLISTS  # noqa: E402

import arena  # noqa: E402
import battle  # noqa: E402
import hand as hand_module  # noqa: E402
import plan  # noqa: E402
import towers as towers_module  # noqa: E402
from battle import (GRID_COLS, GRID_ROWS, PANEL_EDGES, SLOT_FIRST,  # noqa: E402
                    SLOT_PITCH, Match)

WHOLE_WINDOW = (0.0, 0.0, 1.0, 1.0)
QUIET = (0.0, 0.0, 0.0, 0.0)

BOOK = battle.catalogue()


def attacks() -> tuple[battle.Gesture, ...]:
    """The three attacking deploys, in slot order.

    A helper rather than a constant because the catalogue is keyed by purpose now, and most
    of the geometry tests below are about the card row - which is the same for all five
    purposes - so they want one gesture per slot and do not care which.
    """
    return tuple(BOOK[(slot, "attack")] for slot in sorted(plan.REACH))


def board(cards: tuple[str, ...] = ("knight", "minions", "giant", "musketeer"),
          elixir: int = 10, grey: tuple[int, ...] = (),
          standing: str = "OOOO") -> tuple[hand_module.Hand, towers_module.Towers]:
    """A board state for `play` to be given, in the terms `plan` reads it in.

    Substituted for `battle.read_state` rather than painted into the fake window's pixels,
    and the split is deliberate: whether four boxes of BGRA say "Giant, greyed" is
    `test_hand.py`'s question, answered against saved frames where the answer was read by
    eye. What is being tested here is what the loop *does* with a Giant it can afford, and
    routing that through a synthetic card panel would make one test of two claims.

    The default is a full, affordable hand and four standing towers: the opening board.
    """
    slots = tuple(hand_module.Slot(number, "grey" if number in grey else "ready", card=card)
                  for number, card in enumerate(cards, start=1))
    return (hand_module.Hand(slots, elixir),
            towers_module.Towers(*(mark == "O" for mark in standing)))


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


def arena_grid(activity: tuple[float, float, float, float], value: int = 200) -> bytes:
    """An arena grid with a given fraction of each quadrant's cells lit.

    *Where* in the quadrant is arbitrary, as with `mixed` - but *which quadrant* is not,
    and this is the one fake here that has to agree with the code it tests about that. So
    the split is taken from `arena` itself rather than restated: a test that lit the wrong
    half would otherwise pass while asserting the opposite of what it says.
    """
    split_row, half = arena.river_row(), arena.COLS // 2
    lit = [0, 0, 0, 0]
    out = bytearray()
    for row in range(arena.ROWS):
        for col in range(arena.COLS):
            which = (0 if row < split_row else 2) + (0 if col < half else 1)
            quadrant_cells = (split_row if which < 2 else arena.ROWS - split_row) * half
            on = lit[which] < round(activity[which] * quadrant_cells)
            lit[which] += on
            v = value if on else 0
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
    the lobby", either of `PANEL_EDGES` for "is there still a card panel", `ELIXIR_STRIP` for
    "how much elixir is there", and a slot box for "did that slot change at all".

    **The elixir bar is the fake's one piece of state**, because it is the one thing on the
    real window that is state: a spend is not undone by looking again. `pink` is how full it
    is, `drag` takes `spends` off it, and `refill` puts a pass's worth back. Both readings the
    driver takes come off that one number - `capture(ELIXIR_STRIP)` for "is a board up" and
    `state`'s elixir for the panel - which is the arrangement on the real window too, and it
    is what makes a spend visible to the loop one pass later without anything being scripted.

    `slot_moves` is scripted rather than stateful and defaults to 1.0, because on the real
    window it says yes to everything: a drag that deploys nothing still leaves its card
    selected. Keeping the confounded reading in the fake is what lets the tests assert that
    nothing believes it.

    The two panel slivers answer *together* by default, which is the honest fake - on a real
    window they are grass together or panel together. `left_only` breaks that on purpose,
    for the one test that cares.
    """

    def __init__(self, spends: float = 0.40, agreement: float = 0.0,
                 panel_gone: float = 1.0, finish_after: int | None = None,
                 slot_moves: float = 1.0, refill: float = 0.03,
                 activity: tuple[float, float, float, float] = QUIET,
                 state=None) -> None:
        self.target = Target(name="Clash Royale", exe="",
                             denylist=DENYLISTS["clashroyale"])
        self.hwnd = 1
        # What `read_state` will report: the hand and the towers, as a pair. Carried on the
        # window rather than passed to `play`, because on the real thing it *is* a property
        # of the window - two readings of it, taken with two captures. The cards are whatever
        # the test asked for; the *elixir* is not, it comes off `pink` - see `state`.
        self.cards = state if state is not None else board()
        # Whether the elixir bar is showing at all, which is `require_board`'s positive test
        # for a board being up. True by default: almost every test here is about a board that
        # exists, and the one that is not says so. `bar_showing` False hides the bar whatever
        # `pink` says, the way an off-board screen does.
        self.bar_showing = True
        self.pink = self.cards[0].elixir / hand_module.ELIXIR_MAX
        self.spends = spends
        self.refill = refill
        self.slot_moves = slot_moves
        self.agreement = agreement
        self.panel_gone = panel_gone
        self.finish_after = finish_after
        self.finished = False
        self.panel_reads: list[bool] = []   # scripted answers, ahead of `finished`
        self.left_only = False              # only the left sliver stops being a panel
        self.gone = False
        self.activity = activity            # per-quadrant fraction the arena shows moving
        self.arena_grabs = 0
        self.dragged = 0
        self.drags: list[tuple] = []
        self.hovers: list[float] = []
        self.clicks: list[tuple[float, float]] = []
        self.focuses = 0

    @property
    def state(self):
        """The hand and the towers, with the elixir taken from the bar rather than from what
        the test wrote down. One number, read two ways, exactly as on the real window - which
        is the whole reason a spend made by `drag` becomes visible to the loop's own panel
        reading a pass later without any test having to script the sequence."""
        in_hand, standing = self.cards
        return replace(in_hand, elixir=round(self.pink * hand_module.ELIXIR_MAX)), standing

    # -- perception --
    def grab(self, cols: int, rows: int, region=WHOLE_WINDOW, verify: bool = True) -> bytes:
        cells = cols * rows
        if region == arena.ARENA:
            # Alternating, for the same reason the card regions alternate: `arena.Watch`
            # compares consecutive looks, so a board that is *always* the same picture is a
            # board where nothing ever moves, whatever `activity` says.
            self.arena_grabs += 1
            return (arena_grid(self.activity) if self.arena_grabs % 2
                    else flat(cells))
        if region in PANEL_EDGES:
            # Scripted per reading, not per sliver: `panel()` grabs both, and a test that
            # says "gone, then not gone" means two moments, not one moment's two ends.
            if region == PANEL_EDGES[0]:
                self.gone = (self.panel_reads.pop(0) if self.panel_reads
                             else self.finished)
                # Elixir arrives here: the panel check is the one thing `play` does on every
                # pass whether or not it is watching the arena, and `deploy` never does it.
                # Keeping the refill outside anything `deploy` touches is what stops a test
                # from accidentally letting regeneration answer "did a card land".
                self.pink = min(1.0, self.pink + self.refill)
            gone = self.gone and not (self.left_only and region != PANEL_EDGES[0])
            return mixed(cells, round(self.panel_gone * cells)) if gone else flat(cells)
        if region == WHOLE_WINDOW:
            return mixed(cells, round((1.0 - self.agreement) * cells))
        lit = round(self.slot_moves * cells)
        return mixed(cells, lit if self.dragged % 2 else 0)

    def capture(self, region=WHOLE_WINDOW, longest: int = 1400):
        # The elixir strip is answered as a bar `pink` full, in a 10-pixel buffer so one
        # pixel is one elixir. Everything else is answered as an empty buffer: `read_state`
        # is substituted in these tests, so the panel and tower bands are never read here.
        if region == battle.ELIXIR_STRIP:
            cells = hand_module.ELIXIR_MAX
            showing = round(self.pink * cells) if self.bar_showing else 0
            full, empty = b"\xff\x40\xff\xff", b"\x20\x20\x20\xff"
            return full * showing + empty * (cells - showing), cells, 1
        return b"", 4, 4

    @staticmethod
    def write_capture(path: Path, frame) -> tuple[int, int]:
        return frame[1], frame[2]

    # -- action --
    def drag(self, start, end, hover: float = 0.20) -> None:
        self.drags.append((start, end))
        self.hovers.append(hover)
        self.dragged += 1
        # The spend, which is what `deploy` is measuring. Clamped at zero rather than allowed
        # to go negative, so a long scripted run of drags ends up broke instead of absurd.
        self.pink = max(0.0, self.pink - self.spends)
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
    monkeypatch.setattr(battle, "read_state", lambda window: window.state)
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
    for deploy in BOOK.values():
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
    for deploy in BOOK.values():
        assert target.forbids(*deploy.grab) is None
        assert target.forbids(*deploy.drop) is None
        assert target.forbids_path(deploy.grab, deploy.drop) is None, (
            f"the {deploy.purpose} gesture from slot {deploy.slot} crosses a box")
    for point in (battle.MENU, battle.TRAINING_CAMP, battle.CONFIRM, battle.RESULT_OK):
        assert target.forbids(*point) is None


def test_the_gate_at_the_top_of_the_run_sees_every_gesture_the_run_can_send(quiet, capsys):
    """Fifteen gestures now - three slots at each of five purposes - and the gate has to be
    shown all of them. A purpose that was added to `DROPS` and to the policy but not to the
    vetting call would be a coordinate that reaches a live match without ever having been
    checked, which is the one thing this file's safety argument rests on not happening."""
    window = FakeWindow()

    battle.vet_the_gestures(window, BOOK)

    printed = capsys.readouterr().out
    assert printed.count("clear of all") == len(BOOK) == 3 * len(battle.DROPS)
    # Every purpose named in the output, so the operator watching the terminal can see which
    # coordinates were checked rather than trusting that fifteen lines means the right ones.
    for purpose in battle.DROPS:
        assert f"slot 1 {purpose}" in printed
    assert f"({battle.DEPTH:.3f})" not in printed, "y alone is not a coordinate"
    for lane_drops in battle.DROPS.values():
        for drop in lane_drops.values():
            assert f"({drop[0]:.3f}, {drop[1]:.3f})" in printed


def test_the_gate_reports_how_much_room_each_path_had(quiet, capsys):
    """Slot 3's paths clear the Battle button by 0.001 to 0.004 of the window's width. That
    is a coincidence of where the button sits rather than a designed margin, so the number is
    printed every run: a re-measured card row shows up as a shrinking margin in the terminal
    the operator is already watching, instead of as a surprise."""
    window = FakeWindow()

    battle.vet_the_gestures(window, BOOK)

    printed = capsys.readouterr().out
    tightest = min(battle.clearance(window, g) for g in BOOK.values())
    assert 0.0 < tightest < 0.005, "slot 3 is the tight one and it is still clear"
    assert f"{tightest:.4f}" in printed
    # The gesture the whole margin question is about, checked by name so that a future
    # catalogue which quietly drops it does not make this test pass by having nothing tight.
    assert battle.clearance(window, BOOK[(3, "attack")]) == pytest.approx(tightest)


def test_a_gesture_across_a_box_stops_the_run_before_anything_is_sent(quiet):
    """The gate failing closed, which is what makes slot 3's four pixels of clearance
    acceptable rather than reckless: if the card row is ever measured differently, this is
    where it is found out - not by a live match."""
    window = FakeWindow()
    over_the_battle_button = battle.Gesture(
        slot=2, purpose="attack", grab=(0.498, 0.873), drop=(0.498, 0.470),
        box=(0.42, battle.SLOT_ROW_TOP, battle.SLOT_WIDTH, battle.SLOT_ROW_HEIGHT))

    with pytest.raises(SystemExit, match="REFUSED before starting"):
        battle.vet_the_gestures(window, {**BOOK, (2, "attack"): over_the_battle_button})

    assert window.drags == [] and window.clicks == []


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
    # And the policy has to be reading the same fact, since it is the one that picks slots.
    assert plan.REACH == {1: "left", 3: "right", 4: "right"}
    assert set(battle.LANES) == set(plan.REACH)


def test_every_purpose_has_a_destination_on_both_sides_of_the_board():
    """Otherwise a lane would silently lose a purpose - and the loop would raise `KeyError`
    out of the middle of a live match rather than being refused at the top of it. Slot 1 is
    the only slot that reaches left, so a missing left entry would make the whole left side
    of the board unusable for that purpose without anything saying so."""
    for purpose, sides in battle.DROPS.items():
        assert set(sides) == {"left", "right"}, f"{purpose} is missing a side"
    for slot in plan.REACH:
        assert {p for (s, p) in BOOK if s == slot} == set(battle.DROPS)


def test_the_five_destinations_are_five_different_places():
    """Each one is a claim about where a card should land, and two purposes that resolve to
    the same coordinate would make one of those claims decorative - a policy that carefully
    chose `push` over `attack` and then sent the identical drag."""
    for lane in ("left", "right"):
        drops = [sides[lane] for sides in battle.DROPS.values()]
        assert len(set(drops)) == len(drops), f"two {lane} purposes land in the same spot"


def test_the_depths_are_ordered_the_way_the_strategy_reads_them():
    """Deeper into their half means a smaller y, and the four lane depths have to run in the
    strategy's own order: `deep` past the river, `attack` at the bridge, `push` a body behind
    it, `defend` between the bridge and our tower. Any pair out of order is a card sent to do
    the opposite of what it was chosen for, which no log would show."""
    lane = "left"
    deep, attack, push, defend = (battle.DROPS[p][lane][1]
                                  for p in ("deep", "attack", "push", "defend"))
    assert deep < arena.RIVER < attack < push < defend
    assert defend < battle.SLOT_ROW_TOP, "a defence must land above our own card panel"
    # And the two that are not on the lane line are where they say they are: `deep` hard
    # against the outside of the playfield (measured 0.127..0.878), `spell-ours` at the
    # centroid of the quadrant whose activity chose it.
    assert battle.DROPS["deep"]["left"][0] < battle.DROPS["attack"]["left"][0]
    assert battle.DROPS["deep"]["right"][0] > battle.DROPS["attack"]["right"][0]
    for at in (battle.DROPS["deep"]["left"][0], battle.DROPS["deep"]["right"][0]):
        assert 0.127 < at < 0.878, "off the playfield entirely"
    # Both sides of `deep` are past the river whatever else differs about them, and they do
    # differ: the right one is held short by the Pass Royale denylist box. Asserted rather
    # than left implicit so that a later edit which quietly equalises them - by moving the
    # box, or by trusting the lobby to be gone - has to say so here.
    for lane in ("left", "right"):
        assert battle.DROPS["deep"][lane][1] < arena.RIVER
    assert battle.DROPS["deep"]["right"][1] > battle.DROPS["deep"]["left"][1], (
        "the right lane is the shallower one, and only because the banner box says so")
    assert battle.DROPS["spell-ours"]["left"][1] > arena.RIVER, "our half only"


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

def one_pass(window, **args) -> Match:
    """Run `play` for a fixed few passes and hand back what it counted."""
    match = Match(number=1)
    battle.play(window, match, panel_ref=battle.panel(window),
                **{"seconds": 6.0, "cadence": 1.0, "book": BOOK, "watching": False, **args})
    return match


def test_a_drag_is_judged_on_the_pass_after_it_was_sent(quiet):
    """The shape of the fix, asserted as a shape. `deploy` no longer answers the question at
    all - it returns one number, the slot reading - so `play` is the only place a card can be
    counted, and it counts last pass's drag against this pass's elixir.

    The count therefore lags the attempt by exactly one, which is what the two numbers below
    say: a run that sent N drags has judged N-1 of them and is still waiting on the last.
    """
    match = one_pass(FakeWindow(spends=0.40))

    assert match.attempts > 2
    assert match.unresolved == 1, "the last drag is sent and never judged"
    assert match.judged == match.attempts - 1
    assert isinstance(battle.deploy(FakeWindow(), attacks()[0]), float), (
        "deploy returns the slot reading and nothing else")


def test_a_drag_that_cost_no_elixir_is_not_a_card_played(quiet):
    """The measurement the whole "played better" claim rests on. Drags were sent either way -
    `drags` proves it - and the difference is only whether the bar went down."""
    window = FakeWindow(spends=0.0)

    match = one_pass(window)

    assert len(window.drags) == match.attempts > 2
    assert match.played == 0 and match.rate == 0.0


def test_elixir_going_down_is_a_card_played(quiet):
    """The positive case, and it has to be a *bounded* one: `spends` is 0.4 of the bar and
    `refill` is a realistic 0.03 a pass, so the fake can fund two cards and then it is broke.
    A run that reported every attempt as played would be a run whose fake was giving away
    elixir, which is exactly the shape of the bug this replaced."""
    match = one_pass(FakeWindow(spends=0.40))

    assert 0 < match.played <= 3, f"funded about two cards, counted {match.played}"
    assert match.per_purpose.get("attack", 0) == match.played


def test_regeneration_alone_is_never_read_as_a_card_played(quiet):
    """The direction that makes one segment a safe threshold. Elixir arrives every pass and
    arriving must never look like spending, so this is a bar that only ever fills - a full
    refill and no spend at all - and nothing in it may be counted."""
    match = one_pass(FakeWindow(spends=0.0, refill=0.30))

    assert match.attempts > 2
    assert match.played == 0


def test_regeneration_can_hide_a_spend_and_that_is_the_safe_direction(quiet):
    """The detector's one false answer, pinned so it stays the harmless one.

    Comparing two readings a pass apart means the difference is the spend *minus* whatever
    arrived in between. Here the fake refills faster than it spends, so a card really does
    leave the hand every pass and the bar reads the same both times - and the loop reports
    nothing played. Under-reporting costs a lane taint and a tank follow-up; over-reporting
    would have the driver believe it has troops on a board where it has none, and read its
    own empty lane as defended. So this asserts the miss rather than pretending it away.

    On the real window the two rates are nothing like this close: a pass is 0.9s, which buys
    about 0.3 of an elixir, against the 2 to 5 a card costs.
    """
    match = one_pass(FakeWindow(spends=0.40, refill=0.50))

    assert match.attempts > 2
    assert match.played == 0, "the refill covered every spend"


def test_the_slot_reading_is_kept_but_not_believed(quiet):
    """The confound, asserted rather than only written down. A drag that fails to deploy
    leaves its card selected - drawn larger and lit - so the slot changes and stays changed
    while nothing was paid for. A live run measuring the slot read twenty of its first
    twenty-one attempts as played, which no elixir budget allows.

    So the slot number is still taken, still logged, and has no say in `played`.
    """
    match = one_pass(FakeWindow(spends=0.0, slot_moves=1.0))

    assert match.slot_said == match.attempts, "the slot says yes to every one of them"
    assert match.played == 0, "and not one of them was paid for"


def test_the_last_attempt_is_kept_out_of_the_rate_rather_than_counted_against_it(quiet):
    """A match always ends with one drag in flight, because the pass that would judge it is
    the pass that stops. Counting it as a failure would make the rate depend on how long the
    match was - a two-attempt match would report 50% at best - so it is excluded and said
    out loud instead."""
    match = one_pass(FakeWindow(spends=0.40))

    assert match.unresolved == 1
    assert match.judged == match.attempts - 1
    assert "unjudged at the whistle" in match.line()
    assert match.rate == match.played / (match.attempts - 1)


def test_the_elixir_strip_is_outside_every_card_slot():
    """The bar has to be a different thing from the hand, or it would carry the same
    confound. `ELIXIR_STRIP` sits *below* the row - the cards can turn over, grey out and
    light up without touching it."""
    top = battle.ELIXIR_STRIP[1]
    for deploy in attacks():
        _, slot_top, _, slot_height = deploy.box
        assert top >= slot_top + slot_height, (
            f"the elixir strip at y {top} overlaps slot {deploy.slot}")


def test_deploy_asks_nothing_about_whether_the_card_landed():
    """Three signals have been tried inside `deploy` and all three were too early: the slot
    is confounded by the selection highlight, the next-card thumbnail waits on the hand-cycle
    animation, and the elixir bar waits on its own drain animation. The conclusion is
    structural rather than a tuned threshold - `deploy` sends the drag and does not judge it -
    so this asserts the structure, because a later edit that "just checks quickly" here would
    be the fourth version of the same mistake.
    """
    body = Path(battle.__file__).read_text(encoding="utf-8").split("def deploy(")[1]
    code = body.split("\ndef ")[0].split('"""')[2]
    assert "NEXT_CARD" not in code, "deploy is reading the thumbnail again"
    assert "elixir_showing" not in code, "deploy is reading the bar again"
    assert "SPEND" not in code, "deploy is deciding whether a card landed"


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
                cadence=2.5, book=BOOK, watching=False)

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
                cadence=2.5, book=BOOK, watching=False)

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
                cadence=2.5, book=BOOK, watching=False)

    assert "window ran out" in match.ended
    assert match.attempts > 1


def test_the_timer_is_the_backstop_when_the_end_goes_unnoticed(quiet):
    """The panel test is a threshold and thresholds can be wrong, so the timer stays. A
    match that never reads as finished stops on the clock, with a count to report."""
    window = FakeWindow()
    panel_ref = battle.panel(window)
    match = Match(number=1)

    battle.play(window, match, seconds=10.0, panel_ref=panel_ref,
                cadence=2.5, book=BOOK, watching=False)

    assert "ran out with the match still on" in match.ended
    # Four, exactly: a flat 2.5s cadence puts attempts at 0.0, 2.5, 5.0 and 7.5, and the
    # check at 10.0 finds the window spent. The count being arithmetic rather than a
    # measurement is the point of a flat cadence - the version this replaced fitted a fifth
    # attempt in the same ten seconds by tightening itself mid-window on a bad signal.
    assert match.attempts == 4 and match.seconds >= 10.0


def test_a_quiet_opening_board_sends_the_tank_down_the_opening_lane(quiet):
    """The plainest thing the strategy asks for, end to end through `play`. Nothing is
    attacking, both their towers stand, and there is a Giant in a slot that reaches right -
    so every attempt is that Giant at the bridge on the right, which is rule 1 and rule 3.

    Worth going through `play` rather than only through `plan.decide` because the coordinate
    is the thing that reaches the game: a policy that chose the right slot and a catalogue
    that resolved it to the wrong drop point would both look correct on their own.
    """
    window = FakeWindow()
    match = Match(number=1)

    battle.play(window, match, seconds=15.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=False)

    assert match.attempts > 3
    assert set(match.per_slot) == {3}, "the Giant is in slot 3 and nothing outranks it"
    assert {drop for _, drop in window.drags} == {battle.DROPS["attack"]["right"]}
    assert match.holds == 0, "with 10 elixir there is nothing to wait for"


def test_the_best_card_in_an_unreachable_slot_is_left_there(quiet):
    """Slot 2's every path crosses the Battle button's box, so a Giant sitting in it is a
    Giant that cannot be played, and the driver plays the next thing the strategy names
    instead of reaching for it.

    Asserted from the outside rather than in `plan`, because the failure mode is not a
    refusal: the catalogue has no slot-2 gesture at all, so a policy that chose one would
    raise `KeyError` in the middle of a live match rather than being stopped at the top of
    it. Cheaper to be certain the choice never happens.
    """
    window = FakeWindow(state=board(cards=("knight", "giant", "minions", "arrows")))
    match = Match(number=1)

    battle.play(window, match, seconds=15.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=False)

    assert 2 not in match.per_slot
    assert set(match.per_slot) == {3}, "minions support the right lane in the Giant's place"
    grabs = {start[0] for start, _ in window.drags}
    assert SLOT_FIRST + SLOT_PITCH not in grabs, "slot 2's card was picked up"


# --- what it can see ---------------------------------------------------------
#
# The newest part of this file and the part with the most ways to be quietly wrong, because
# a detector that reports nothing and a detector that reports everything both produce a run
# that finishes and a log that reads fine. So the tests come in three layers: the geometry
# is where it says it is, the reading says the right thing about a board, and the *action*
# taken on the reading is one of the six vetted gestures.

def test_the_arena_stops_where_the_card_panel_starts():
    """Overlap here would be the worst kind of bug in this file: silent and self-inflicted.

    The card panel changes constantly and none of it is the board - the cards turn over, the
    elixir bar fills, the next-card thumbnail advances. An arena box reaching down into any
    of that would report our own interface as enemy activity, in our own half, continuously,
    and the run would defend against the elixir bar for three minutes.
    """
    left, top, width, height = arena.ARENA
    assert top + height <= arena.PANEL_TOP, "the arena reaches into the card panel"
    assert top + height <= battle.SLOT_ROW_TOP, "the arena reaches into the card row"
    for fx, fy, fw, fh in PANEL_EDGES:
        assert fy >= top + height, "the arena overlaps a panel sliver"
    assert battle.NEXT_CARD[1] >= top + height, "the arena overlaps the next-card thumbnail"
    assert 0.0 <= left and left + width <= 1.0, "the arena runs off the window"


def test_the_river_lands_inside_the_arena_and_splits_it_about_evenly():
    """The one number here whose being wrong would not show up as an error, only as a bot
    that defends its opponent's half. Measured at 0.432 off a real frame; what is asserted
    is the consequence - both halves exist and neither is a sliver."""
    _, top, _, height = arena.ARENA
    assert top < arena.RIVER < top + height
    split = arena.river_row()
    assert 0 < split < arena.ROWS, "one half of the board has no rows in it"
    assert abs(split - arena.ROWS / 2) <= 2, "the halves are lopsided"


def test_the_river_row_is_derived_from_the_arena_box_and_not_written_down():
    """A grid row is a fact about the box the grid covers, so moving the box has to move the
    row. Written down as an index instead, it would go on pointing at the same row of a
    different board - which is the failure mode that has no symptom.

    Proportional to within a rounding rather than exactly proportional: the river is 47.9%
    of the way down the box, so 20 rows put it at row 10 and 40 rows at row 19. Asserting
    exact doubling would be asserting that a grid row can be half a row.
    """
    assert arena.river_row(cols=6, rows=40) == pytest.approx(
        2 * arena.river_row(cols=6, rows=20), abs=1)
    assert arena.river_row(cols=6, rows=2) == 1
    _, top, _, height = arena.ARENA
    assert arena.river_row(cols=6, rows=1000) == round((arena.RIVER - top) / height * 1000)


def test_a_board_where_nothing_moved_names_no_lane():
    quiet_board = arena_grid(QUIET)

    threat = arena.read(quiet_board, quiet_board, delta=10)

    assert threat.lane is None and threat.pressure == 0.0
    assert "quiet" in threat.line()


@pytest.mark.parametrize("activity,expected", [
    ((0.0, 0.0, 0.5, 0.0), "left"),
    ((0.0, 0.0, 0.0, 0.5), "right"),
])
def test_the_lane_named_is_the_lane_that_moved(activity, expected):
    threat = arena.read(arena_grid(QUIET), arena_grid(activity), delta=10)

    assert threat.lane == expected
    assert threat.pressure == pytest.approx(0.5)


def test_a_push_forming_in_their_own_half_is_not_something_to_defend():
    """Their half being busy is the *opponent* deploying, and answering it by dropping a card
    in front of our own tower is worse than ignoring it - the card arrives before anything
    does. Only our own half decides the lane; their side is read, logged and not acted on.
    """
    threat = arena.read(arena_grid(QUIET), arena_grid((1.0, 1.0, 0.0, 0.0)), delta=10)

    assert threat.lane is None
    assert threat.their_left == pytest.approx(1.0), "but it is still measured"
    assert "theirs L100%/R100%" in threat.line()


def test_the_busier_of_two_busy_lanes_is_the_one_answered():
    """A double push is one card's worth of answer at a time, so the tie has to break
    somewhere, and the busier side is the side more is happening on."""
    both = arena.read(arena_grid(QUIET), arena_grid((0.0, 0.0, 0.3, 0.6)), delta=10)
    assert both.lane == "right"
    assert arena.read(arena_grid(QUIET), arena_grid((0.0, 0.0, 0.6, 0.3)),
                      delta=10).lane == "left"


def test_a_lane_that_barely_moved_is_below_the_threshold():
    """One cell of sixty is a tower's HP bar ticking or a flag animating, not a push.

    Both sides of `BUSY` are checked a cell clear of it rather than exactly on it, because a
    fraction of a quadrant has to round to a whole number of cells: `BUSY` itself asks for
    7.2 cells of 60, which is 7, which is 11.7% - just under its own threshold. Testing the
    boundary exactly would be testing Python's rounding.
    """
    one_cell = 1.0 / (arena.ROWS // 2 * (arena.COLS // 2))

    assert arena.read(arena_grid(QUIET), arena_grid((0.0, 0.0, one_cell, 0.0)),
                      delta=10).lane is None
    assert arena.read(arena_grid(QUIET), arena_grid((0.0, 0.0, arena.BUSY - one_cell, 0.0)),
                      delta=10).lane is None
    assert arena.read(arena_grid(QUIET), arena_grid((0.0, 0.0, arena.BUSY + one_cell, 0.0)),
                      delta=10).lane == "left"


def test_the_first_look_of_a_match_says_nothing_rather_than_saying_quiet():
    """There is no reading to be had from one frame, and the difference matters: `None`
    falls through to the cycle, while a `Threat` of zeroes is a positive claim that the
    board is calm - made at the one moment this file has no evidence either way."""
    window = FakeWindow(activity=(0.0, 0.0, 1.0, 0.0))
    watch = arena.Watch(delta=10)

    assert watch.see(window, 0.0) is None
    assert watch.see(window, 1.0).lane == "left", "and the second look does read"


def test_our_own_troops_walking_up_a_lane_are_not_reported_as_a_threat():
    """The confound a change test cannot see past. Movement in our half is an enemy push or
    it is the card we just put there, and the pixels are identical - so the only thing that
    tells them apart is that we know what we did. A run without this defends against itself:
    it drops a card, sees it move, calls that a threat, drops another into the same lane.
    """
    window = FakeWindow(activity=(0.0, 0.0, 1.0, 0.0))
    watch = arena.Watch(delta=10)
    watch.see(window, 0.0)
    watch.deployed_into("left", 1.0)

    threat = watch.see(window, 2.0)

    assert threat.lane == "left", "the movement is still measured and still logged"
    assert threat.trustworthy is False, "it is just not evidence about the opponent"
    assert "ours, ignored" in threat.line()


def test_the_lane_reads_again_once_our_own_card_has_walked_on():
    """The taint is a timer, not a latch. Left set, the first deploy into a lane would blind
    us to that lane for the rest of the match."""
    window = FakeWindow(activity=(0.0, 0.0, 1.0, 0.0))
    watch = arena.Watch(delta=10)
    watch.see(window, 0.0)
    watch.deployed_into("left", 1.0)

    assert watch.see(window, 1.0 + arena.OURS_FOR).trustworthy is True


# --- what it does about it ---------------------------------------------------

def test_only_the_slots_that_can_reach_a_lane_are_offered_for_it():
    """`slots_for` is a claim about the denylist, so it is checked against the denylist
    rather than against itself. The important half is the completeness: if either lane had
    no reachable slot, half of all threats would be unanswerable and the redirection would
    be a no-op that still logged "defending"."""
    target = Target(name="Clash Royale", exe="", denylist=DENYLISTS["clashroyale"])
    for lane in ("left", "right"):
        reachable = arena.slots_for(lane, battle.LANES)
        assert reachable, f"nothing can defend the {lane} lane"
        for gesture in (BOOK[(slot, "defend")] for slot in plan.REACH):
            legal = target.forbids_path(gesture.grab, gesture.drop) is None
            wants = battle.lane_of(gesture) == lane
            assert (gesture.slot in reachable) == (wants and legal)


def test_a_defence_drops_between_the_bridge_and_our_tower():
    """The depth is the other half of defending, and getting it wrong is invisible in a log:
    a defensive *lane* at an attacking *depth* sends the card to the bridge, where it walks
    away from the thing it was meant to meet."""
    assert battle.DEFEND_DEPTH > battle.DEPTH, "a defence has to land behind the bridge"
    assert battle.DEFEND_DEPTH < battle.SLOT_ROW_TOP, "and in front of our own card panel"
    target = Target(name="Clash Royale", exe="", denylist=DENYLISTS["clashroyale"])
    for slot in plan.REACH:
        gesture = BOOK[(slot, "defend")]
        assert gesture.drop[1] == battle.DEFEND_DEPTH
        assert target.forbids_path(gesture.grab, gesture.drop) is None
        assert gesture.purpose == "defend"


# --- the two of them together -----------------------------------------------

def test_the_loop_answers_a_lane_it_sees_moving(quiet):
    """End to end through `play`: a board with our own left lane busy, and the drags that
    come out of it. The first attempt cannot know - there is nothing to compare the first
    look with - so it attacks the opening lane, and every one after it defends the left.

    `spends=0.0` so nothing this run drags ever actually costs elixir, which is what keeps
    the lane readable: with no card of ours on the board, the movement can only be theirs.
    """
    window = FakeWindow(activity=(0.0, 0.0, 0.9, 0.0), spends=0.0)
    match = Match(number=1)

    battle.play(window, match, seconds=12.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=True)

    assert match.attempts > 2
    assert match.defences == match.attempts - 1, "every look after the first should answer"
    assert match.defended == 0, "and none of them deployed, which is why it kept answering"
    _, first_drop = window.drags[0]
    assert first_drop == battle.DROPS["attack"]["right"], "the first look cannot read"
    for _, drop in window.drags[1:]:
        assert drop == battle.DROPS["defend"]["left"]
    # The Knight defends and the Giant does not, which is rule 3 in the drag log: slot 1
    # holds the Knight and slot 3 the Giant, and only slot 1 was used after the first pass.
    assert {start[0] for start, _ in window.drags[1:]} == {SLOT_FIRST}


def test_a_drag_that_played_nothing_does_not_blind_its_own_lane(quiet):
    """Most drags fail, so tainting a lane on the gesture rather than on the card would
    switch the detector off almost permanently. The comparison is against the same run with
    cards landing, where the taint does fire and the loop goes back to attacking."""
    args = dict(seconds=12.0, cadence=1.0, book=BOOK, watching=True)
    busy = (0.0, 0.0, 0.9, 0.0)

    nothing_lands = Match(number=1)
    window = FakeWindow(activity=busy, spends=0.0)
    battle.play(window, nothing_lands, panel_ref=battle.panel(window), **args)

    cards_land = Match(number=2)
    window = FakeWindow(activity=busy, spends=0.40)
    battle.play(window, cards_land, panel_ref=battle.panel(window), **args)

    assert nothing_lands.defences == nothing_lands.attempts - 1
    assert cards_land.defences < cards_land.attempts - 1
    assert cards_land.defended > 0, "and the defences it did send landed"


def test_blind_takes_no_picture_of_the_arena_at_all(quiet):
    """The control condition has to be the loop without the look, not the loop with the
    answer thrown away - otherwise "is watching worth the 12ms" is measured against a run
    that also spends the 12ms. Blind still reads the hand and the towers: it has to, to play
    at all, so what `--blind` now isolates is the arena watch and nothing else."""
    window = FakeWindow(activity=(0.0, 0.0, 0.9, 0.0))
    match = Match(number=1)

    battle.play(window, match, seconds=12.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=False)

    assert window.arena_grabs == 0
    assert match.defences == 0, "a lane it cannot see is a lane it never defends"
    assert {drop for _, drop in window.drags} == {battle.DROPS["attack"]["right"]}


def test_a_held_pass_sends_nothing_and_comes_back_sooner(quiet):
    """Rule 4's most valuable case: a Giant one elixir away, and a Knight that could be
    dumped now. Dumping it is what stops the Giant ever being played, so the pass holds -
    and holding is only worth doing if it is short, because the elixir it is waiting for
    arrives on the game's clock rather than on this loop's.

    `refill=0.0` freezes the bar, because this is a test about one moment's decision taken
    repeatedly. Let the fake regenerate and the fifth elixir eventually arrives, at which
    point holding for the Giant is the wrong answer and the loop rightly stops - a different
    and also correct behaviour, which `plan.affordable_soon` has its own tests for.
    """
    window = FakeWindow(refill=0.0,
                        state=board(cards=("knight", "minions", "giant", "musketeer"),
                                    elixir=4, grey=(3, 4)))
    match = Match(number=1)

    battle.play(window, match, seconds=6.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=False, hold_cadence=0.5)

    assert match.attempts == 0 and window.drags == []
    assert match.holds == 12, "6.0s of holding at 0.5s a pass"


def test_the_hold_interval_is_shorter_than_the_one_that_pays_for_a_drag(quiet):
    """The whole reason there are two intervals. A pass that sends nothing costs two small
    captures - about 20ms against the drag's 430 - so there is nothing for it to be waiting
    out, and every extra tenth is a tenth of the held card being played late."""
    assert battle.HOLD_CADENCE < battle.CADENCE
    drag = (battle.DRAG_HOVER + controller.DRAG_GRAB
            + controller.DRAG_STEPS * controller.DRAG_GLIDE + controller.DRAG_SETTLE)
    assert battle.HOLD_CADENCE < drag, "a hold pays no drag, so it need not wait one out"
    assert battle.HOLD_CADENCE > 0.05, "and it is a wait, not a spin"


def test_a_fallen_tower_moves_the_attack_to_that_side_and_deeper(quiet):
    """Rules 1 and 2, end to end and in the coordinates that reach the game. Their left tower
    is gone, so the plan switches off the opening lane onto the left and drops hard against
    the outside edge in their half - as far from their surviving right tower as the arena
    allows while still walking at the king."""
    window = FakeWindow(state=board(cards=("giant", "minions", "musketeer", "knight"),
                                    standing="xOOO"))
    match = Match(number=1)

    battle.play(window, match, seconds=10.0, panel_ref=battle.panel(window),
                cadence=2.5, book=BOOK, watching=False)

    assert match.attempts > 2
    assert {drop for _, drop in window.drags} == {battle.DROPS["deep"]["left"]}
    assert set(match.per_purpose) == {"deep"}
    assert match.crowns_for == 1 and match.crowns_against == 0


# --- how fast the loop can go ------------------------------------------------

def test_the_hover_before_a_drag_is_the_trimmed_one(quiet):
    """120ms off every attempt, and the only reason it is safe to trim is that the target is
    a static card in a panel this file has dragged from thousands of times. The pause exists
    so the press is hit-tested where the pointer now is rather than where it was, so what it
    has to clear is a few frames - not the generous default for a UI nobody has measured."""
    battle.deploy(FakeWindow(), attacks()[0])

    assert battle.DRAG_HOVER < 0.20, "0.20 is the default this is trimming"
    assert battle.DRAG_HOVER >= 4 / 60, "fewer than four frames at 60Hz is not a pause"


def test_the_loop_spends_more_time_waiting_than_working():
    """What the cadence has to clear, computed from the drag's own constants rather than
    asserted as a number. The measurement that made this worth changing is in the docstring:
    the seven captures a pass takes cost 48ms all told, so the cadence and the drag are the
    entire cycle and captures are not worth trimming."""
    drag = (battle.DRAG_HOVER + controller.DRAG_GRAB
            + controller.DRAG_STEPS * controller.DRAG_GLIDE + controller.DRAG_SETTLE)
    captures = 7 * 0.012        # generous: the small ones measured 6ms, the arena 12ms

    assert drag + captures < battle.CADENCE, "the interval would stop meaning anything"
    assert battle.CADENCE < 2.8, "slower than the elixir rate would leave elixir unspent"


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


def test_a_screen_that_changed_but_has_no_elixir_bar_is_not_a_board(quiet):
    """The second run's failure, and the one the change test could not catch. That run began
    on a loading screen, so the reference picture was a loading screen, so of course the
    screen "changed" - a percentage bar advances by itself. Four gestures went into artwork.
    A change test can only say the screen is not the one it started on; it takes a positive
    test to say the screen is a board."""
    window = FakeWindow(agreement=1.0)
    lobby = window.grab(GRID_COLS, GRID_ROWS)
    window.agreement = 0.3          # the screen did change...
    window.bar_showing = False      # ...but into something with no elixir bar on it

    with pytest.raises(SystemExit, match="still reads only"):
        battle.require_board(window, lobby)
    assert window.drags == []


def test_a_bar_that_has_not_been_drawn_yet_is_waited_for(quiet, monkeypatch):
    """The refusal that was wrong. A run was turned away from a board with all four towers up,
    2:53 on the clock and eight elixir showing, because the single look landed on the match's
    opening countdown - and the frame the refusal saved to disk already had the bar in it.

    So the bar is waited for. The fake starts with none and grows one on the third look, and
    the gate has to accept rather than refuse - while still sending nothing, because a gate
    that deploys to prove a point is not a gate.
    """
    monkeypatch.setattr(battle, "BAR_WAIT", 0.0)
    window = FakeWindow(agreement=1.0)
    lobby = window.grab(GRID_COLS, GRID_ROWS)
    window.agreement = 0.3
    window.bar_showing = False

    looks = 0
    was = battle.elixir_showing

    def late(controller):
        nonlocal looks
        looks += 1
        if looks >= 3:
            controller.bar_showing = True
        return was(controller)

    monkeypatch.setattr(battle, "elixir_showing", late)
    battle.require_board(window, lobby)

    assert looks == 3, "it accepted on the look the bar appeared, not before or after"
    assert window.drags == []


def test_the_lobby_is_not_photographed_while_it_is_still_moving(quiet, monkeypatch):
    """The other half of that fix, and the root of it: the reference picture must be of
    something still. A loading screen cannot be described without a content test, but it can
    be ruled out by the one thing that is true of it and false of a lobby - it moves."""
    monkeypatch.setattr(battle, "SETTLE_WAIT", 0.0)
    monkeypatch.setattr(battle, "SETTLE_TRIES", 3)

    moving = FakeWindow()
    monkeypatch.setattr(battle, "fraction_changed", lambda *a, **k: 0.40)
    with pytest.raises(SystemExit, match="REFUSED to start"):
        battle.settled_lobby(moving)
    assert moving.clicks == [], "and it refuses before tapping anything"

    monkeypatch.setattr(battle, "fraction_changed", lambda *a, **k: 0.01)
    assert battle.settled_lobby(FakeWindow()) is not None


def test_a_lobby_that_settles_late_is_still_accepted(quiet, monkeypatch):
    """A cold client takes about twenty seconds to reach the main screen, so the gate waits
    rather than refusing a client that is merely not ready. It is a wait with a limit, not a
    wait forever: a client stuck on a Content Update never becomes still."""
    monkeypatch.setattr(battle, "SETTLE_WAIT", 0.0)
    monkeypatch.setattr(battle, "SETTLE_TRIES", 5)
    readings = iter([0.40, 0.40, 0.40, 0.01])
    monkeypatch.setattr(battle, "fraction_changed",
                        lambda *a, **k: next(readings, 0.01))
    assert battle.settled_lobby(FakeWindow()) is not None


def test_the_stillness_threshold_leaves_room_for_the_screens_own_animation():
    """The main screen has running water and waving flags and measured 0.971 agreement with
    itself, i.e. about 0.029 of self-movement. STILL has to sit above that or the gate would
    refuse every lobby there has ever been."""
    assert 0.029 < battle.STILL < 1 - battle.SAME_SCREEN


# --- what the run reports ---------------------------------------------------

def test_a_matchs_own_line_says_what_it_did():
    """Including the reading it does not believe. The slot number stays in the line so
    that the next run's log can be compared against the one that got this wrong, rather
    than the comparison having to be reconstructed from a commit message."""
    match = Match(number=3, attempts=50, played=20, slot_said=48,
                  per_slot={1: 12, 4: 8}, defences=9, defended=4, seconds=142.0,
                  ended="both ends of the card panel are gone")

    line = match.line()

    assert "match 3" in line and "20 of 50 cards played (40%)" in line
    assert "slot 1: 12" in line and "slot 4: 8" in line
    assert "142s" in line
    assert "over-reports, said 48" in line
    # Both numbers, because either alone is unreadable: nine attempts redirected says the
    # detector fired, four landing says whether the redirection did anything.
    assert "4 of 9 defensive attempts landed" in line


def test_two_runs_of_the_same_match_do_not_photograph_over_each_other(tmp_path,
                                                                     monkeypatch):
    """The A/B this was written for lost its control half to exactly this. Both runs played
    match 1, both wrote `battle-m1-end.png`, and the result screen is the only place the
    crowns exist - so the second run silently deleted the first run's score."""
    monkeypatch.setattr(battle, "OUT", tmp_path)
    window = FakeWindow()

    written = []
    for label in ("blind", "watch"):
        monkeypatch.setattr(battle, "RUN_LABEL", label)
        written.append(battle.shoot(window, "m1-end").name)

    # The names, not the files: the fake window reports a size rather than encoding a PNG,
    # so there is nothing on disk to count. Distinct paths is the whole property anyway.
    assert written == ["battle-blind-m1-end.png", "battle-watch-m1-end.png"]


def test_an_unlabelled_run_writes_the_names_the_old_frames_on_disk_have(tmp_path,
                                                                       monkeypatch):
    """The label is a prefix and not a rename. Frames already in `out/` from before this
    existed are still comparable with a run started with `--label ""`, which is the only
    reason the empty label is allowed to mean anything at all."""
    monkeypatch.setattr(battle, "OUT", tmp_path)
    monkeypatch.setattr(battle, "RUN_LABEL", "")

    assert battle.shoot(FakeWindow(), "m1-end").name == "battle-m1-end.png"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
