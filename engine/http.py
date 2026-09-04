"""Shared HTTP call to the SUT - identical implementation existed in every
prior experiment's run_live.py - plus the two HTTP-shaped things the generic
engine needs of a SUT before a run starts: is it up, and what does one
successful call look like.

Those two used to be written out inline in `runner.py` and `loop.py`, which is
what made "the engine is SUT-agnostic" not quite true: the checkpoint loop only
ever calls `adapter.execute_test`, but a run could not *begin* against anything
that wasn't a web service. They live here now as the defaults behind
`SUTAdapter.check_sut_ready` and `.fetch_happy_day_example`, so the httpx
dependency sits in the one module named after it and an adapter for a SUT with
no URL simply supplies its own pair.
"""

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # pragma: no cover - annotations only, and adapter imports nothing back
    from engine.adapter import SUTAdapter


def http_accepted(response: dict) -> bool:
    """Did the SUT accept the request at all, in the sense engine/outcome.py means?

    Accepted is not "succeeded". A 200 saying `declined` is an accepted input that
    was answered; a 422, a 429 or a 500 is an input the SUT would not process, and
    a test inside a run of those is measuring the refusal rather than whatever it
    was cast to measure. That is the same distinction the game adapter draws between
    a tap the coordinate guard refused and a tap that landed and changed nothing.

    A missing status counts as not accepted: `call_sut_once` always supplies one, so
    its absence means the call never completed.
    """
    status = (response or {}).get("status")
    return isinstance(status, int) and 200 <= status < 400


def call_sut_once(
    base_url: str,
    path: str,
    request_body: dict,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
    method: str = "POST",
) -> dict:
    with httpx.Client(transport=transport) as client:
        response = client.request(method, base_url + path, json=request_body, timeout=timeout)
        try:
            body = response.json()
        except ValueError:
            # A non-JSON response (a crash page, an empty body, a proxy error)
            # shouldn't take down the whole run - surface it as data the Driver
            # can react to instead of an uncaught JSONDecodeError.
            body = {"error": "non-JSON response from SUT", "raw_text": response.text}
        return {"status": response.status_code, "body": body}


def default_check_sut_ready(adapter: "SUTAdapter") -> None:
    """Is the SUT up? Only TransportError counts as down.

    A 404 or a 500 from the docs path is a SUT that answered, which is all this
    needs to know - plenty of real services have no /docs, and refusing to run
    against one because a page was missing would be a readiness probe that
    fails closed on the wrong signal.
    """
    docs_url = adapter.base_url + adapter.docs_path
    try:
        httpx.get(docs_url, timeout=adapter.sut_ready_timeout)
    except httpx.TransportError:
        raise SystemExit(f"{adapter.name}'s SUT isn't running at {adapter.base_url} - start it first.")


def default_happy_day_example(adapter: "SUTAdapter") -> dict:
    """One real, successful call, fetched live rather than written down.

    Live on purpose: a hand-written example in the adapter is a claim about the
    SUT that nothing checks, and the first thing the Driver reads should not be
    a fact that may have gone stale.
    """
    request = {"method": "POST", "path": adapter.test_endpoint_path, "body": adapter.happy_day_request}
    response = call_sut_once(adapter.base_url, adapter.test_endpoint_path, adapter.happy_day_request)
    return {"request": request, "response": response}
