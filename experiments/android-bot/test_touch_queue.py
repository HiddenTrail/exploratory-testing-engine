"""The touch queue's one load-bearing invariant, and the bug it exists to fix.

The invariant: **an admitted candidate must have a verdict by the time `prune_blocked`
runs.** It is worth a test file of its own because breaking it does not degrade a pass,
it destroys map data - `prune_blocked` retires "no verdict for this action" permanently,
into `screen.tried`, which is written to `ontology.json` and inherited by every later
pass. An action retired unsent this way can never be tried again by anything.

That is not hypothetical. The 320-second pass in `out/Clash Royale-20260903-122143`
recorded 15 actions and **not one** of them was aimed at an element the vetting call had
located: candidates were offered all at once, the element coordinates only exist *after*
the call that would have ruled on them, so all 19 lobby elements were offered unruled and
retired on the next step. 66 of that pass's 100 blocked actions read "never ruled on".

Runs under pytest, or standalone with `python experiments/android-bot/test_touch_queue.py`
(the harness lives on a sys.path insert, so both entry points need the same import).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

import pytest

from controller import Target  # noqa: E402
from recon import Screen, Variant  # noqa: E402
from target import DENYLISTS  # noqa: E402

from touch import (AWAY, QUEUE_SIZE, REFILL_AT, REFILL_BATCH,  # noqa: E402
                   REFILL_CALLS, TouchRecon, border_points)


class FakeController:
    """Everything `Recon.__init__` and the policy methods read off a controller, and
    nothing else. No window, no capture: the queue is decided from the map."""

    def __init__(self) -> None:
        self.target = Target(name="Clash Royale", exe="",
                             denylist=DENYLISTS["clashroyale"])
        self.notes: list[str] = []

    def note(self, message: str) -> None:
        self.notes.append(message)

    def say(self, message: str) -> None:
        pass


class FakeVetter:
    """A stand-in for `describe.make_vetter()`'s callable. Never called - `ask_about` is
    replaced in these tests - but it has to be non-None, because that is how the session
    knows whether it may ask anything at all."""


def session(tmp_path: Path) -> TouchRecon:
    return TouchRecon(FakeController(), tmp_path, vetter=FakeVetter())


def screen_with(elements: list[dict] | None = None, vetted: bool = False) -> Screen:
    """A screen as it stands at some point in a pass. `vetted` is the whole difference
    between the two states the queue behaves differently in."""
    screen = Screen(id="sc01", representative=b"", first_seen=0)
    screen.variants["sc01v1"] = Variant(id="sc01v1", key="k", fp=b"")
    if vetted:
        screen.vetting = {"name": "Lobby", "actions": {}, "elements": elements or []}
    return screen


def variant_of(screen: Screen) -> Variant:
    return next(iter(screen.variants.values()))


def rule(screen: Screen, action_ids, safe: bool = True) -> None:
    """What a vetting call's answer does to the map, and nothing more."""
    for action_id in action_ids:
        screen.vetting["actions"][action_id] = {"safe": safe, "why": "test"}


def recording_asks(recon: TouchRecon, safe: bool = True, fails: bool = False):
    """Replace `ask_about` with a recorder. Stands in for the real one because what is
    being tested is which actions are asked about and when - the base class's merging of
    an answer into the verdict dictionaries is its own code and its own concern."""
    asked: list[list[str]] = []

    def fake(screen, variant, actions, retire_unruled=False):
        asked.append([a.id for a in actions])
        assert retire_unruled, ("a top-up must retire what the model declines to rule "
                               "on, or the same candidate is re-offered every step")
        if fails:
            return False
        rule(screen, [a.id for a in actions], safe=safe)
        return True

    recon.ask_about = fake            # type: ignore[method-assign]
    return asked


def cleared(screen: Screen, elements: list[dict]) -> None:
    """Rule the element taps safe, which a top-up is what really does.

    Needed because `after_first_vetting` rules only the seed - the blind repertoire read off
    the screen before it was vetted - and an element tap with no verdict is not permitted,
    so it is not in the queue at all. Tests about queue *order* have to get past that.
    """
    rule(screen, [f"click:{e['at'][0]:.3f},{e['at'][1]:.3f}" for e in elements])


