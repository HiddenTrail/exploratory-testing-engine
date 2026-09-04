"""The typed outcome envelope: the small vocabulary the engine may reason over.

Why this exists
---------------
Adapters already knew everything in here. They just reported it as *prose* -
`"recovered to unknown-5 - NOT the main screen, so the next test starts somewhere
nobody chose"` is a complete and accurate statement of a reset failure that no
generic code can read. Good for the Driver, useless for the engine, and the
consequence was measurable: a live run continued for two more checkpoints after it
had lost the ability to return to its own baseline, because the only thing that
knew was a sentence in a string field.

So this is the seam. An adapter fills a handful of typed fields; `engine/diagnostics.py`
does arithmetic over them. Nothing generic ever interprets a *value* - only compares
tokens for equality and counts them - which is what keeps the abstraction from
quietly acquiring domain knowledge.

Three rules that make it honest rather than merely typed
-------------------------------------------------------
1. **`UNKNOWN` is a real answer and is never counted as `NONE`.** An adapter that
   cannot tell whether anything changed must say so. Folding "I could not measure
   it" into "nothing happened" is how a detector manufactures a finding out of a
   blind spot - the exact fails-as-success shape this project keeps meeting.
2. **An empty state token means unobserved, not "one state".** `token_purchase`
   genuinely cannot see the SUT's credit balance, so it reports `""` and every
   state-based detector skips it. A default of `"default"` would instead make every
   stateless SUT look like a system with one enormous state.
3. **`accepted is None` is expected and common.** For a pixel SUT, "the tap was
   swallowed by a modal" and "the tap hit a dead area" are indistinguishable
   without a new observable, so the honest answer is `None`. The detectors that
   need only `effect` and `state_before` still work; the one that needs `accepted`
   reports nothing rather than guessing.

The envelope is optional. An adapter that supplies none gets a run that says its
diagnostics were unavailable, which is different from a run that says it found
nothing wrong.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# The reserved key `execute_test` results carry this under. One place, so an
# adapter and the engine cannot disagree about the spelling.
KEY = "outcome"

# How much observably changed. Deliberately the same three-value taxonomy the
# game-ontology recon settled on after several measured sessions, because the
# distinction it draws is the one that matters here: `NONE` and `VARIANT` are both
# "still the same place", but only `NONE` means the input demonstrably did nothing.
# Collapsing them - which is what a bare "same state" boolean does - is what let a
# live run read five taps into a modal dialog as five ordinary no-ops.
NONE = "none"              # nothing observable changed at all
VARIANT = "variant"        # same state, but something in it moved
TRANSITION = "transition"  # a different state
UNKNOWN = "unknown"        # the adapter cannot tell
EFFECTS = (NONE, VARIANT, TRANSITION, UNKNOWN)


@dataclass(frozen=True)
class Outcome:
    """One executed test, in the terms the engine can reason about.

    Every field defaults to the least-committed value, so an adapter can fill in
    only what it actually measures and the rest degrades to "not observed" rather
    than to a confident wrong answer.
    """

    # The adapter's own name for *what was done*, used only for equality. Two tests
    # sharing an action_id are "the same action tried twice"; that is the whole
    # contract. A SUT whose every test is a distinct request body (token_purchase)
    # honestly has near-unique ids, and the detectors that group by action then find
    # nothing - which is correct, because such a SUT has no action space to collapse.
    action_id: str = ""

    effect: str = UNKNOWN
    accepted: bool | None = None

    # Opaque state tokens. The engine compares them and never parses them; `""`
    # means the adapter cannot observe the SUT's state.
    state_before: str = ""
    state_after: str = ""

    # Whether the adapter tried to return the SUT to its baseline after this test,
    # and whether that worked. `reset_ok is None` means it was not attempted.
    reset_attempted: bool = False
    reset_ok: bool | None = None

    latency: float | None = None

    # Whether this observation matched whatever prior the adapter was given - a
    # carried fingerprint, a discovered OpenAPI schema, an oracle claim. `None`
    # where the adapter has no prior to match against. A run whose prior matched
    # nothing is running blind in a way its own report should say out loud.
    matched_prior: bool | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def attach(result: dict, outcome: Outcome) -> dict:
    """Put an envelope on a result dict, returning the same dict for chaining."""
    result[KEY] = outcome.as_dict()
    return result


def read(result: dict) -> dict | None:
    """The envelope on one result, or None if the adapter did not supply one."""
    envelope = (result or {}).get(KEY)
    return envelope if isinstance(envelope, dict) else None


def rows(casting_log: list[dict]) -> list[dict]:
    """Every envelope in a casting log, each tagged with its test number.

    Rows without an envelope are dropped rather than defaulted, which is what lets
    `diagnostics` distinguish "no adapter support" from "nothing detected".
    """
    found = []
    for entry in casting_log or []:
        envelope = read(entry)
        if envelope is None:
            continue
        found.append({
            **envelope,
            "test_number": entry.get("test_number"),
            "checkpoint": entry.get("checkpoint"),
        })
    return found


def validate_outcome(data) -> list[str]:
    """Errors in an envelope, for an adapter's own tests to assert against.

    Not called by the loop: a malformed envelope should fail an adapter's test
    suite, not a live run halfway through, and every detector already tolerates
    missing keys by skipping the row.
    """
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]
    errors = []
    if data.get("effect") not in EFFECTS:
        errors.append(f"'effect' must be one of {', '.join(EFFECTS)} (got {data.get('effect')!r})")
    for key in ("action_id", "state_before", "state_after"):
        if not isinstance(data.get(key, ""), str):
            errors.append(f"'{key}' must be a string ('' where unobserved)")
    for key in ("accepted", "reset_ok", "matched_prior"):
        if data.get(key) is not None and not isinstance(data.get(key), bool):
            errors.append(f"'{key}' must be true, false, or null")
    if not isinstance(data.get("reset_attempted", False), bool):
        errors.append("'reset_attempted' must be a boolean")
    if data.get("latency") is not None and not isinstance(data.get("latency"), (int, float)):
        errors.append("'latency' must be a number or null")
    if data.get("reset_ok") is not None and not data.get("reset_attempted"):
        errors.append("'reset_ok' is set but 'reset_attempted' is false")
    return errors
