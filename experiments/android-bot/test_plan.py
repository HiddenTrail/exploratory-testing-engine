"""Does the policy follow the four rules it was given?

These are the tests that used to live in `test_battle.py` against `battle.choose`, rewritten
for `plan.decide`. They moved because the decision moved: `choose` picked a slot and a depth
from a threat reading, and `decide` picks them from a threat reading *plus* the hand and the
tower state, which is what made the strategy expressible at all.

Nothing here touches a window, a frame or a capture. A `Hand` and a `Towers` are both plain
value objects, so the whole policy can be exercised by constructing the board it should be
looking at - which is the point of having split reading from deciding. What these cannot
check is whether the reader produces the board; that is `test_readers.py`.

Every test names the rule it is defending, because a policy test that only asserts the
current behaviour is a test that will be updated to match the next bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import arena  # noqa: E402
import hand as hand_module  # noqa: E402
import plan  # noqa: E402
import towers as towers_module  # noqa: E402

# A deck whose four cards cover the three roles the strategy names, in slots chosen so that
# the reachable ones matter: slot 1 (left) holds the knight that rule 3 defends with, slot 3
# (right) the giant that rule 3 attacks with, slot 4 (right) the musketeer that supports it,
# and slot 2 - the slot no lane can be reached from - holds a spell.
DECK = ("knight", "arrows", "giant", "musketeer")


def hand_of(cards=DECK, elixir=10, grey=(), empty=()):
    """A `Hand` with the named cards in slots 1..4. `grey` and `empty` are slot numbers."""
    slots = []
    for number, card in enumerate(cards, start=1):
        if number in empty:
            slots.append(hand_module.Slot(number, "empty"))
            continue
        state = "grey" if number in grey else "ready"
        slots.append(hand_module.Slot(number, state, card=card))
    return hand_module.Hand(tuple(slots), elixir)


def standing(marks="OOOO"):
    """`Towers` from four characters: their left, their right, ours left, ours right."""
    return towers_module.Towers(*(mark == "O" for mark in marks))


def moving(lane=None, how_much=0.30, trustworthy=True):
    """A `Threat` that reads `lane` as busy in our own half, or a quiet one."""
    ours = {"left": (how_much, 0.0), "right": (0.0, how_much), None: (0.0, 0.0)}[lane]
    return arena.Threat(0.0, 0.0, ours[0], ours[1], trustworthy=trustworthy)


# --- rule 1: one lane, and the fallen one after that -------------------------

def test_a_quiet_opening_board_commits_to_the_opening_lane_with_the_tank():
    """Rule 1 with nothing yet decided. Both their towers stand, so there is no fallen side
    to attack from, and the plan commits to the lane it can find cards for rather than
    splitting damage across two towers it will then take neither of."""
    move, why = plan.decide(hand_of(), standing("OOOO"), moving(None), attempts=0)
    assert move == plan.Move(3, "attack"), why
    assert plan.REACH[move.slot] == plan.OPENING_LANE
    assert "giant" in why


def test_a_fallen_tower_moves_the_attack_to_that_side():
    """Rule 1's second half, and the only thing that overrides the opening lane. Their left
    is gone, so the left lane is the one with a hole in it - even though two of the three
    usable slots reach right, which is what chose the opening lane in the first place."""
    move, why = plan.decide(hand_of(), standing("xOOO"), moving(None), attempts=0)
    assert plan.REACH[move.slot] == "left", why
    assert move.purpose == "deep"


def test_both_their_towers_down_stops_preferring_a_lane_on_tower_state():
    """`open_lane` is None when both are gone, because then the king is the only target and
    a lane preference no longer follows from anything measured. The plan falls back to the
    opening lane rather than inventing a reason to favour one side."""
    move, _ = plan.decide(hand_of(), standing("xxOO"), moving(None), attempts=0)
    assert plan.REACH[move.slot] == plan.OPENING_LANE
    assert move.purpose == "attack", "nothing is open, so nothing is dropped deep"


# --- rule 2: as far from their surviving tower as the arena allows ------------

def test_the_open_lane_is_the_only_one_dropped_deep():
    """Rule 2 only applies where the ground is unlocked, and the only evidence that it is
    unlocked is that the tower guarding it has fallen. A deep drop into a lane whose tower
    still stands deploys nothing at all, so the condition is not a preference."""
    open_left, _ = plan.decide(hand_of(), standing("xOOO"), moving(None), attempts=0)
    both_up, _ = plan.decide(hand_of(), standing("OOOO"), moving(None), attempts=0)
    assert open_left.purpose == "deep"
    assert both_up.purpose == "attack"


def test_support_drops_behind_a_tank_only_when_a_tank_actually_went_there():
    """Rule 2 applied to support. `push` is a body further back so a Musketeer walks in a
    Giant's shadow; with no Giant in front of it that is just a slower card arriving alone,
    so the same slot goes to the bridge instead. The tank is greyed here so that support is
    what gets offered."""
    board, up = hand_of(grey=(3,)), standing("OOOO")
    behind, why = plan.decide(board, up, moving(None), attempts=0, following="right")
    alone, _ = plan.decide(board, up, moving(None), attempts=0, following=None)
    assert behind == plan.Move(4, "push"), why
    assert alone == plan.Move(4, "attack")


def test_following_the_other_lane_is_not_following_this_one():
    """`following` is a lane, not a flag. A tank sent left does not put anything in front of
    a card dropped right, and a policy that read it as a boolean would trail support behind
    an empty lane for the six seconds the memory lasts."""
    move, _ = plan.decide(hand_of(grey=(3,)), standing("OOOO"), moving(None),
                          attempts=0, following="left")
    assert move == plan.Move(4, "attack")


# --- rule 3: giant attacks, ranged supports, knight defends ------------------

def test_a_lane_seen_moving_is_answered_and_not_attacked():
    """Rule 3's defensive half, and the ordering that matters most: stopping what is coming
    outranks spending on the plan. The knight in slot 1 reaches left, which is where the
    movement is, so it answers there rather than the giant pushing right."""
    move, why = plan.decide(hand_of(), standing("OOOO"), moving("left"), attempts=0)
    assert move == plan.Move(1, "defend"), why
    assert "defends left" in why


def test_a_tank_is_never_offered_a_defence():
    """Rule 3 again, in the negative. `DEFENDERS` leaves the tank out on purpose: a Giant
    spent stopping something a Knight would have stopped is the attack the strategy is
    built on, spent on the other side of the board."""
    assert "tank" not in plan.DEFENDERS
    # Right lane moving, and the only ready card that reaches right is the giant.
    move, why = plan.decide(hand_of(grey=(4,)), standing("OOOO"), moving("right"),
                            attempts=0)
    assert move != plan.Move(3, "defend"), why
    assert move.purpose == "attack", "it pushes with the tank instead of parking it"


def test_a_threat_in_a_lane_nothing_reaches_falls_through_to_the_plan():
    """A defence dropped into the wrong lane answers nothing and spends the elixir the next
    pass needs. With only the unreachable slot 2 and the right-hand slots playable, a left
    lane attack goes unanswered and the plan carries on rather than pretending."""
    move, why = plan.decide(hand_of(grey=(1,)), standing("OOOO"), moving("left"),
                            attempts=0)
    assert plan.REACH.get(move.slot) == "right", why
    assert "defends" not in why


# --- rule 4: no spells at empty space ---------------------------------------

def test_a_spell_is_spent_on_a_busy_lane_and_not_on_a_quiet_one():
    """Rule 4, exactly as it was given. `arrows` sits in slot 2, which reaches nothing, so
    the spell that can be tested is one in a reachable slot - and the test is the same
    either way: a lane at 30% busy is worth it and a lane under `SPELL_BUSY` is not."""
    spells = ("arrows", "knight", "giant", "musketeer")
    busy = arena.Threat(0.0, 0.0, plan.SPELL_BUSY + 0.1, 0.0, trustworthy=True)
    move, why = plan.decide(hand_of(spells, grey=(3, 4)), standing("OOOO"), busy,
                            attempts=0)
    assert move == plan.Move(1, "spell-ours"), why
    assert "spells left" in why


def test_a_lane_busy_enough_to_defend_is_not_always_busy_enough_to_spell():
    """The two thresholds are different numbers for a reason: `arena.BUSY` means something
    is coming, `SPELL_BUSY` means enough of it is coming to be worth a spell. Between them
    a card defends and a spell waits, which is rule 4 at its narrowest."""
    assert arena.BUSY < plan.SPELL_BUSY
    between = (arena.BUSY + plan.SPELL_BUSY) / 2
    spells = ("arrows", "knight", "giant", "musketeer")
    move, why = plan.decide(hand_of(spells, grey=(3, 4)),
                            standing("OOOO"),
                            arena.Threat(0.0, 0.0, between, 0.0), attempts=0)
    assert move != plan.Move(1, "spell-ours"), why


def test_a_spell_is_never_aimed_at_their_half():
    """Rule 4 met a measurement: `arena`'s their-half numbers move with the red no-deploy
    overlay rather than with anything on the board, so a spell aimed by them is a spell
    aimed at our own card selection. Their half reading 90% busy and ours reading nothing
    must produce no spell."""
    theirs = arena.Threat(0.90, 0.85, 0.0, 0.0, trustworthy=True)
    assert plan.busiest_ours(theirs) is None
    move, _ = plan.decide(hand_of(), standing("OOOO"), theirs, attempts=0)
    assert move.purpose != "spell-ours"


def test_an_untrustworthy_reading_aims_nothing():
    """Activity we put there ourselves is not a threat and not a target. `Threat` refuses to
    launder that and so does the policy."""
    ours = arena.Threat(0.0, 0.0, 0.9, 0.9, trustworthy=False)
    assert plan.busiest_ours(ours) is None
    move, why = plan.decide(hand_of(), standing("OOOO"), ours, attempts=0)
    assert move.purpose in ("attack", "deep", "push"), why


# --- doing nothing is a move -------------------------------------------------

def test_a_giant_one_elixir_short_is_worth_holding_a_pass_for():
    """The behaviour rule 4 generalises to: dumping the 3-elixir Knight because it is
    affordable is what stops the 5-elixir Giant ever being played. Identity survives
    greying - `hand` matches on luminance - which is what makes this possible at all."""
    move, why = plan.decide(hand_of(grey=(3,), elixir=4), standing("OOOO"),
                            moving(None), attempts=0)
    assert move is None, why
    assert "holding for giant" in why


def test_nothing_is_held_for_while_a_lane_is_moving():
    """A Knight held back for a Giant is a Knight arriving after the fight. The hold is only
    ever taken on a quiet board."""
    move, why = plan.decide(hand_of(grey=(3,), elixir=4), standing("OOOO"),
                            moving("left"), attempts=0)
    assert move is not None, why


def test_two_elixir_short_is_too_far_to_wait():
    """`affordable_soon` is one elixir and not two. Waiting two is holding through a whole
    cadence of income for a card that may be answered by the time it lands."""
    move, why = plan.decide(hand_of(grey=(3,), elixir=3), standing("OOOO"),
                            moving(None), attempts=0)
    assert move is not None, why


def test_a_greyed_card_with_a_full_bar_is_not_held_for():
    """A contradiction rather than a board: greyed is the game saying it cannot be paid for,
    and ten elixir says it can. One of the two readings is wrong and neither can be re-read
    into agreement, so the resolution has to be to play something. The first version of
    `affordable_soon` had no lower bound and answered yes here, which would have held every
    pass for the rest of the match while the bar sat full - a stall with no error in it and
    no log line distinguishable from a legitimate wait."""
    assert not hand_of(elixir=10).affordable_soon(5)
    move, why = plan.decide(hand_of(grey=(3,), elixir=10), standing("OOOO"),
                            moving(None), attempts=0)
    assert move is not None, why


def test_an_empty_hand_says_so_rather_than_saying_nothing():
    """The two ways of sending nothing have to be told apart in a log: four hundred passes
    of "held" is a policy that never spends, and four hundred of "nothing playable" is a
    cadence outrunning the elixir bar. Neither shows up as an error."""
    move, why = plan.decide(hand_of(grey=(1, 2, 3, 4), elixir=0), standing("OOOO"),
                            moving(None), attempts=0)
    assert move is None
    assert "nothing playable" in why


def test_every_branch_gives_a_reason():
    """Including the ones that do nothing. A `why` of "" would make the log unreadable in
    exactly the cases the log exists for."""
    boards = [
        (hand_of(), standing("OOOO"), moving(None)),
        (hand_of(), standing("xOOO"), moving("left")),
        (hand_of(grey=(1, 2, 3, 4)), standing("OOOO"), moving(None)),
        (hand_of(grey=(3,), elixir=4), standing("OOOO"), moving(None)),
        (hand_of(empty=(1, 2, 3, 4)), standing("xxxx"), moving("right")),
    ]
    for board, marks, threat in boards:
        _, why = plan.decide(board, marks, threat, attempts=0)
        assert why and why.strip() == why


# --- the constraint underneath all of it -------------------------------------

def test_no_slot_is_ever_offered_a_lane_it_cannot_reach():
    """The denylist box over the Battle button is what makes slot 2 unreachable and pins the
    other three to one side each. `offer` is the only place that is enforced in the policy,
    and every branch of `decide` goes through it, so this holds across the whole space of
    boards rather than at the one place it was written."""
    for marks in ("OOOO", "xOOO", "OxOO", "xxOO"):
        for lane in ("left", "right", None):
            for grey in ((), (1,), (3,), (1, 3), (1, 3, 4)):
                move, why = plan.decide(hand_of(grey=grey), standing(marks),
                                        moving(lane), attempts=0)
                if move is not None:
                    assert move.slot in plan.REACH, f"{marks} {lane} {grey}: {why}"


def test_slot_two_is_unreachable_and_stays_that_way():
    """Stated as its own test because it is a fact about the safety geometry rather than
    about the strategy, and because a future edit that adds slot 2 to `REACH` has to come
    past a test that says why it cannot be there."""
    assert 2 not in plan.REACH
    best = hand_of(("arrows", "giant", "arrows", "arrows"))
    move, why = plan.decide(best, standing("OOOO"), moving(None), attempts=0)
    assert move is None or move.slot != 2, why


def test_the_deck_turns_over_rather_than_dragging_one_slot_all_match():
    """`attempts` rotates the choice among equally suitable slots. Without it a policy that
    always takes the lowest slot leaves slot 4 holding whatever it holds for the rest of the
    match, which is how a run ends having played four cards eleven times."""
    board = hand_of(("knight", "arrows", "musketeer", "musketeer"))
    chosen = {plan.decide(board, standing("OOOO"), moving(None), attempts=n)[0].slot
              for n in range(4)}
    assert chosen == {3, 4}, "both right-hand slots get a turn"


def test_an_unnamed_card_is_played_and_not_jammed_behind():
    """A card the library cannot name is playable with an unknown purpose, which is what the
    driver assumed about every card before it could read the panel at all. Refusing to play
    it would jam the hand behind the one card the library is missing."""
    unknown = hand_module.Hand(
        (hand_module.Slot(1, "grey"),
         hand_module.Slot(2, "grey"),
         hand_module.Slot(3, "ready", card=None, gap=31.0),
         hand_module.Slot(4, "grey")), 10)
    move, why = plan.decide(unknown, standing("OOOO"), moving(None), attempts=0)
    assert move == plan.Move(3, "attack"), why
    assert "unnamed" in why and "31" in why


def test_the_other_lane_is_the_last_resort_and_says_so():
    """When nothing reaches the chosen lane the plan will use the other one rather than pass,
    because a card played into the wrong lane still defends a tower and a card not played is
    elixir capped. The `why` has to record that it was a fallback, or a log of a match spent
    entirely in the wrong lane reads identically to one spent in the right one."""
    left_only = hand_of(grey=(3, 4))          # only slot 1, which reaches left
    move, why = plan.decide(left_only, standing("xOOO"), moving(None), attempts=0)
    assert plan.REACH[move.slot] == "left", why
    # ...and with the open lane on the right, the same hand goes left and admits it.
    move, why = plan.decide(left_only, standing("OxOO"), moving(None), attempts=0)
    assert plan.REACH[move.slot] == "left"
    assert "nothing reaches right" in why


def test_no_reading_at_all_still_plays_the_plan():
    """`--blind` and a failed grab both arrive here as `threat=None`. That is not a calm
    board and it is not a reason to stop: the hand and the towers are still readable, so the
    plan proceeds without the defensive half of rule 3."""
    move, why = plan.decide(hand_of(), standing("OOOO"), None, attempts=0)
    assert move == plan.Move(3, "attack"), why


def test_no_tower_reading_falls_back_to_the_opening_lane():
    """`towers=None` should not silently become "both towers down" or "left is open". The
    opening lane is the answer when there is nothing to override it."""
    assert plan.attack_lane(None) == plan.OPENING_LANE
    move, _ = plan.decide(hand_of(), None, moving(None), attempts=0)
    assert plan.REACH[move.slot] == plan.OPENING_LANE


@pytest.mark.parametrize("purpose", ["attack", "push", "defend", "deep", "spell-ours"])
def test_every_purpose_the_policy_can_name_has_a_vetted_gesture(purpose):
    """`Move.purpose` selects a drop coordinate out of the catalogue `battle.py` vets at
    startup. A purpose with no gesture behind it is a `KeyError` in the middle of a live
    match, so the two vocabularies are checked against each other here instead."""
    import battle
    for slot in plan.REACH:
        assert (slot, purpose) in battle.catalogue()