def grid_elements(count: int) -> list[dict]:
    """`count` harmless elements at distinct points, all clear of every denylist box.

    Laid out between y 0.30 and 0.50, which on this game's layout is the middle of the
    window: the boxes cover the top strip (currencies, Pass Royale), the Battle button
    at y 0.72-0.84 and the bottom navigation.
    """
    return [{"label": f"button {i}", "what": "a navigation button",
             "at": [0.10 + 0.10 * (i % 8), 0.30 + 0.05 * (i // 8)]}
            for i in range(count)]


def after_first_vetting(recon: TouchRecon, elements: list[dict],
                        safe: bool = True) -> tuple[Screen, Variant]:
    """A screen in the state `Recon.vet` leaves it in, reached the way `vet` reaches it.

    Faithfulness matters here more than brevity: the seed is read off the screen *while
    it is still unvetted*, which is the only moment that clause applies, and the answer
    then arrives carrying both a verdict per seeded candidate and the element list. Any
    shortcut that installs `screen.vetting` first models a state a pass cannot be in.
    """
    screen = screen_with()
    seed = [a.id for a in recon.screen_actions(screen)]
    screen.vetting = {"name": "Lobby", "elements": elements,
                      "actions": {i: {"safe": safe, "why": "test"} for i in seed}}
    return screen, variant_of(screen)


# --- the plan ---------------------------------------------------------------

def test_the_seed_is_the_blind_repertoire_and_never_the_border_sweep(tmp_path):
    """Before the first vetting call nothing is known about where anything is, so the
    queue can only hold moves aimed at the window rather than at a control. The border
    sweep is aimed at nothing at all and has to wait: it is the answer to "this screen
    has run out of better ideas", which is not knowable yet."""
    recon = session(tmp_path)
    screen = screen_with()

    offered = [a.id for a in recon.screen_actions(screen)]

    assert len(offered) == QUEUE_SIZE
    assert sum(1 for a in offered if a.startswith("drag:")) == 4
    assert sum(1 for a in offered if a.startswith("click:")) == len(AWAY)
    assert sum(1 for a in offered if a.startswith("scroll:")) == 1
    # Every border point bar two: `plan` dedupes by point, and two of the three away-taps
    # are already border points - both edge midpoints, (0.03, 0.50) and (0.97, 0.50) - so
    # the sweep's copies of them are dropped rather than queued twice. Asserted rather
    # than tolerated, because `AWAY` and `BORDER_ALONG` were written independently for
    # different jobs, and the overlap is a coincidence of two constants that could stop
    # coinciding. What it means in practice: the sweep is ten new taps, not twelve, and
    # two of them are paid for early as modal dismissals.
    borders = {f"click:{x:.3f},{y:.3f}" for x, y in border_points()}
    assert borders & set(offered) == {"click:0.030,0.500", "click:0.970,0.500"}


def test_element_taps_lead_the_plan_once_the_vetting_call_has_answered(tmp_path):
    """The whole reason the queue is ordered rather than shuffled: a coordinate somebody
    read a label at is better evidence than the middle of the window."""
    recon = session(tmp_path)
    screen = screen_with(grid_elements(3), vetted=True)

    plan = [a.id for a in recon.plan(screen)]

    assert plan[:3] == ["click:0.100,0.300", "click:0.200,0.300", "click:0.300,0.300"]
    assert plan[3].startswith("drag:"), "swipes come after the located controls"
    assert plan[-1] == f"click:{border_points()[-1][0]:.3f},{border_points()[-1][1]:.3f}"


def test_money_words_keep_an_element_out_of_the_plan_and_are_noted_once(tmp_path):
    """The filter has to bite in `plan`, not in `permitted`: an element that never becomes
    a candidate cannot be cleared by a later call on another appearance of the screen.

    The note is asserted to appear exactly once because `plan` is walked several times a
    step - `next_action`, `prune_blocked` and the frontier search each walk it - and a
    note per walk would bury the pass's real findings under duplicates of this one."""
    recon = session(tmp_path)
    screen = screen_with([
        {"label": "Gem pack", "what": "buy 500 gems for EUR 4.99", "at": [0.5, 0.40]},
        {"label": "Deck", "what": "opens the card deck", "at": [0.5, 0.45]},
    ], vetted=True)

    for _ in range(3):
        plan = [a.id for a in recon.plan(screen)]

    assert "click:0.500,0.450" in plan
    assert "click:0.500,0.400" not in plan
    money_notes = [n for n in recon.controller.notes if "must not touch" in n]
    assert len(money_notes) == 1 and "Gem pack" in money_notes[0]


def test_an_element_outside_the_window_is_dropped_out_loud(tmp_path):
    """Measured: five of 99 located elements came back at y 1.33, off the bottom of a
    1121x1993 window, and all five were sc07's bottom navigation - the row a touch UI most
    needs. `is_fraction` dropped them, correctly and silently, so a systematic model error
    read as a screen that happened to have no navigation."""
    recon = session(tmp_path)
    screen = screen_with([
        {"label": "Bottom nav: chest icon", "what": "opens chests", "at": [0.09, 1.33]},
        {"label": "Deck", "what": "opens the card deck", "at": [0.35, 0.45]},
    ], vetted=True)

    for _ in range(3):
        plan = [a.id for a in recon.plan(screen)]

    assert "click:0.350,0.450" in plan
    dropped = [n for n in recon.controller.notes if "not a point inside the window" in n]
    assert len(dropped) == 1 and "chest icon" in dropped[0]


# --- the invariant ----------------------------------------------------------

def one_step(recon: TouchRecon, screen: Screen, variant: Variant) -> str:
    """The tail of `Recon.step`, in its real order, with the real methods.

    Written out rather than stubbed because the order *is* the thing under test: the
    top-up hook runs, then `prune_blocked` retires whatever is still refused, then
    `next_action` picks. Anything the top-up failed to buy a verdict for is destroyed
    between the first line and the third, and only running them in this order shows it.
    """
    recon.ask_about_escalated(screen, variant)
    recon.prune_blocked(screen, variant)
    action = recon.next_action(screen, variant)
    if action is None:
        return ""
    screen.tried.add(action.id)          # what `take` does, minus the window
    recon.actions_taken += 1
    return action.id


def unsent(recon: TouchRecon) -> dict[str, str]:
    """Blocked actions retired for want of a verdict - the measured bug, as the report
    prints it. On the 320-second pass this was 66 of 100 entries."""
    return {key: why for key, why in recon.blocked.items() if "no verdict" in why}


def test_no_candidate_is_ever_retired_for_want_of_a_verdict(tmp_path):
    """The regression, driven through the real `prune_blocked`.

    Nineteen located elements and a screen worked until it runs dry. Every element the
    money filter allows and the denylist permits must end up either taken or refused by
    the model - never "never ruled on", which is the outcome that also puts it beyond the
    reach of every later pass."""
    recon = session(tmp_path)
    recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19))

    taken = [one_step(recon, screen, variant) for _ in range(40)]

    assert unsent(recon) == {}
    # And the queue's own reason for existing: element taps actually got pressed. The
    # code this replaced aimed none of its 15 recorded actions at one.
    element_taps = {f"click:{e['at'][0]:.3f},{e['at'][1]:.3f}" for e in grid_elements(19)}
    assert element_taps & set(taken)


def test_the_elements_the_queue_admits_are_the_ones_it_takes(tmp_path):
    """The counted version of the above: with four top-ups of four, sixteen of nineteen
    located elements get admitted, ruled and pressed, and the three left over are the
    honest cost of a budget."""
    recon = session(tmp_path)
    recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19))

    taken = {one_step(recon, screen, variant) for _ in range(40)}

    element_taps = {f"click:{e['at'][0]:.3f},{e['at'][1]:.3f}" for e in grid_elements(19)}
    assert len(element_taps & taken) == REFILL_CALLS * REFILL_BATCH


