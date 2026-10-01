"""Regression checks against the ported complex_sut mock SUT - no Anthropic
calls. Unlike token_purchase's regression tests, these run against a REAL
uvicorn subprocess rather than FastAPI's in-process TestClient: the bug here
is a genuine TOCTOU race that depends on Starlette actually dispatching sync
handlers across its thread pool under real concurrent load, and time.sleep()
genuinely releasing the GIL between the quota check and the quota write -
something an in-process test client isn't guaranteed to reproduce faithfully.

The sequential check is fully deterministic - a race is structurally
impossible when each request waits for the previous response. The
concurrent check is inherently probabilistic (it's a race, not a clean
branch), but the margin here (20 concurrent requests against a limit of 5,
each holding the vulnerable window open for 50ms) makes a false negative
exceedingly unlikely - this is the same mechanism the original experiment
used to repeatedly, reliably reproduce this exact bug across many live runs.

That margin only holds if the requests really overlap. Building an httpx.Client
is slow (0.7 to 6 s measured on a Windows dev machine, mostly SSL setup) while a
request on an existing one takes about 10 ms, so the tests build their clients
before anything is timed and release the burst through a barrier. When each
thread built its own client first, the requests spread out over seconds, the
race often didn't happen under load, and the test failed now and then (#136).
"""

import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

TEST_PORT = 8791
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
RATE_LIMIT = 5  # must match engine/adapters/complex_sut/sut.py's RATE_LIMIT


@pytest.fixture(scope="module")
def running_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "engine.adapters.complex_sut.sut:app", "--port", str(TEST_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(timeout=1.0) as probe:   # one client: building one per poll ate the deadline
            while time.monotonic() < deadline:
                try:
                    probe.get(f"{BASE_URL}/docs")
                    break
                except httpx.TransportError:
                    time.sleep(0.2)
            else:
                proc.terminate()
                pytest.fail("complex_sut test server did not start in time")
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _submit(client, base_url, client_id, payload="x"):
    response = client.post(f"{base_url}/submit", json={"client_id": client_id, "payload": payload}, timeout=30.0)
    return response.json()


def _fresh_client_id(label: str) -> str:
    # WINDOW_SECONDS is 600 - a hardcoded id would carry spent quota into any
    # later invocation within the same server session (a retry, a future
    # parametrization). A fresh uuid per call keeps each test unconditionally
    # independent of what ran before it.
    return f"regression-{label}-{uuid.uuid4()}"


def test_sequential_requests_never_exceed_the_rate_limit(running_server):
    client_id = _fresh_client_id("sequential")
    with httpx.Client() as client:
        responses = [_submit(client, running_server, client_id) for _ in range(RATE_LIMIT + 3)]
    accepted_count = sum(1 for r in responses if r["status"] == "accepted")
    assert accepted_count == RATE_LIMIT


def test_concurrent_burst_overcounts_past_the_rate_limit(running_server):
    client_id = _fresh_client_id("concurrent")
    burst_size = 20
    # One client with a connection per request, built before the burst, and a barrier
    # so all 20 are sent together and land inside the server's 50 ms window.
    start = threading.Barrier(burst_size)

    def fire(client):
        start.wait()
        return _submit(client, running_server, client_id)

    with httpx.Client(limits=httpx.Limits(max_connections=burst_size)) as client:
        with ThreadPoolExecutor(max_workers=burst_size) as pool:
            responses = list(pool.map(lambda _: fire(client), range(burst_size)))
    accepted_count = sum(1 for r in responses if r["status"] == "accepted")
    assert accepted_count > RATE_LIMIT
