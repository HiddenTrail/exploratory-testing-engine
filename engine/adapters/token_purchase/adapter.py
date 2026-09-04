"""SUTAdapter for the token-purchase mock: a credit-purchase API backed by a
mock payment processor. Ported from experiments/token-purchase-poc/run_live.py
and report.py - the genuinely per-SUT parts (test-proposal schema, casting
prompt, execute_test, onboarding data, report rendering for one test entry
and the onboarding section).
"""

import json
from pathlib import Path

from engine import outcome
from engine.adapter import SUTAdapter
from engine.http import call_sut_once, http_accepted
from engine.ontology.oracle_creator import build_ranked_ideas
from engine.report import badge, bool_badge, esc, inline_markdown, render_json_block
from engine.util import unwrap_accidental_json_body

BASE_URL = "http://127.0.0.1:8000"
TEST_ENDPOINT_PATH = "/purchase"

KNOWN_DECLINE_REASONS = [
    "invalid_auth_token",
    "card_not_authorized",
    "invalid_card_number",
    "expiry_mismatch",
    "expired_card",
    "invalid_cvv",
    "invalid_credit_count",
    "insufficient_funds",
]

# What a real tester reading published API docs would already know going in -
# structural facts and documented error codes, not anything about a bug.
API_SCHEMA_DOC = f"""POST /purchase

Request body:
  auth_token: string - identifies the calling user.
  card_number: string - the card to charge.
  expiry_month: integer (1-12)
  expiry_year: integer
  cvv: string
  credit_count: integer - how many credits to purchase.

Response body:
  status: string - "approved" or "declined".
  decline_reason: string or null - present only if declined. One of:
    {", ".join(KNOWN_DECLINE_REASONS)}
  credits_purchased: integer - 0 if declined.
  total_charged: number - dollars charged, 0 if declined.
  new_credit_balance: integer or null - the user's current total credit balance
    after this transaction (whether or not it was approved). null only if
    auth_token itself couldn't be resolved to any account.
  transaction_id: string or null - present only if approved.

Pricing is tiered by bulk quantity - buying more credits in one transaction may
reduce the price per credit for the whole order. The exact tiers are not
published; buy at different quantities to observe pricing behavior.

Each card has a spending capacity that is never revealed directly in any
response (by design - a real payment gateway doesn't reveal a card's exact
available balance to the merchant either). Capacity has to be inferred by
testing purchases until declines start happening."""

# 3 real, fully-disclosed accounts - not a partial guessing game. What's genuinely
# unknown is each card's spending capacity and whether the implementation's many
# validation rules actually behave as documented.
KNOWN_ACCOUNTS = [
    {"auth_token": "tok_live_9f2c8a41", "card_number": "4111104332181963", "expiry_month": 11, "expiry_year": 2027, "cvv": "482"},
    {"auth_token": "tok_live_7d51e6b0", "card_number": "4111001338908383", "expiry_month": 3, "expiry_year": 2028, "cvv": "915"},
    {"auth_token": "tok_live_c3a9f204", "card_number": "4111637940265421", "expiry_month": 8, "expiry_year": 2028, "cvv": "067"},
]

HAPPY_DAY_REQUEST = {**KNOWN_ACCOUNTS[0], "credit_count": 10}

# A one-time snapshot from the Oracle Agent PoC (experiments/oracle-agent-poc),
# a heuristic pass over this SUT's spec.md - not regenerated per run. Merged
# into onboarding_extra so the Driver sees it as ordinary evidence, same as
# known_accounts.
ORACLE_LIBRARY = json.loads((Path(__file__).parent / "oracle_library.json").read_text(encoding="utf-8"))

# Layer 4 of the ontology stack (engine/ontology): the same domain claims above,
# plus generic heuristic probes, re-scored and ranked using yesterday's context
# (test results, jira). Top slice only - this is what the Driver actually sees;
# ORACLE_LIBRARY stays available above for the report's full-library exhibit.
ORACLE_RANKED_TOP_N = 15
ORACLE_RANKED = build_ranked_ideas("token_purchase")["ranked_ideas"][:ORACLE_RANKED_TOP_N]