def test_a_failed_top_up_unplans_its_batch_rather_than_losing_it(tmp_path):
    """A network error must not cost the map four candidates permanently. Left admitted
    and unruled they would be retired by the very next line of `Recon.step` - so this
    asserts on `blocked` after that line has actually run."""
    recon = session(tmp_path)
    recording_asks(recon, fails=True)
    screen, variant = after_first_vetting(recon, grid_elements(8))
    screen.tried.update(a.id for a in recon.ready(screen, variant))

    one_step(recon, screen, variant)

    assert unsent(recon) == {}
    assert recon.refills["sc01"] == 0, "a call that bought nothing spent no budget"
    assert any("unplanned again" in n for n in recon.controller.notes)
    assert recon.admitted["sc01"] == set()


# --- the pacing -------------------------------------------------------------

def test_no_top_up_while_the_queue_is_more_than_half_full(tmp_path):
    """"After half of the queue is done" - so a freshly vetted screen with seven cleared
    moves ahead of it buys nothing, and the pass spends its next seconds moving.

    Seven of eight, because the downward swipe is denylisted on this game - see
    `test_the_downward_swipe_is_denylisted_because_of_where_it_ends`."""
    recon = session(tmp_path)
    asked = recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19))

    recon.ask_about_escalated(screen, variant)

    assert asked == []
    assert len(recon.ready(screen, variant)) == QUEUE_SIZE - 1


