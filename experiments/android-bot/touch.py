"""A recon session restricted to what a finger can do to a phone.

`Recon` was written against desktop games, and its probe repertoire says so: it sweeps
the cursor across the window to find controls that light up, it presses the arrow keys,
and it offers enter, space and escape once a screen has been vetted. On an Android game
inside the Play Games emulator, all three are dead weight, and the first measurement of
this target proved it - a one-minute pass spent 32.9 of those seconds hover-probing 40
points, found 2 that reacted, and correctly concluded that even those were the cursor
dragging a selection rather than controls responding. The keys went the same way: the
model refused enter, space and escape on the grounds that nothing is highlighted on a
touch UI, and `key:up` moved 0 of 576 cells.

So this subclass removes them and keeps what a finger has:

- **one-finger tap** - `click`.
- **one-finger swipe** - `drag`. Promoted from a last-resort escalation to a first-class
  probe, because on a touch UI swiping is how lists, carousels and maps are operated,
  not an exotic gesture.
- **two-finger pinch** - as close as can be reached, which is the wheel. Genuine
  multi-touch cannot be injected: the emulator is booted with `--multi-touch=nil` and
  presents a mouse, and Play Games maps the wheel onto pinch-zoom. Kept last in
  priority and honestly labelled, rather than dropped, because "two fingers" was asked
  for and this is what two fingers are on this backend.

Two behaviours are added rather than removed, both of them rules a person gave:

- **Home is a tap, not a relaunch.** `Recon.recover_frontier` closes the game and starts
  it again, which is the one move that returns a desktop game to a known state. Here it
  is both impossible and wrong: there is no executable to relaunch (see `attach.py`),
  and the state lives on a server where nothing can be undone by restarting. The centre
  of the bottom pane is this game's home, so getting unstuck means tapping it.
- **Dismiss dialogs by leaving them.** Agreement is refused by the safety brief, which
  leaves a session that lands on a consent dialog with nothing it may press - the exact
  dead end that stopped the Boom Beach map. The way out of a modal is a tap outside its
  panel, so those taps are offered as candidates and are tried before home - and when one
  works, home is not tapped on top of it, because a dialog's own button lives where home
  does.

And one thing is restructured rather than added: **candidates arrive as a queue**, in
batches, instead of all at once. See `plan` and `top_up`.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import changed_cells, is_fraction, log  # noqa: E402
from recon import (Action, DRAG_DIRECTIONS, GRID_COLS, GRID_ROWS,  # noqa: E402
                   PROBE_AT, Recon, SCROLL_NOTCHES, Screen, Variant,
                   as_box, box_centre, fingerprint, point_key, probe_drag)

# The centre of the bottom navigation pane: this game's home. Measured off a
# photographed main screen, and clear of every denylist box - the Shop tab ends at
# x 0.18 and the Clan tab starts at x 0.64.
HOME = (0.50, 0.95)

# Points outside any centred panel, tried when a screen offers nothing that may be
# pressed. Edges rather than corners: a corner on a phone layout is as likely to be a
# close button as to be background, and a tap that lands on a control is not a dismissal.
AWAY = ((0.03, 0.50), (0.97, 0.50), (0.03, 0.85))

# The border sweep: a cheap answer to "nothing here responds and there is nothing left
# to aim at". Phone layouts put their navigation against the edges, so the edges are
# where an unrecognised screen is most likely to have a way out of it. Deliberately
# coarse - twelve taps, not a grid - because this is a fallback and not a search.
BORDER_INSET = 0.03
BORDER_ALONG = (0.20, 0.50, 0.80)


# The touch queue. `plan` writes down everything that could be tried on a screen, in
# priority order; the queue is the prefix of that list which has been *admitted*, meaning
# a vetting call has been asked about it and so `permitted` can answer for it. Nothing
# outside the queue is offered to `next_action`, and nothing inside it is offered without
# a verdict.
#
# The shape a person asked for: plan eight, and when half of them are used up, introduce
# four more and vet those. What makes it more than pacing is what it fixes. Candidates
# used to be offered all at once, which cannot work: the element taps are the best
# candidates on any screen and their coordinates come *out of* the vetting call, so they
# cannot be in the call that would rule on them. The measured consequence, on a 320-second
# pass, was that of 15 recorded actions **none** was aimed at an element the model located
# - `prune_blocked` retires anything with a permanent refusal, "no verdict for this
# action" is permanent, so all 19 lobby elements were retired unsent on the first step
# after they were discovered. 66 of that pass's 100 blocked actions read "never ruled on".
#
# So the queue is the fix, generalised: admission and vetting happen together, in batches,
# for as long as the screen has candidates left and the budget lasts. Sizes, not
# priorities, are the tuning knobs here - which candidate is best is decided by `plan`,
# in code, and no model is asked to rank them.
QUEUE_SIZE = 8       # candidates planned before the first move on a screen
REFILL_AT = 4        # ... topped up once this many are left ready to try
REFILL_BATCH = 4     # ... with this many more, bought with one vetting call
REFILL_CALLS = 4     # ... and at most this many top-ups per screen, ever


# Words and symbols that disqualify a described element from being tapped, whatever the
# vetting call decided about it.
#
# This exists because of a measured hole. The Shop tab is denylisted by coordinate, and a
# pass reached the shop anyway - by swiping, because a coordinate denylist forbids a
# button and not a destination. The vetting call on that screen located a
# "purchase button showing real-money price ... tapping it would spend real money" at
# (0.50, 0.66), which no denylist box covers. So the only thing standing between a live
# account and a one-tap purchase was the same model's own judgement, one layer where the
# rule a person gave asks for a floor.
#
# What makes this cheap is that it reads evidence already in hand: the vetting call
# describes each element in plain words before anything is aimed at it, and a purchase
# button is nearly always described as one. Matching those words is mechanical, so it
# cannot be reasoned around the way the safety brief's own OK-button rule was. Skipping a
# safe control by accident costs one branch of exploration - the asymmetry the brief
# states, applied to the harness rather than to the model.
MONEY_WORDS = ("€", "$", "£", "¥", "₹", "price", "purchas", "buy", " pay", "payment",
               "real money", "real-money", "checkout", "subscri", "bundle", "offer",
               "pack ", " pack", "gem", "coin", "shop", "store")


def costs_money(described: str) -> str:
    """The first money word in an element's description, or "" if there is none."""
    lowered = described.lower()
    return next((word for word in MONEY_WORDS if word in lowered), "")