def execute_test(test: dict, test_number: int) -> dict:
    request_body = {
        "auth_token": unwrap_accidental_json_body(test["auth_token"]),
        "card_number": unwrap_accidental_json_body(test["card_number"]),
        "expiry_month": test["expiry_month"],
        "expiry_year": test["expiry_year"],
        "cvv": unwrap_accidental_json_body(test["cvv"]),
        "credit_count": test["credit_count"],
    }
    request = {"method": "POST", "path": TEST_ENDPOINT_PATH, "body": request_body}

    response = call_sut_once(BASE_URL, TEST_ENDPOINT_PATH, request_body)
    body = response["body"]
    actual_status = body.get("status")
    actual_decline_reason = body.get("decline_reason")

    predicted_status = test["predicted_status"]
    predicted_decline_reason = test.get("predicted_decline_reason") or None
    prediction_matched = (
        actual_status == predicted_status
        and (predicted_status != "declined" or actual_decline_reason == predicted_decline_reason)
    )

    return outcome.attach({
        "test_number": test_number,
        "request": request,
        "response": response,
        "predicted_outcome": test["predicted_outcome"],
        "predicted_status": predicted_status,
        "predicted_decline_reason": predicted_decline_reason,
        "actual_status": actual_status,
        "actual_decline_reason": actual_decline_reason,
        "prediction_matched": prediction_matched,
    }, _outcome_for(response, actual_status))


def _outcome_for(response: dict, actual_status: str | None) -> outcome.Outcome:
    """This SUT in the engine's typed outcome terms, and mostly what it CANNOT say.

    The honest envelope here is largely empty, and that is the useful part: it
    demonstrates that a detector which only fires when an adapter overstates what it
    measured would find nothing here.

    - `state_before`/`state_after` are empty because they genuinely are unobservable.
      The card's credit balance is the SUT's state and this interface never reports
      it; the only way to know it changed is to infer it from the status. A token
      like `"default"` would be worse than nothing - it would make a SUT with an
      invisible balance look like a system with exactly one state, and every
      state-based detector would then reason over a fiction.
    - `effect` uses the one state change this endpoint's contract does assert: an
      approved purchase consumes credits, a decline consumes nothing. So approved is
      a TRANSITION and declined is NONE - and NONE here is the correct answer to the
      test rather than a symptom, which is exactly why the detector that reads NONE
      also requires an observable state before it will say anything.
    - `accepted` is about processing, not outcome: a 200 saying `declined` was
      accepted and answered. See engine.http.http_accepted.
    - `action_id` is the endpoint, because that is what was invoked. The varying part
      is the request body, and every test's body differs, so an id per body would
      make every action unique and mean nothing.
    """
    accepted = http_accepted(response)
    if not accepted or actual_status not in ("approved", "declined"):
        effect = outcome.UNKNOWN
    else:
        effect = outcome.TRANSITION if actual_status == "approved" else outcome.NONE
    return outcome.Outcome(
        action_id=f"POST {TEST_ENDPOINT_PATH}",
        effect=effect,
        accepted=accepted,
    )


def describe_test_for_log(test: dict) -> str:
    return f"auth_token={test['auth_token']!r} card={test['card_number']!r} credit_count={test['credit_count']}"


def describe_result_for_log(result: dict) -> str:
    status = result["actual_status"]
    reason = result["actual_decline_reason"]
    return status + (f" ({reason})" if reason else "")


CASTING_TOOL = {
    "name": "submit_casting_round",
    "description": "Propose a batch of tests against the live /purchase endpoint.",
    "input_schema": {
        "type": "object",
        "properties": {
            "give_up": {
                "type": "boolean",
                "description": "Set true only if you have no more good ideas worth proposing this round.",
            },
            "reasoning": {
                "type": "string",
                "description": "Your reasoning for this round's batch, per the system prompt's instructions.",
            },
            "candidate_tests": {
                "type": "array",
                "description": (
                    "See the system prompt for how many tests to propose this round. Each is EITHER tied "
                    "to a specific candidate hypothesis (set linked_hypothesis to that theory, stated in "
                    "full) OR a pure edge-case/negative-case probe not tied to any theory (set "
                    "linked_hypothesis to an empty string). Mix both kinds in the same list."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "linked_hypothesis": {"type": "string"},
                        "oracle_claim_id": {
                            "type": "string",
                            "description": (
                                "If this test is meant to test one of the ranked ideas from the "
                                "'Prioritized oracle' list in your evidence, copy its id exactly as shown "
                                "there (e.g. 'claim:data:03' or 'heuristic:goldilocks'). Otherwise - a pure "
                                "edge-case probe, or a hypothesis you came up with yourself that isn't on "
                                "that list - leave this an empty string, even if linked_hypothesis is set."
                            ),
                        },
                        "auth_token": {"type": "string"},
                        "card_number": {"type": "string"},
                        "expiry_month": {"type": "integer"},
                        "expiry_year": {"type": "integer"},
                        "cvv": {"type": "string"},
                        "credit_count": {"type": "integer"},
                        "predicted_outcome": {"type": "string", "description": "What you predict will happen and why."},
                        "predicted_status": {"type": "string", "enum": ["approved", "declined"]},
                        "predicted_decline_reason": {
                            "type": "string",
                            "description": "Required (one of the documented decline_reason values) if predicted_status is 'declined'. Empty string if predicting 'approved'.",
                        },
                    },
                    "required": [
                        "linked_hypothesis", "oracle_claim_id", "auth_token", "card_number", "expiry_month",
                        "expiry_year", "cvv", "credit_count", "predicted_outcome", "predicted_status",
                        "predicted_decline_reason",
                    ],
                },
            },
        },
        "required": ["give_up", "reasoning", "candidate_tests"],
    },
}