def test_the_top_up_fires_at_half_and_buys_one_call_for_the_batch(tmp_path):
    recon = session(tmp_path)
    asked = recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19))
    # Half the queue used up, which is the trigger the person who asked for this named.
    screen.tried.update(a.id for a in recon.ready(screen, variant)[:QUEUE_SIZE - REFILL_AT])

    recon.ask_about_escalated(screen, variant)

    assert len(asked) == 1, "one vetting call for the whole batch, not one per candidate"
    assert asked[0] == ["click:0.100,0.300", "click:0.200,0.300",
                        "click:0.300,0.300", "click:0.400,0.300"]
    assert recon.refills["sc01"] == 1


def test_refusals_count_as_used_up_so_a_stuck_screen_tops_up_at_once(tmp_path):
    """The situation the queue was asked for: a screen the model refuses most of. Eight
    candidates and six refusals is two moves left, not eight, and counting untried
    instead of ready would leave the session sitting there looking busy."""
    recon = session(tmp_path)
    asked = recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19), safe=False)
    permitted_ids = [a.id for a in recon.screen_actions(screen) if recon.worth_asking(a)]
    rule(screen, permitted_ids[:2], safe=True)
    assert len(recon.ready(screen, variant)) == 2, "the rest of the eight were refused"

    recon.ask_about_escalated(screen, variant)

    assert len(asked) == 1 and len(asked[0]) == REFILL_BATCH
    assert len(recon.ready(screen, variant)) == 2 + REFILL_BATCH


def test_top_ups_run_out_and_then_the_screen_stops_being_a_frontier(tmp_path):
    """A budget that could not be exhausted would be a loop: `screen_has_frontier` sends
    the explorer back to any screen with plan left, and plan is nearly always left."""
    recon = session(tmp_path)
    recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(40))

    while one_step(recon, screen, variant):
        assert recon.actions_taken < 100, "the queue must run out, not run on"

    assert recon.refills["sc01"] == REFILL_CALLS
    assert not recon.screen_has_frontier(screen)
    # Forty elements, four top-ups of four: the plan outlives the budget, and what is
    # left over is left over. A screen that could always be topped up is a session that
    # never leaves it.
    assert len(recon.plan(screen)) > len(recon.screen_actions(screen))


def test_a_drained_queue_with_plan_left_is_still_a_frontier(tmp_path):
    """Otherwise the queue would quietly shrink the map: a screen worked down to an empty
    queue would read as finished with fourteen located elements never admitted, and
    nothing would ever travel back to spend a top-up on it."""
    recon = session(tmp_path)
    recording_asks(recon)
    screen, variant = after_first_vetting(recon, grid_elements(19))
    screen.tried.update(a.id for a in recon.ready(screen, variant))

    assert recon.ready(screen, variant) == []
    assert recon.screen_has_frontier(screen)


# --- the denylist -----------------------------------------------------------

def test_the_downward_swipe_is_denylisted_because_of_where_it_ends(tmp_path):
    """A finding, pinned so nobody spends an afternoon on it twice.

    Three of the four swipes are permitted and the fourth is refused, and the reason is
    not where it starts - the middle of the window is clear of every box - but the line it
    travels: (0.500, 0.500) to (0.500, 0.750) crosses the Battle button's box at
    y 0.72-0.84, and `Target.forbids_path` checks the line because a drag holds the button
    down the whole way. So this game's touch profile has three usable swipes, not four,
    and the missing one is downward.

    Right, and worth stating rather than working around: a drag that ends on the Battle
    button is a way of pressing it. The cost is that vertical scrolling can only be probed
    upward, which is what the wheel probes are for."""
    recon = session(tmp_path)
    screen = screen_with()

    refused = [(a.id, recon.controller.target.forbids_path(a.at, a.to))
               for a in recon.plan(screen) if a.kind == "drag"
               and not recon.worth_asking(a)]

    assert [a for a, _ in refused] == ["drag:0.500,0.500>0.500,0.750"]
    assert "Battle button" in refused[0][1]