def border_points() -> list[tuple[float, float]]:
    near, far = BORDER_INSET, 1.0 - BORDER_INSET
    points = [(along, near) for along in BORDER_ALONG]
    points += [(along, far) for along in BORDER_ALONG]
    points += [(near, along) for along in BORDER_ALONG]
    points += [(far, along) for along in BORDER_ALONG]
    return points


class TouchRecon(Recon):
    """`Recon` with the repertoire of a finger, offered as a queue. Rest is inherited."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Which candidates a top-up has admitted, per screen. Ids rather than actions
        # because `plan` rebuilds the actions from the map every time it is called, and
        # an id is what everything else in the harness is keyed on.
        #
        # Deliberately not written to `ontology.json`: a resumed map re-derives the same
        # thing from what it already stores. See `queue`.
        self.admitted: dict[str, set[str]] = defaultdict(set)
        # Top-ups spent per screen, capped by `REFILL_CALLS`. In memory only, like the
        # base class's `escalation_asks` it replaces: a budget is a property of a pass.
        self.refills: dict[str, int] = defaultdict(int)
        # Notes `plan` has already written, so each is written once. `plan` runs several
        # times a step - `next_action`, `prune_blocked` and the frontier search each walk
        # it - and a note per walk would bury the pass's real findings in duplicates of
        # the same handful of refusals.
        self.noted: set[str] = set()

    def note_once(self, message: str) -> None:
        """`Controller.note`, for the notes written from `plan`. See `self.noted`."""
        if message not in self.noted:
            self.noted.add(message)
            self.controller.note(message)

    def map_hover(self, screen: Screen) -> None:
        """Not done at all, and the note says so rather than leaving a silent gap.

        A hover map is the input to `screen.hotspots`, so skipping it means clicks are
        aimed only at coordinates the vetting call reported seeing controls at. On the
        measured screen that was 19 elements against 2 hotspots, so this loses nothing
        and buys back a third of the budget.
        """
        if screen.hover_probed:
            return
        # Marked probed so the step loop does not keep asking for a map; left *not*
        # inert, because inert is a measurement of a screen that ignored the cursor and
        # this screen was never asked.
        screen.hover_probed = True
        self.controller.note(f"{screen.id}: no hover map - a touch UI has no hover "
                             f"states, so clicks are aimed at vetted elements instead")

    @staticmethod
    def variant_actions() -> list[Action]:
        """No keys. A phone has no keyboard here, and escape closes the game."""
        return []

    def plan(self, screen: Screen) -> list[Action]:
        """Everything that could be tried on this screen, best candidate first.

        The plan, not the queue: this is the whole universe of moves a finger has here,
        and `screen_actions` is the prefix of it that has been admitted. Nothing is
        consumed by walking it, so it is safe to call from the frontier search.

        The order *is* the prioritisation, and it is written here in code rather than
        asked for. Ranked by how much is known about the target:

        1. **taps on elements the vetting call located** - a coordinate somebody read a
           label at, minus anything the money filter refuses.
        2. **hotspots** - empty on a touch profile, kept for a resumed desktop map.
        3. **four swipes from the middle** - aimed at no control, but on a touch UI
           swiping is how lists, carousels and maps are operated. The desktop version
           offers one and gates the other three behind evidence the screen drags at all;
           here that gate costs more than it saves, because a carousel that only moves
           horizontally reports nothing for the vertical probe and the vertical probe is
           how you find out.
        4. **three taps away from any panel** - the way out of a modal, ranked above the
           wheel because a screen this session cannot leave is worse than one it has not
           finished measuring.
        5. **two wheel probes** - the two-finger stand-in, and the weakest evidence of
           the lot: a proxy for a gesture this backend does not have.
        6. **the twelve-point border sweep** - aimed at nothing whatsoever, which is the
           point. Last, so it is reached only on a screen where the queue has run out of
           anything better, which is exactly "if you don't know what to do, try the
           borders".

        Where the seed lands is worth knowing: before the first vetting call there are no
        elements yet, so the first `QUEUE_SIZE` of this list is the four swipes, the three
        away-taps and one wheel probe - the whole blind repertoire bar one. The elements
        arrive with that call's answer and go to the front of the queue behind it.
        """
        actions: list[Action] = []
        seen: set[str] = set()

        def tap(point: tuple[float, float]) -> None:
            key = point_key(point)
            if key not in seen:
                seen.add(key)
                actions.append(Action("click", at=point))

        if screen.vetting is not None:
            for element in screen.vetting.get("elements", []):
                # The rectangle first. On a screen `locate_elements` has been over, `at` is
                # already this centre and the two agree; on one it could not reach - and on
                # every map written before boxes existed - the box is the better of the two,
                # and preferring it here means one rule for where a tap lands rather than
                # one per caller. See `Mission._element`, which prefers it for the same
                # reason.
                box = as_box(element.get("box"))
                at = box_centre(box) if box else element.get("at")
                if not is_fraction(at):
                    # Said out loud rather than skipped. `is_fraction` is a guard against
                    # a coordinate that cannot be clicked, and a silent guard turns a
                    # systematic model error into a screen that merely looks sparse:
                    # measured on this game, five of 99 located elements came back at
                    # y 1.33, which is off the bottom of a 1121x1993 window, and all five
                    # were the bottom navigation - the one row a touch UI most needs. A
                    # whole control group vanished from the plan and nothing recorded it.
                    self.note_once(f"{screen.id}: dropping "
                                   f"{element.get('label', 'an element')!r} - the vetting "
                                   f"call put it at {at}, which is not a point inside the "
                                   f"window, so there is nothing to tap")
                    continue
                described = f"{element.get('label', '')} {element.get('what', '')}"
                word = costs_money(described)
                if word:
                    # Not offered at all, rather than offered and refused: an action that
                    # never enters the candidate list cannot be cleared by a later
                    # vetting call on a different appearance of the same screen.
                    self.note_once(f"{screen.id}: not tapping "
                                   f"{element.get('label', 'an element')!r} at "
                                   f"({at[0]:.3f}, {at[1]:.3f}) - described as {word!r}, "
                                   f"and money is the one thing this bot must not touch")
                    continue
                tap((float(at[0]), float(at[1])))
        for point in screen.hotspots:      # empty unless a map was resumed from disk
            tap(point)

        actions += [probe_drag(PROBE_AT, direction) for direction in DRAG_DIRECTIONS]
        for point in AWAY:
            tap(point)
        actions += [Action("scroll", at=PROBE_AT, notches=-SCROLL_NOTCHES),
                    Action("scroll", at=PROBE_AT, notches=SCROLL_NOTCHES)]
        for point in border_points():
            tap(point)
        return actions

    def screen_actions(self, screen: Screen) -> list[Action]:
        """The admitted prefix of `plan`: the touch queue as the base class sees it.

        Three things count as admitted, and the reason is the same each time - that
        `permitted` can give an answer about them:

        - anything a vetting call has ruled on. This is what makes the queue survive a
          resume without being written to disk: the verdicts are on the map, so a second
          pass re-admits everything the first one paid for, in plan order, for free.
        - anything already tried, so a screen that has been worked through still reports
          its history to `prune_blocked` and the report rather than appearing to shrink.
        - anything a top-up has admitted this pass (`self.admitted`).

        Plus one seed: before the screen has been vetted at all, the first `QUEUE_SIZE`
        of the plan, because that is what `Recon.vet` reads to decide what its one call
        should ask about. That clause switches itself off the moment the call comes back,
        since by then those same candidates are admitted by their verdicts instead.

        The invariant everything above serves: **an admitted action with no verdict must
        be asked about in the same step it is admitted.** `prune_blocked` runs after
        `top_up` and retires "no verdict for this action" permanently, on the map, for
        every later pass too - so an action offered here and not asked about is not
        delayed, it is destroyed.
        """
        universe = self.plan(screen)
        ruled = (screen.vetting or {}).get("actions", {})
        admitted = {a.id for a in universe
                    if a.id in ruled or a.id in screen.tried}
        admitted |= self.admitted[screen.id]
        if screen.vetting is None:
            admitted |= {a.id for a in universe[:QUEUE_SIZE]}
        return [a for a in universe if a.id in admitted]

    def worth_asking(self, action: Action) -> bool:
        """Whether a verdict could ever unlock this action, i.e. it is not denylisted.

        The point is to stop paying for rulings that cannot matter. The denylist is
        checked by `permitted` *before* it looks a verdict up, so a box that covers the
        Battle button refuses a tap on it whatever the model says - and on the measured
        pass 34 of 100 blocked actions were denylist refusals the vetting call had
        already been paid to rule on, about four per screen per call. Four of them were
        taps the model itself proposed at Battle coordinates.

        Filtered here, at the point a question is asked, and deliberately *not* in `plan`
        or `screen_actions`. A denylisted action stays a candidate, gets no verdict, and
        is refused by the denylist - which is how its reason reaches `prune_blocked` and
        the report. Dropping it from the plan instead would leave the strongest safety
        layer invisible in the output, and "the box did its job" is the finding.
        """
        if action.at is None:
            return True
        why = self.controller.target.forbids(*action.at)
        if not why and action.kind == "drag" and action.to is not None:
            why = (self.controller.target.forbids(*action.to)
                   or self.controller.target.forbids_path(action.at, action.to))
        return not why

    def ready(self, screen: Screen, variant: Variant) -> list[Action]:
        """Queued actions this session may still take: untried and cleared to go.

        This is the number the top-up watches, and it is deliberately not "untried".
        A screen whose eight candidates came back with six refusals has two moves left,
        not eight, and counting the refusals would leave it looking busy while it sat
        there with nothing to do - the situation the queue exists to end.
        """
        return [a for a in self.screen_actions(screen)
                if a.id not in screen.tried and self.permitted(screen, variant, a)[0]]

    def top_up(self, screen: Screen, variant: Variant) -> None:
        """Admit the next batch of the plan and buy verdicts for it, in one call.

        Runs when the queue is down to `REFILL_AT` ready moves, up to `REFILL_CALLS`
        times per screen. Everything admitted here is asked about here - see the
        invariant in `screen_actions` - and anything the call declines to rule on is
        retired by `retire_unruled` rather than left to be offered again forever.

        A failed call takes the batch back out of the queue. That is not tidiness: left
        admitted and unruled, the very next line of `Recon.step` would retire the whole
        batch permanently for a network error.
        """
        if self.vetter is None or screen.vetting is None:
            return
        queue = self.screen_actions(screen)
        ruled = screen.vetting.get("actions", {})
        # Normally empty: `vet`'s own validator requires a verdict per candidate. Kept
        # because the invariant above has to hold for whatever reason it was broken.
        unruled = [a for a in queue if a.id not in ruled and a.id not in screen.tried]

        ready = len(self.ready(screen, variant))
        additions: list[Action] = []
        if ready <= REFILL_AT and self.refills[screen.id] < REFILL_CALLS:
            offered = {a.id for a in queue}
            budget = REFILL_BATCH
            for action in self.plan(screen):
                if action.id in offered:
                    continue
                additions.append(action)
                # Denylisted additions ride along for free - they are admitted so their
                # refusal is recorded, and cost nothing because nothing is asked about
                # them - so only the askable ones count against the batch.
                if self.worth_asking(action):
                    budget -= 1
                    if not budget:
                        break

        batch = [a for a in unruled + additions if self.worth_asking(a)]
        if not batch:
            return
        self.admitted[screen.id] |= {a.id for a in additions}
        if additions:
            self.refills[screen.id] += 1
            log(f"  {screen.id}: queue down to {ready} ready "
                f"moves, so {len(additions)} more are planned "
                f"({self.refills[screen.id]} of {REFILL_CALLS} top-ups spent) - "
                f"{len(batch)} of them need a verdict")
        if not self.ask_about(screen, variant, batch, retire_unruled=True):
            self.admitted[screen.id] -= {a.id for a in additions}
            if additions:
                self.refills[screen.id] -= 1
            self.controller.note(f"{screen.id}: the top-up's vetting call failed, so the "
                                 f"{len(additions)} new candidates are unplanned again "
                                 f"rather than retired unsent")

    def ask_about_escalated(self, screen: Screen, variant: Variant) -> None:
        """The queue's top-up, in the slot the base class reserved for exactly this.

        `Recon.step` calls this after vetting and before `prune_blocked`, because the
        escalated wheel and drag probes are the base class's one kind of candidate that
        is minted *after* the call that would have ruled on it. On a touch profile there
        are no escalated probes - all four swipes and both wheel directions are offered
        from the start - but the queue turns that exception into the normal case: every
        batch after the first is minted after a vetting call. Same hook, same reason, one
        step earlier in the argument.
        """
        self.top_up(screen, variant)

    def screen_has_frontier(self, screen: Screen) -> bool:
        """Also true while a screen has plan left and top-ups to admit it with.

        Without this the queue would quietly narrow the map. The base class asks "is any
        offered action untried", and offered now means admitted - so a screen worked down
        to an empty queue reads as finished even with fourteen located elements still
        unadmitted, and `route_to_frontier` would never travel back to spend a top-up on
        it. Bounded by `REFILL_CALLS`, so this cannot make a screen a frontier forever.
        """
        if super().screen_has_frontier(screen):
            return True
        if self.vetter is None or self.refills[screen.id] >= REFILL_CALLS:
            return False
        offered = {a.id for a in self.screen_actions(screen)}
        return any(a.id not in offered for a in self.plan(screen))

    def recover_frontier(self) -> bool:
        """Tap home instead of relaunching, and say which rung of the ladder was used.

        The base class closes the game and starts it again. With no executable that
        raises, and even if it worked it would buy nothing: a live account does not
        return to a known state by being restarted. What does return this game to a
        known screen is the bottom pane's centre.

        Away-taps come first because the reason a session is stuck is usually a modal
        it may not agree to, and home may well be underneath it.
        """
        unexplored = [s for s in self.screens.values() if self.screen_has_frontier(s)]
        if not unexplored:
            return False
        if self.actions_taken == self.actions_at_recovery:
            self.controller.note(
                f"tapping home did not reach the frontier - "
                f"{', '.join(s.id for s in unexplored)} still have untried actions but "
                f"no observed route leads back to them")
            return False
        self.actions_at_recovery = self.actions_taken

        for point in AWAY:
            if self.controller.target.forbids(*point) is None:
                self.controller.note(f"stuck; tapping away from any panel at {point} "
                                     f"before trying home")
                before = fingerprint(self.controller)
                self.controller.click(*point)
                self.controller.wait_stable()
                if self.moved_on(before):
                    # The tap outside was the dismissal, so home is not needed - and
                    # skipping it is not merely tidy. A dialog's own button sits at the
                    # bottom centre of the panel, which is where HOME is: a vetting call
                    # on the arena-info popup located OK at exactly (0.50, 0.95). Home is
                    # clicked directly, without a vetting call, so tapping it after a
                    # dismissal already worked is the one path that could press a button
                    # nothing ruled on. Stop at the rung that did the job.
                    self.controller.note("the tap away changed the screen; not tapping "
                                         "home on top of it")
                    return True
                break
        self.controller.note(f"tapping home at {HOME} to get back to the main screen")
        self.controller.click(*HOME)
        self.controller.wait_stable()
        return True

    def moved_on(self, before: bytes) -> bool:
        """Whether the screen has become a different screen since `before`.

        Scored the way the session scores everything else - `changed_cells` against the
        target's own `cell_delta`, compared to its own `screen_match` - so "different
        screen" means here what it means in the map, rather than being a second opinion
        with a threshold of its own.
        """
        moved = changed_cells(before, fingerprint(self.controller),
                              self.controller.target.cell_delta)
        return 1.0 - moved / (GRID_COLS * GRID_ROWS) < self.controller.target.screen_match
