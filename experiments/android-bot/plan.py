"""Which card to play, where, and when not to play one at all.

The strategy this implements was given as four rules:

1. Destroy one tower, then attack from that side.
2. Put our troops as far from their *surviving* tower as possible while still closing on
   the king.
3. Giant attacks, ranged supports, knight defends.
4. Don't throw spells at empty space.

Everything below is those four rules plus the constraints the game and the safety rules put
on them. The rules are the user's; the constraints are measured; nothing else is invented.

The constraint that shapes all of it
------------------------------------
**A slot can only reach its own side of the board.** Not a design choice - a consequence of
the denylist box over the Battle button (x 0.32..0.69, y 0.72..0.84). A drag from slot 1 to
the right bridge passes through x 0.346 at y 0.840, and one from slot 4 to the left bridge
passes through x 0.624 at y 0.720; both are inside the box, so both are refused before
anything is sent. Slot 1 reaches left, slots 3 and 4 reach right, and slot 2 reaches nothing
at all.

So "attack the open lane" is not a free choice. It is a preference expressed over whichever
cards happen to be sitting in slots that can reach that lane, and some passes will have
nothing suitable there. `decide` says so rather than substituting a card into a lane the
strategy did not ask for.

Doing nothing is a move
-----------------------
Rule 4 generalises past spells: an attempt is only free in elixir, not in time, and the
loop's own floor is about 0.43s of dragging. So `decide` may return no move, for two
reasons that are worth telling apart in a log:

- **nothing playable** - every slot is greyed or empty. Waiting is the only option.
- **holding for** a card - a greyed card is one elixir short and worth more than anything
  currently affordable. This is the rule-4 behaviour that matters most: dumping a Knight at
  4 elixir to "not waste" it is what stops the Giant ever being played.

Identity survives greying, which is what makes holding possible: `hand` matches on
luminance, so a greyed Giant is still recognisably a Giant with a cost of 5. A driver that
could only read affordable cards could not plan one step ahead.

Where the reading can be trusted
--------------------------------
`arena` reports movement in four quadrants, and **only the two in our own half mean
anything**. Their half is dominated by the red no-deploy overlay, which appears and
disappears with whether a card is currently selected - measured across a live match, the
their-half numbers toggle between roughly 85%/67% and 5%/8% with nothing on the board to
explain it. So spells are aimed at our own half only, which is also where rule 4 says a
spell has something to hit.
"""
from __future__ import annotations

from dataclasses import dataclass

# Which lane each slot can reach, from the denylist geometry above. Slot 2 is absent
# because it is unreachable, not because it is unimportant.
REACH = {1: "left", 3: "right", 4: "right"}

# The lane to commit to before either of their towers has fallen. Right, and for a
# measured reason rather than a preference: two of the three usable slots reach right and
# only one reaches left, so a right-lane plan finds a suitable card about twice as often.
# Concentrating on one lane is the whole of rule 1 - spreading damage evenly across two
# towers takes neither of them down, and rule 2 has nothing to work with until one falls.
OPENING_LANE = "right"

# Activity in one of our own quadrants at which a spell is worth spending. Higher than
# `arena.BUSY`, which is the threshold for "something is coming" - a spell wants a group,
# not a single troop, and a spell thrown at one Skeleton is rule 4's exact complaint.
SPELL_BUSY = 0.20

# Roles in the order they are offered a lane that needs defending. A tank is deliberately
# absent: rule 3 says the Giant attacks, and a Giant dropped on defence is 5 elixir spent
# stopping something a 3-elixir Knight would have stopped.
DEFENDERS = ("defence", "support", "spell")

# ...and the order for attacking. Spells are absent for the same kind of reason: rule 4.
ATTACKERS = ("tank", "support", "defence")


@dataclass(frozen=True)
class Move:
    """A decision: which slot to drag, and what depth to drop it at.

    `purpose` is not a label. It selects the drop coordinate from the catalogue `battle.py`
    built and vetted at startup, so a purpose that has no vetted gesture for that slot is a
    programming error caught before the run rather than a drag sent somewhere unchecked.
    """
    slot: int
    purpose: str


def offer(hand, lane: str, role: str | None, attempts: int):
    """A playable slot that reaches `lane` and holds `role`, or None.

    Rotated by `attempts` rather than always taking the lowest slot. The deck only turns
    over if the slots do, and a policy that always drags slot 3 leaves slot 4 holding
    whatever it holds for the rest of the match - which is how a driver ends a match having
    played four cards eleven times.
    """
    fits = [s for s in hand.ready()
            if REACH.get(s.slot) == lane and (s.role == role if role else s.card is None)]
    if not fits:
        return None
    return fits[attempts % len(fits)]


def busiest_ours(threat) -> tuple[str, float] | None:
    """The busier of our own two quadrants, if either is busy enough to spell.

    Our half only - see the module docstring on why their half is not a measurement.
    """
    if threat is None or not threat.trustworthy:
        return None
    left, right = threat.our_left, threat.our_right
    lane, activity = ("left", left) if left >= right else ("right", right)
    return (lane, activity) if activity >= SPELL_BUSY else None


