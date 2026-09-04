"""The action space: every input the Driver is allowed to ask for, by name.

This file is the whole of the answer to "what stops an exploratory Driver from
poking a real account's purchase flow". The engine's other adapters let the
Driver compose a request body freely, because an HTTP SUT's blast radius is a
test database. Here it cannot: `CASTING_ACTIONS` is an enum of names, the
coordinates live in `CATALOGUE`, and there is no field anywhere in the casting
schema that carries a number a model wrote. A Driver that wants to tap
somewhere nobody vetted has no way to say so.

That is a deliberate narrowing of what the engine usually offers, and it costs
something real: the Driver cannot discover a control nobody has entered here, so
this adapter explores the *behaviour* of a known action space rather than
searching for new controls. The alternative was an LLM improvising coordinates on
an account with a coordinate guard that is known to have been walked around
once, and those are not comparable risks.

Three layers, and each one is load-bearing
------------------------------------------
1. **Named actions only** - this file. Stops an invented coordinate at the schema.
2. **The coordinate denylist** - `target.forbids` / `forbids_path`, enforced
   inside `Controller.click`, which raises rather than returns. Stops a *vetted*
   coordinate that turns out to sit on something forbidden.
3. **`preflight`** - refuses to run at all unless the denylist is actually
   loaded and actually refuses the controls it was written for. Stops the silent
   failure where `DENYLISTS.get(name, [])` returns an empty list and every layer
   above it reports success.

Layer 3 exists because layers 1 and 2 both report "allowed" for every action when
the denylist is empty, and an empty denylist is one typo in a game name away.

No drags
--------
Every action here is a tap. A drag is the one input that touches somewhere it was
not aimed at - it holds the button down along a line - and the single recorded
escape from this project's guard was a swipe that ended clear of the Shop box,
started clear of it, and reached a one-tap purchase anyway. The meta-game needs
no drags to navigate, so the class of input that produced the only known escape
is simply absent rather than guarded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """One tap the Driver may ask for.

    `at` is fractional so it survives the window being resized, which this client
    does on its own between sessions - a run measured the same window at 1121x1993
    and at 560x996 within an hour.

    `reversible` is a claim a person is making, not something measured, and it is
    written down per action so that the claim can be argued with. It gates nothing
    by itself; it is what `preflight` prints for review.
    """
    name: str
    at: tuple[float, float]
    what: str
    reversible: str


# Read off `experiments/android-bot/out/now.png`, a 393x700 capture of the main
# screen taken 2026-09-04, by locating each icon's centre and dividing. Then checked
# against a live 787x1400 window with `preview`, which found one of the five landing
# on the wrong thing - see `open_profile`. Four of five survived the check, which is
# about the hit rate that justifies looking rather than reasoning.
#
# The bottom navigation bar has five slots and only two of them are here. Shop
# (leftmost) and Clan (fourth) are both denylisted - offers and real money in one,
# messages and irrevocable card donations in the other - and Battle (centre) is
# denylisted because it joins a live match. So the reachable meta-game from the
# main screen is: the cards/deck tab, the events tab, and getting back.
CATALOGUE: tuple[Action, ...] = (
    Action(
        name="open_cards",
        at=(0.216, 0.943),
        # Deliberately hedged, and it used to say "the card-collection tab" flatly.
        # The carried recon pass sent a tap at (0.2, 0.97) - within a hair of this
        # one - and landed on a screen it named "Battle Deck", while the screen it
        # named "Collection/Card Deck" was reached from somewhere else entirely. So
        # the flat description was probably wrong, and a wrong `what` in front of the
        # Driver is worse than a vague one: it would predict a collection, get a
        # deck, and report a control that does not do what its label says - an
        # anomaly manufactured by this comment rather than found in the game.
        what="the second tab in the bottom navigation, the cards/deck one. An earlier pass "
             "tapping within a hair of this point reached a screen it called the Battle Deck; "
             "whether that is the same thing as the card collection is not established",
        reversible="yes - a screen with the same navigation bar still on it, so "
                   "return_to_main gets back",
    ),
    Action(
        name="open_events",
        at=(0.903, 0.943),
        what="the rightmost of the five bottom-navigation tabs, drawn as a sword in a "
             "laurel wreath - conventionally the events/tournaments tab, though the "
             "icon is what was observed and the name is not",
        reversible="yes - same navigation bar. Note this tab has carried timed "
                   "offers before, which is why the run aborts on any screen it "
                   "cannot identify rather than tapping onward through it",
    ),
    Action(
        name="return_to_main",
        at=(0.5, 0.943),
        what="the centre of the bottom navigation, which is the main screen's own "
             "tab - the user's stated least-trouble destination",
        reversible="n/a - this IS the way back, and it is the recovery action",
    ),
    Action(
        name="open_profile",
        # Corrected from (0.14, 0.075) after `preview` was run against the live
        # client for the first time. That point was 0.14 too high: it sat on the
        # decorative green banner above the name plaque, which is exactly the class
        # of error the preview exists for - plausible in the source, wrong on the
        # screen, and invisible to any amount of reading. (0.14, 0.215) is on the
        # name text itself, with roughly 0.028 of plaque above and below it. The
        # carried recon pass never tapped anywhere near here, so nothing measured
        # contradicted the old number either.
        at=(0.14, 0.215),
        what="the plaque at the top left carrying the player name, clan line and "
             "trophy count. What it does has not been observed: no measured pass has "
             "ever tapped it, and the guess that it opens an own-profile card is a "
             "guess about a convention, not a reading of this client",
        reversible="claimed, not measured - a panel of this kind normally has an X and "
                   "closes on an outside tap, which is what `dismiss` is for. If it "
                   "instead navigates, return_to_main is still the way back",
    ),
    Action(
        name="dismiss",
        at=(0.5, 0.30),
        what="a tap high on the board area, used to dismiss a panel by tapping "
             "outside it - the user's stated way out of an unexpected popup",
        reversible="n/a - this is a way out, not a way in. On the main screen it "
                   "lands on the arena picture and does nothing",
    ),
)

# The enum the Driver actually picks from. Derived rather than written twice, so a
# catalogue entry cannot exist that the schema will not accept, nor the reverse -
# the second of which would be a name the Driver can send and nothing can execute.
CASTING_ACTIONS: tuple[str, ...] = tuple(a.name for a in CATALOGUE)

BY_NAME: dict[str, Action] = {a.name: a for a in CATALOGUE}

# The action used to get back when a screen cannot be identified. Named here
# rather than inline so that `preflight` can prove it is in the catalogue and
# that it is itself allowed - a recovery action that the denylist refuses would
# leave a run with no way out of a screen it should not be on.
RECOVERY = "return_to_main"

# Controls that MUST be refused for the denylist to be considered loaded. Each is
# a point inside one of the six boxes in `DENYLISTS["clashroyale"]`, and the whole
# point is that these are *not* in CATALOGUE: they are probes fired at the guard
# to check it is awake. If any of them comes back allowed, the guard is not there.
GUARD_PROBES: tuple[tuple[str, tuple[float, float]], ...] = (
    ("the Battle button", (0.5, 0.78)),
    ("the Shop tab", (0.09, 0.95)),
    ("the Clan tab", (0.74, 0.95)),
    ("the gem counter", (0.86, 0.02)),
    ("the gold counter", (0.55, 0.02)),
    ("the Pass Royale banner", (0.79, 0.19)),
)


class Unsafe(RuntimeError):
    """The safety layers are not in the state a run requires. Never caught."""


def vet(target) -> list[tuple[Action, str | None]]:
    """Every catalogue action paired with the reason it is forbidden, or None.

    Returned as a list rather than filtered, because the user's rule is that the
    denylist and what it blocks are *shown* before anything clicks. A function
    that quietly dropped the refused ones would satisfy the guard and defeat the
    review.
    """
    return [(action, target.forbids(*action.at)) for action in CATALOGUE]


def preflight(target) -> str:
    """Prove the safety layers are loaded, or raise. Returns what to print.

    Fails closed on four separate things, in the order in which each would be
    most embarrassing to discover afterwards:

    1. The denylist is empty. `target.resolve` builds it with
       `DENYLISTS.get(_squash(name), [])`, so a game whose discovered name
       squashes to something other than "clashroyale" gets no denylist at all and
       every check below it reports "allowed". This is the failure that looks
       exactly like success.
    2. The guard does not refuse the controls it was written for. Catches a
       denylist that loaded but whose boxes have drifted from where the client now
       draws those controls.
    3. A catalogue action is itself denylisted. Not a safety hole - the guard
       would refuse it at the click - but it means a Driver can spend a test on an
       action that can never run, and it is more likely to mean a coordinate here
       is wrong.
    4. The recovery action is missing or refused, which would leave a run with no
       way off a screen it should not be on.
    """
    if not target.denylist:
        raise Unsafe(
            f"REFUSING to run: target {target.name!r} has an empty coordinate denylist, so "
            f"nothing is forbidden and every safety check below would report 'allowed'. "
            f"This is what a mis-squashed game name looks like - see DENYLISTS in "
            f"experiments/game-ontology/target.py."
        )

    unguarded = [what for what, at in GUARD_PROBES if target.forbids(*at) is None]
    if unguarded:
        raise Unsafe(
            f"REFUSING to run: the denylist loaded ({len(target.denylist)} boxes) but does not "
            f"refuse {', '.join(unguarded)}. Either the boxes have drifted from where this "
            f"client draws those controls, or the wrong denylist loaded. Re-measure against a "
            f"current capture before running anything live."
        )

    vetted = vet(target)
    forbidden = [(a.name, why) for a, why in vetted if why]
    if forbidden:
        raise Unsafe(
            "REFUSING to run: these catalogue actions are themselves denylisted, so the Driver "
            "could spend tests on actions that can never execute - and more likely one of their "
            "coordinates is wrong: "
            + "; ".join(f"{name} ({why})" for name, why in forbidden)
        )

    if RECOVERY not in BY_NAME:
        raise Unsafe(f"REFUSING to run: the recovery action {RECOVERY!r} is not in the catalogue.")

    lines = [
        f"Safety preflight for {target.name!r}:",
        f"  {len(target.denylist)} denylisted box(es), and the guard refuses all "
        f"{len(GUARD_PROBES)} controls probed:",
    ]
    for what, at in GUARD_PROBES:
        lines.append(f"    ({at[0]:.3f}, {at[1]:.3f}) {what}: refused - {target.forbids(*at)}")
    lines.append(f"  {len(CATALOGUE)} action(s) the Driver may choose from, all allowed:")
    for action, _ in vetted:
        lines.append(f"    {action.name:16} ({action.at[0]:.3f}, {action.at[1]:.3f}) {action.what}")
        lines.append(f"    {'':16} reversible: {action.reversible}")
    lines.append(f"  recovery action: {RECOVERY}")
    lines.append("  no drags: every action is a tap, so the guard is never asked about a path")
    return "\n".join(lines)
