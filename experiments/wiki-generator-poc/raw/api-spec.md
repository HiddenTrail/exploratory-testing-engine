# token_purchase — published API spec

<!-- Transcribed verbatim from API_SCHEMA_DOC and KNOWN_ACCOUNTS in
     engine/adapters/token_purchase/adapter.py - not rediscovered, not
     fabricated. Stands in here for "a real spec doc a tester would be
     handed," so the wiki-generator has a real file to ingest from a plain
     directory instead of a string constant embedded in code. -->

POST /purchase

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
    invalid_auth_token, card_not_authorized, invalid_card_number,
    expiry_mismatch, expired_card, invalid_cvv, invalid_credit_count,
    insufficient_funds
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
testing purchases until declines start happening.

## Known accounts

3 real, fully-disclosed accounts - not a partial guessing game. What's
genuinely unknown is each card's spending capacity and whether the
implementation's many validation rules actually behave as documented.

| auth_token | card_number | expiry | cvv |
|---|---|---|---|
| tok_live_9f2c8a41 | 4111104332181963 | 11/2027 | 482 |
| tok_live_7d51e6b0 | 4111001338908383 | 3/2028 | 915 |
| tok_live_c3a9f204 | 4111637940265421 | 8/2028 | 067 |