def holding_for(hand, threat):
    """A greyed card worth waiting one elixir for, or None.

    Only ever one elixir short, and only when nothing is attacking. Waiting two would be
    holding through a whole cadence of income for a card that may be answered by then, and
    waiting at all while a lane is moving is rule 3's Knight arriving after the fight.
    """
    if threat is not None and threat.trustworthy and threat.lane:
        return None
    if hand.ready():
        # Something is affordable. Only worth holding for a *better* card, and the only
        # role that outranks what is already in hand is the tank the plan is built on.
        best = max((s for s in hand.ready()), key=lambda s: s.cost or 0)
        candidates = [s for s in hand.slots
                      if s.state == "grey" and s.role == "tank"
                      and (s.cost or 99) > (best.cost or 0)]
    else:
        candidates = [s for s in hand.slots if s.state == "grey" and s.card]
    for slot in candidates:
        if slot.cost and hand.affordable_soon(slot.cost) and REACH.get(slot.slot):
            return slot
    return None


def attack_lane(towers) -> str:
    """The lane to push. Rule 1, and the whole of it."""
    if towers is None:
        return OPENING_LANE
    return towers.open_lane or OPENING_LANE


def attack_purpose(lane: str, towers, tank: bool, following: bool) -> str:
    """How deep to drop an attacking card.

    Rule 2 is entirely in here. While their tower on this lane stands, a card goes to the
    bridge and walks in. Once it has fallen, `deep` drops past the river and hard against
    the outside edge - as far from their surviving tower as the arena allows while still
    walking at the king.

    `following` is whether a tank went into this lane recently. Support belongs *behind* a
    tank, which means dropping deeper so it trails; support dropped deep with no tank in
    front of it is just a slow card, so with nothing to follow it goes to the bridge like
    everything else. Guessing "behind" unconditionally would spend the whole match walking
    Musketeers up an empty lane.
    """
    if towers is not None and towers.open_lane == lane:
        return "deep"
    if tank:
        return "attack"
    return "push" if following else "attack"


def decide(hand, towers, threat, attempts: int,
           following: str | None = None) -> tuple[Move | None, str]:
    """The move for this pass, and a sentence saying why, always.

    Order matters and it is the order of the rules: stop what is coming, then spend on the
    plan, then keep the deck moving so the plan has cards to spend. The `why` is returned
    for every branch including the ones that do nothing, because a match whose log says
    "held" four hundred times is a different bug from one that says "nothing playable" four
    hundred times, and neither shows up as an error.
    """
    # Rule 3, defending half: a lane in our own half is moving and the reading is one we
    # believe. Answer it with the cheapest thing that can, in role order.
    if threat is not None and threat.trustworthy and threat.lane:
        lane = threat.lane
        for role in DEFENDERS:
            pick = offer(hand, lane, role, attempts)
            if pick is None:
                continue
            if role == "spell":
                # A spell counts as a defence only against something worth a spell.
                busy = busiest_ours(threat)
                if busy is None or busy[0] != lane:
                    continue
                return (Move(pick.slot, "spell-ours"),
                        f"{pick.card} spells {lane} at {busy[1]:.0%} busy")
            return (Move(pick.slot, "defend"),
                    f"{pick.card or 'unnamed'} defends {lane}")
        # Nothing in a slot that reaches the busy lane. Falls through to the plan rather
        # than dropping a card into the other lane, which would answer nothing and spend
        # the elixir the next pass needs.

    held = holding_for(hand, threat)
    if held is not None:
        return None, (f"holding for {held.card} at {held.cost} with {hand.elixir} elixir")

    if not hand.ready():
        return None, "nothing playable - every slot greyed or empty"

    # Rules 1 and 2: push the lane the plan has chosen, deepest when it is open.
    lane = attack_lane(towers)
    for role in ATTACKERS:
        pick = offer(hand, lane, role, attempts)
        if pick is None:
            continue
        purpose = attack_purpose(lane, towers, tank=(role == "tank"),
                                 following=(following == lane))
        return Move(pick.slot, purpose), f"{pick.card} {purpose}s {lane}"

    # Rule 4 in its widest form: a spell with nothing to hit stays in the hand, and a card
    # this cannot name is played rather than held, because refusing to play an unknown card
    # would jam the hand behind the one card the library is missing.
    unnamed = offer(hand, lane, None, attempts)
    if unnamed is not None:
        return (Move(unnamed.slot, "attack"),
                f"unnamed card (nearest exemplar {unnamed.gap:.0f}) attacks {lane}")

    other = "left" if lane == "right" else "right"
    for role in ATTACKERS:
        pick = offer(hand, other, role, attempts)
        if pick is not None:
            purpose = attack_purpose(other, towers, tank=(role == "tank"),
                                     following=(following == other))
            return (Move(pick.slot, purpose),
                    f"{pick.card} {purpose}s {other} - nothing reaches {lane}")

    return None, f"nothing playable reaches either lane ({hand.line()})"
