"""Stubbed JIRA ticket store for adapter-bootstrap context - proves the
"swap the context source without touching probe.py/generate.py" design
holds, without taking on real JIRA auth/API risk.

TODO (context-enriched-bootstrap Phase 4, not started): replace this
in-memory dict with a real JIRA API client - authenticate with an API
token, GET /rest/api/3/issue/<key>, extract the description (and
optionally comments) as api_context. Everything downstream of
fetch_ticket_context's return value already works unchanged; only this
module's internals need to change.
"""

_TICKETS = {
    "PROJ-101": {
        "summary": "Exploratory testing needed for the credits-purchase API",
        "description": (
            "This is a credits-purchase API for an app that sells in-app credits.\n\n"
            "Normal usage: a client authenticates with a valid auth token, then submits a "
            "credit-card charge (card number, expiry month/year, CVV) to buy a specific "
            "number of credits. A successful purchase returns the number of credits "
            "purchased, the amount charged, and the new credit balance.\n\n"
            "Known normal-use values: real test card numbers look like Visa/Mastercard "
            "test numbers (e.g. 4111111111111111 is a well-known Visa test number, and "
            "5555555555554444 is a well-known Mastercard test number) - these pass "
            "basic format/Luhn checks even though they're not real cards. A 3-digit CVV "
            "and a near-future expiry date (e.g. next year) are typical valid values. "
            "Purchases are usually small, realistic quantities of credits (1-100), not "
            "huge or zero/negative amounts."
        ),
    },
    "PROJ-102": {
        "summary": "Rate-limiting concerns on the burst-submission endpoint",
        "description": (
            "This API accepts a burst of concurrent submissions and enforces a per-client "
            "rate limit. Normal usage: clients submit requests at a moderate rate; the "
            "system should reject excess requests with a clear rate-limit error rather "
            "than silently dropping or corrupting data under concurrent load."
        ),
    },
}


def fetch_ticket_context(ticket_id: str) -> str:
    ticket = _TICKETS.get(ticket_id)
    if ticket is None:
        raise KeyError(f"Unknown mock ticket '{ticket_id}'. Known tickets: {', '.join(sorted(_TICKETS))}")
    return f"{ticket['summary']}\n\n{ticket['description']}"