def casting_system_prompt(test_budget: int, is_first_round: bool) -> str:
    if is_first_round:
        context_instruction = """Nothing is currently flagged as anomalous, and you do not know whether any
bug exists at all - this implementation was not deliberately seeded with a bug, so there may genuinely be
none to find. Before proposing anything, think about context: what can you reasonably assume about this
kind of system (a credit-purchase API backed by a mock payment processor) given its apparent purpose, and
what bug classes are commonly seen in this category of implementation (e.g. authorization checks that can
be bypassed by mixing credentials across accounts, off-by-one errors at pricing tier or expiry boundaries,
inconsistent validation ordering that leaks information before authorization is confirmed, rounding errors
in tiered pricing, capacity/balance accounting errors)? State this reasoning explicitly."""
    else:
        context_instruction = """You now have real test results, and prior_checkpoint_feedback holds the
previous checkpoint's hypothesis plus Skeptic's cold critique of it. If that hypothesis claimed any
anomalies that Skeptic found weak, prioritize tests that could confirm OR refute those SPECIFIC claims.
If Skeptic flagged the absence of any anomaly claim as premature given what's been tested, prioritize
whatever category it pointed at. Briefly state what you've actually learned so far and how that's
changing your approach this round."""

    return f"""You are testing a live API endpoint (POST /purchase, a credit-purchase API backed by a
mock payment processor) to look for bugs or unexpected behavior. You've been shown the API's schema
documentation (including the documented decline_reason values), 3 real fully-disclosed accounts
(auth_token, card_number, expiry, cvv - use these directly, nothing about them needs to be guessed),
and one real executed "happy day" purchase.

{context_instruction}

In one round, propose a BATCH of tests - up to {test_budget} total:
1. Candidate hypotheses: think of a few specific, falsifiable theories about possible bugs - e.g.
   mixing one account's auth_token with another's card_number (authorization), boundary values around
   the pricing tiers, malformed or boundary expiry/cvv values, credit_count edge cases, or attempting
   to push a card past its (unknown) capacity to see how declines behave. For each, propose 1-2
   concrete test ideas - a full request plus a prediction of what would happen if that specific theory
   were true. Set linked_hypothesis to the full theory text for these.
2. Pure edge-case probes: also propose tests not tied to any specific theory - general negative-case/
   boundary testing instinct. For these, predict "approved" or the most likely "declined" outcome as
   your null hypothesis and set linked_hypothesis to an empty string.

All of these tests will be executed for real, together, before you see any results - they don't
depend on each other's outcomes, so make each one a genuinely independent check rather than a
refinement of another test in the same batch. You'll see every real result before being asked for
another round, and can refine across rounds then.

If you believe you've explored reasonably and have no more good ideas worth proposing, set give_up
to true rather than proposing something arbitrary just to have something to submit.

Prioritize breadth over depth. Before proposing a test, check tests_tried_in_earlier_rounds: if the
same underlying question has already been asked multiple times with consistent results, treat it as
settled - don't ask a third or fourth variant of it unless something specific suggests the picture has
actually changed.

Call submit_casting_round with your answer."""


