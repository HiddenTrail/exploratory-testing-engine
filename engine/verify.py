"""Replay a bug's evidence before it's reported (issue #177).

A false positive costs more trust than three missed bugs. So before a bug gets a
written report, the engine runs every test it cites again, exactly as the Driver
cast it, and asks the adapter whether each one came out the same. A bug whose tests
all reproduce stays a bug. One that doesn't, or can't be replayed, is lowered to an
anomaly with the reason, the same way lower_unsupported_bugs lowers a bug that names
no violated fact. No model call is made: the replays and the comparison are code.

Only the adapter knows what "came out the same" means for its SUT (web_gui compares
the screen reached and its trusted signals; a rate-limited API's replay hits a quota
the first run already used), so replay is opt-in through SUTAdapter.compare_replay.
An adapter without it keeps its bugs, marked as not replayed, so a reader can tell
"reproduced" from "never tried".

Found in the #160 milestone run: a bug the Skeptic corroborated (/profile returns 500)
came from an expired saved session. Replaying with that same session reproduced it
every time, which is why the adapter's before_replay hook checks the session is
still good first: a replay is only worth something from a session the server accepts.
"""

from __future__ import annotations

NOT_AVAILABLE = "not available"   # the adapter doesn't support replay
REPRODUCED = "reproduced"
NOT_REPRODUCED = "not reproduced"
UNVERIFIABLE = "couldn't replay"


def _lower(bug: dict, reason: str) -> None:
    bug["driver_kind"] = bug["kind"]
    bug["kind"] = "anomaly"
    bug["lowered_because"] = reason


def replay_bugs(adapter, observations: list[dict], casting_log: list[dict], test_counter) -> tuple[list, list]:
    """Replay the tests every bug in `observations` cites, and lower each bug whose
    tests don't all come out the same. Mutates the observations (each bug gets a
    'replay' verdict) and returns (one record per bug, the replays' own results).
    Replays take the next test numbers, so they never collide with the run's."""
    bugs = [o for o in observations if o["kind"] == "bug"]
    if not bugs:
        return [], []
    if adapter.compare_replay is None:
        for bug in bugs:
            bug["replay"] = NOT_AVAILABLE
        return [{"observation_id": b["id"], "verdict": NOT_AVAILABLE, "tests": []} for b in bugs], []

    blocker = adapter.before_replay() if adapter.before_replay else None
    by_number = {e.get("test_number"): e for e in casting_log}
    records, replay_log = [], []
    for bug in bugs:
        record = {"observation_id": bug["id"], "tests": []}
        cited = [by_number.get(n) for n in bug["tests"]]
        if blocker:
            record["verdict"], record["detail"] = UNVERIFIABLE, blocker
        elif not cited or any(e is None or "cast_test" not in e or e.get("skipped") for e in cited):
            record["verdict"] = UNVERIFIABLE
            record["detail"] = "it cites a test that wasn't run, or wasn't kept as cast"
        else:
            for original in cited:
                number = next(test_counter)
                try:
                    replayed = adapter.execute_test(original["cast_test"], number)
                except Exception as e:   # a failed replay is a missing check, not a failed run
                    record["tests"].append({"test": original["test_number"], "replay": number, "same": None,
                                            "detail": f"the replay failed ({type(e).__name__}: {e})"})
                    continue
                replay_log.append({"replay_of": original["test_number"], "for": bug["id"], **replayed})
                same = adapter.compare_replay(original, replayed)
                record["tests"].append({"test": original["test_number"], "replay": number, **same})
            # A cited test whose original run showed nothing (it never reached its state,
            # say) is evidence of nothing, so it can't make or break the replay. Every
            # other cited test has to come out the same, and there has to be one.
            counted = [t for t in record["tests"] if t.get("original_ran") is not False]
            if counted and all(t["same"] is True for t in counted):
                record["verdict"] = REPRODUCED
            elif any(t["same"] is False for t in counted):
                record["verdict"] = NOT_REPRODUCED
            else:
                record["verdict"] = UNVERIFIABLE
            record["detail"] = "; ".join(f"test {t['test']} as #{t['replay']}: {t['detail']}"
                                         for t in counted if t["same"] is not True) or (
                "none of its tests showed anything in the first place" if not counted else "")
        bug["replay"] = record["verdict"]
        if record["verdict"] == NOT_REPRODUCED:
            _lower(bug, f"its tests didn't come out the same on a fresh replay ({record['detail']})")
        elif record["verdict"] == UNVERIFIABLE:
            _lower(bug, f"it couldn't be replayed ({record['detail']})")
        records.append(record)
    return records, replay_log
