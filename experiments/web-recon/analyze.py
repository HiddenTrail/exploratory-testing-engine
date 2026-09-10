"""Deterministic graph oracles over a finished ontology - the "Oracle heuristics"
half of Stage 4, and it needs no model.

Where `oracles.py` judges a single Observation (an HTTP 500, a console error),
these judge the *shape of the whole map* - the navigation anomalies the game recon
looks for, transposed to a web app:

- **dead control**: a control that, when actuated, changed nothing observable.
- **redundant controls**: two different controls on one state that lead to the same
  place - often a duplicate or a mislabel.
- **dead end**: a reachable state with no way out except back to itself.
- **blocked control**: a control the crawler could not actuate at all.

Each is an *observation*, not necessarily a defect - a "dead" control on a canvas app
may have changed only pixels the DOM can't see - so they are reported separately from
the functional findings and labelled for what they are. Pure and list-based, so they
are unit-tested against a synthetic ontology with no browser.
"""

from __future__ import annotations

from collections import defaultdict

from schema import Evidence, Ontology


def _is_gesture(t) -> bool:
    """A synthetic gesture probe (hover/wheel/zoom/drag), not a real control - its
    element_key is 'gesture:<label>'. Gestures are exploratory pokes at the viewport, so
    a gesture that moves nothing is not a 'dead control' and one that can't fire is not a
    'blocked control'; the control oracles skip them."""
    return t.action.element_key.startswith("gesture:")


def dead_controls(onto: Ontology) -> list[Evidence]:
    """Controls whose action produced no observable change (effect == 'dead')."""
    return [
        Evidence(kind="dead_control", state_id=t.source, seq=t.first_seen,
                 summary=f"{t.action.kind} {t.action.element_key} on {t.source} changed nothing observable")
        for t in onto.transitions if t.effect == "dead" and not _is_gesture(t)
    ]


def blocked_controls(onto: Ontology) -> list[Evidence]:
    """Controls the crawler could not actuate even after the full click ladder."""
    return [
        Evidence(kind="blocked_control", state_id=t.source, seq=t.first_seen,
                 summary=f"{t.action.kind} {t.action.element_key} on {t.source} could not be actuated")
        for t in onto.transitions if t.effect == "blocked" and not _is_gesture(t)
    ]


def redundant_controls(onto: Ontology) -> list[Evidence]:
    """Two or more distinct controls on one state that navigate to the same other state.

    Only real navigations count (effect 'navigate'); self-loops and non-moving effects
    are excluded, and a control reached more than once is not itself redundancy."""
    by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t in onto.transitions:
        if t.effect == "navigate" and t.dest != t.source:
            by_pair[(t.source, t.dest)].add(t.action.element_key)
    out = []
    for (source, dest), controls in by_pair.items():
        if len(controls) > 1:
            out.append(Evidence(
                kind="redundant_controls", state_id=source,
                summary=f"{len(controls)} controls on {source} all lead to {dest}: "
                        f"{', '.join(sorted(controls))}"))
    return out


def dead_ends(onto: Ontology) -> list[Evidence]:
    """States the crawl *explored* that offer no way onward - no navigation to another
    state and no off-site exit.

    Only states the crawl actually acted on (a recorded outgoing transition) are judged:
    a state whose controls were never tried (a budget-limited crawl) is not a dead end,
    just unexplored, so it is excluded to avoid a false positive. An off-site ('external')
    navigation counts as a way onward. Skipped entirely for a one-state app, where "no
    exit" is the shape of the app, not a finding."""
    if len(onto.states) <= 1:
        return []
    acted = {t.source for t in onto.transitions}  # states we actually exercised
    has_exit = {
        t.source for t in onto.transitions
        if (t.effect == "navigate" and t.dest != t.source) or t.effect == "external"
    }
    return [
        Evidence(kind="dead_end", state_id=s.id,
                 summary=f"{s.id} was explored but has no navigation onward - a dead end")
        for s in onto.states if s.id in acted and s.id not in has_exit
    ]


GRAPH_ORACLES = (dead_controls, blocked_controls, redundant_controls, dead_ends)


def analyze(onto: Ontology) -> list[Evidence]:
    """Every graph oracle, flattened - the structural observations for one ontology."""
    out: list[Evidence] = []
    for oracle in GRAPH_ORACLES:
        out.extend(oracle(onto))
    return out