def validate_casting_response(data) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return [f"expected an object, got {type(data).__name__}"]

    for key in ("give_up", "reasoning", "candidate_tests"):
        if key not in data:
            errors.append(f"missing required field '{key}'")

    if not isinstance(data.get("give_up"), bool):
        errors.append("'give_up' must be a boolean")

    tests = data.get("candidate_tests")
    if not isinstance(tests, list):
        errors.append("'candidate_tests' must be a list")
    elif not data.get("give_up") and not tests:
        errors.append("'candidate_tests' must be non-empty unless give_up is true")
    else:
        required_test_keys = (
            "linked_hypothesis", "oracle_claim_id", "auth_token", "card_number", "expiry_month", "expiry_year",
            "cvv", "credit_count", "predicted_outcome", "predicted_status", "predicted_decline_reason",
        )
        for i, test in enumerate(tests or []):
            if not isinstance(test, dict):
                errors.append(f"candidate_tests[{i}] must be an object")
                continue
            for key in required_test_keys:
                if key not in test:
                    errors.append(f"candidate_tests[{i}] missing '{key}'")
            # execute_test() passes auth_token/card_number/cvv straight into
            # unwrap_accidental_json_body(), which calls .strip() on them - a
            # non-string value here (e.g. a stray number or null) would crash
            # the run rather than just producing a bad, but harmless, test.
            for key in ("linked_hypothesis", "oracle_claim_id", "auth_token", "card_number", "cvv", "predicted_outcome"):
                if key in test and not isinstance(test[key], str):
                    errors.append(f"candidate_tests[{i}].{key} must be a string")
            for key in ("expiry_month", "expiry_year", "credit_count"):
                if key in test and not isinstance(test[key], int):
                    errors.append(f"candidate_tests[{i}].{key} must be an integer")
            if test.get("predicted_status") not in ("approved", "declined"):
                errors.append(f"candidate_tests[{i}].predicted_status must be 'approved' or 'declined'")
            if test.get("predicted_status") == "declined" and test.get("predicted_decline_reason") not in KNOWN_DECLINE_REASONS:
                errors.append(f"candidate_tests[{i}].predicted_decline_reason must be one of {KNOWN_DECLINE_REASONS}")

    return errors


def _status_badge(status) -> str:
    if status == "approved":
        return badge("approved", "good")
    if status == "declined":
        return badge("declined", "warn")
    return badge(status or "unknown", "warn")


def render_test_entry(entry) -> str:
    if not entry:
        return ""
    request = entry.get("request", {})
    body = request.get("body", {})

    linked = entry.get("linked_hypothesis")
    linked_html = f"<strong>Hypothesis:</strong> {esc(linked)}" if linked else (
        '<span class="probe-label">Edge-case probe</span> (no linked hypothesis)'
    )
    test_number = entry.get("test_number")
    number_html = f'<span class="test-number">Test #{esc(test_number)}</span>' if test_number is not None else ""

    response_body = entry.get("response", {}).get("body", {})
    predicted_status = entry.get("predicted_status")
    predicted_decline_reason = entry.get("predicted_decline_reason")
    predicted_str = predicted_status if predicted_status == "approved" else f"declined ({predicted_decline_reason})"
    actual_status = entry.get("actual_status")
    actual_decline_reason = entry.get("actual_decline_reason")
    actual_str = actual_status if actual_status == "approved" else f"declined ({actual_decline_reason})"
    matched = entry.get("prediction_matched")

    return f"""
    <article class="test">
      <div class="test-hypothesis">{number_html}{linked_html}</div>
      {render_json_block(body)}
      <div class="test-predicted">Predicted: {inline_markdown(entry.get('predicted_outcome'))}
        {_status_badge(predicted_status)} <span class="prose-muted">{esc(predicted_str)}</span></div>
      <div class="test-outcome">
        Actual: {_status_badge(actual_status)} <span class="prose-muted">{esc(actual_str)}</span>
        <span class="sep">&middot;</span> prediction {bool_badge(matched, 'matched', 'missed')}
      </div>
      <div class="test-outcome prose-muted">
        credits_purchased <span class="num">{esc(response_body.get('credits_purchased'))}</span>
        &middot; total_charged <span class="num">{esc(response_body.get('total_charged'))}</span>
        &middot; new_credit_balance <span class="num">{esc(response_body.get('new_credit_balance'))}</span>
      </div>
    </article>
    """