def test_a_denylisted_candidate_is_admitted_but_never_asked_about(tmp_path):
    """Both halves matter and they pull opposite ways. Not asked, because `permitted`
    consults the denylist before it looks a verdict up, so the answer cannot change
    anything - on the measured pass 34 of 100 blocked actions were denylist refusals the
    call had already been paid to rule on. Still admitted, because that refusal and its
    written reason are how `prune_blocked` gets the finding into the report, and "the box
    did its job" is one of the more useful lines in it."""
    recon = session(tmp_path)
    asked = recording_asks(recon)
    battle = {"label": "Battle", "what": "starts a match", "at": [0.5, 0.78]}
    screen, variant = after_first_vetting(recon, [battle] + grid_elements(8))
    screen.tried.update(a.id for a in recon.ready(screen, variant)[:QUEUE_SIZE - REFILL_AT])

    recon.ask_about_escalated(screen, variant)

    offered = {a.id for a in recon.screen_actions(screen)}
    assert "click:0.500,0.780" in offered
    assert "click:0.500,0.780" not in [a for batch in asked for a in batch]
    assert recon.controller.target.forbids(0.5, 0.78), "the box is what refuses it"
    # And it did not eat one of the four slots the batch was for.
    assert len(asked[0]) == REFILL_BATCH


# --- resuming ---------------------------------------------------------------

def test_a_resumed_map_re_admits_what_the_previous_pass_paid_for(tmp_path):
    """`self.admitted` is in memory only, which is safe exactly because the verdicts are
    not: a second pass reading yesterday's `ontology.json` gets the same queue back from
    the answers already on the map, without a call and without re-deriving anything."""
    recon = session(tmp_path)
    screen = screen_with(grid_elements(19), vetted=True)
    rule(screen, ["click:0.100,0.300", "click:0.200,0.300"])
    screen.tried.add("click:0.300,0.300")

    offered = [a.id for a in recon.screen_actions(screen)]

    assert offered == ["click:0.100,0.300", "click:0.200,0.300", "click:0.300,0.300"]
    assert recon.admitted["sc01"] == set(), "nothing was admitted by a top-up"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

# --- the running commentary -------------------------------------------------

def test_the_queue_can_be_read_one_further_than_the_action_being_sent(tmp_path):
    """`pending_actions` is what lets a pass say what it is about to do *and* what follows,
    and its head has to stay exactly `next_action`. Two orderings of the same plan is how a
    pass announces one action and sends another - the failure that cannot be seen in a log,
    because the log is the thing that is wrong."""
    recon = session(tmp_path)
    screen, variant = after_first_vetting(recon, grid_elements(3))
    cleared(screen, grid_elements(3))

    upcoming = [a.id for a in recon.pending_actions(screen, variant)]

    assert upcoming[0] == recon.next_action(screen, variant).id
    assert upcoming[:3] == ["click:0.100,0.300", "click:0.200,0.300", "click:0.300,0.300"]
    # Reading ahead must not consume the frontier: the search walks this on every screen.
    assert not screen.tried and not variant.tried


def test_a_tap_is_announced_by_the_name_of_what_it_is_aimed_at(tmp_path, capsys):
    """The line a person watching a live account reads. A pair of coordinates does not tell
    them whether the next input lands on a stat panel or on a confirm button, so the element
    the point came from is named, and the one behind it is named too."""
    recon = session(tmp_path)
    screen, variant = after_first_vetting(recon, grid_elements(2))
    cleared(screen, grid_elements(2))
    queued = list(recon.pending_actions(screen, variant))

    recon.announce(screen, queued[0], queued[1:])

    line = capsys.readouterr().out
    assert "button 0" in line and "(0.100, 0.300)" in line
    assert "next" in line and "(0.200, 0.300)" in line


def test_an_action_aimed_at_no_element_is_announced_without_inventing_a_name(tmp_path):
    """Half the repertoire is blind - swipes from the middle, the border sweep - and naming
    those after whatever element is nearest would read as a measurement of intent."""
    recon = session(tmp_path)
    screen, variant = after_first_vetting(recon, grid_elements(1))
    cleared(screen, grid_elements(1))
    blind = next(a for a in recon.pending_actions(screen, variant) if a.kind == "drag")

    assert recon.aimed_at(screen, blind) == ""
    assert recon.aimed_at(screen, recon.next_action(screen, variant)) == "button 0"
