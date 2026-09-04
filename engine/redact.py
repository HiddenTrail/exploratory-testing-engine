"""Default history-redaction for evidence shown back to the Driver/Skeptic.
An adapter may override this via SUTAdapter.redact_history_for_model if a
domain needs to hide something more than round bookkeeping."""

import json

from engine.outcome import KEY as OUTCOME_KEY


def default_redact_history_for_model(casting_log: list[dict]) -> list[dict]:
    """No literal content needs hiding by default - this just strips
    round_reasoning/checkpoint bookkeeping so evidence stays focused on
    outcomes, not re-feeding the model its own prior reasoning verbatim.

    The outcome envelope goes too. It is a re-encoding of fields the entry already
    carries in the adapter's own words, aimed at engine/diagnostics.py rather than
    at a reader, and every adapter documents its result fields in its schema doc -
    so leaving it in would put an undocumented duplicate of each result into the
    evidence, and into every cached history segment for the rest of the run. What
    the model gets instead is the diagnostics computed FROM the envelopes, which is
    the part it cannot work out for itself.
    """
    dropped = ("round_reasoning", OUTCOME_KEY)
    redacted = [{k: v for k, v in entry.items() if k not in dropped} for entry in casting_log]
    return json.loads(json.dumps(redacted))