def _render_oracle_library(oracle_library: dict | None) -> str:
    if not oracle_library:
        return ""

    modeled_html = ""
    for key, entry in oracle_library.get("modeled", {}).items():
        vectors_html = "".join(
            f"""<li><strong>{esc(v['claim'])}</strong><div class="prose-muted">{inline_markdown(v['rationale'])}</div></li>"""
            for v in entry.get("vectors", [])
        )
        modeled_html += f"""
        <div class="oracle-heuristic">
          <h4>{esc(key)} {bool_badge(entry.get('applies'), 'applies', 'does not apply')}</h4>
          <p class="prose-muted">{inline_markdown(entry.get('reasoning', ''))}</p>
          <ul class="vector-list">{vectors_html}</ul>
        </div>
        """

    not_modeled = oracle_library.get("not_modeled", {})
    not_modeled_html = "".join(f"<li>{esc(dim)}</li>" for dim in not_modeled)

    return f"""
    <div class="exhibit">
      <h3>Oracle library (full, unranked)</h3>
      <p class="prose-muted">A one-time heuristic pass over this SUT's spec, produced by the
        Oracle Agent PoC - not testing, just context handed to the Driver alongside the schema
        and known accounts.</p>
      {modeled_html}
      <p class="eyebrow">Not modeled in this pass</p>
      <ul class="prose-muted">{not_modeled_html}</ul>
    </div>
    """


def _render_oracle_ranked(ranked_ideas: list[dict]) -> str:
    if not ranked_ideas:
        return ""
    rows = "".join(
        f"""<li><strong>#{idea['rank']} [{esc(idea['id'])}] ({idea['tier']}, score {idea['score']:.1f}, {idea['status']})</strong>
            {esc(idea['claim'])}<div class="prose-muted">{inline_markdown(idea['rationale'])}</div></li>"""
        for idea in ranked_ideas
    )
    return f"""
    <div class="exhibit">
      <h3>Prioritized oracle (top {len(ranked_ideas)})</h3>
      <p class="prose-muted">Layer 4 of the ontology stack (engine/ontology) - domain claims and
        generic heuristic probes, re-ranked by what context/test-history says about each one.
        Test these first.</p>
      <ul class="vector-list">{rows}</ul>
    </div>
    """


def render_onboarding_section(api_schema, onboarding_extra, happy_day_example) -> str:
    known_accounts = onboarding_extra.get("known_accounts", [])
    happy_request = (happy_day_example or {}).get("request", {})
    happy_response = (happy_day_example or {}).get("response", {})
    accounts_html = "".join(f"<li>{render_json_block(a)}</li>" for a in known_accounts)
    return f"""
    <div class="exhibit">
      <h3>API schema</h3>
      <pre class="schema-doc">{esc(api_schema)}</pre>
    </div>
    <div class="exhibit">
      <h3>Known accounts ({len(known_accounts)})</h3>
      <p class="prose-muted">Fully disclosed - nothing about these needs to be guessed.</p>
      <ul class="account-list">{accounts_html}</ul>
    </div>
    <div class="exhibit">
      <h3>Happy-day example</h3>
      <p class="eyebrow">Request</p>
      {render_json_block(happy_request.get('body', {}))}
      <p class="eyebrow">Response</p>
      {render_json_block(happy_response.get('body', {}))}
    </div>
    {_render_oracle_ranked(onboarding_extra.get('oracle_ranked'))}
    {_render_oracle_library(onboarding_extra.get('oracle_library'))}
    """


ADAPTER = SUTAdapter(
    name="token_purchase",
    display_name="Token-Purchase",
    base_url=BASE_URL,
    test_endpoint_path=TEST_ENDPOINT_PATH,
    api_schema_doc=API_SCHEMA_DOC,
    onboarding_extra={"known_accounts": KNOWN_ACCOUNTS, "oracle_library": ORACLE_LIBRARY, "oracle_ranked": ORACLE_RANKED},
    happy_day_request=HAPPY_DAY_REQUEST,
    casting_tool_schema=CASTING_TOOL,
    casting_system_prompt=casting_system_prompt,
    validate_casting_response=validate_casting_response,
    execute_test=execute_test,
    describe_test_for_log=describe_test_for_log,
    describe_result_for_log=describe_result_for_log,
    render_test_entry=render_test_entry,
    render_onboarding_section=render_onboarding_section,
    default_max_checkpoints=2,
    default_first_round_test_budget=5,
    default_test_budget=4,
)
