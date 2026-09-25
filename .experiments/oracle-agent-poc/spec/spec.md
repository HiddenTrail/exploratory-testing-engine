# token_purchase - System Spec

## Overview

This is a credits-purchase API for an app that sells in-app credits. A client
authenticates with a valid auth token, then submits a credit-card charge
(card number, expiry month/year, CVV) to buy a specific number of credits.
A successful purchase returns the number of credits purchased, the amount
charged, and the new credit balance.

## API

`POST /purchase`

### Request body
- `auth_token` (string) - identifies the calling user.
- `card_number` (string) - the card to charge.
- `expiry_month` (integer, 1-12)
- `expiry_year` (integer)
- `cvv` (string)
- `credit_count` (integer) - how many credits to purchase.

### Response body
- `status` (string) - `"approved"` or `"declined"`.
- `decline_reason` (string or null) - present only if declined. One of:
  `invalid_auth_token`, `card_not_authorized`, `invalid_card_number`,
  `expiry_mismatch`, `expired_card`, `invalid_cvv`, `invalid_credit_count`,
  `insufficient_funds`.
- `credits_purchased` (integer) - 0 if declined.
- `total_charged` (number) - dollars charged, 0 if declined.
- `new_credit_balance` (integer or null) - the user's current total credit
  balance after this transaction (whether or not it was approved). null only
  if `auth_token` itself couldn't be resolved to any account.
- `transaction_id` (string or null) - present only if approved.

Pricing is tiered by bulk quantity - buying more credits in one transaction
may reduce the price per credit for the whole order. The exact tiers are not
published. Each card has a spending capacity that is never revealed directly
in any response (by design - a real payment gateway doesn't reveal a card's
exact available balance to the merchant either).

## Known accounts

Real test card numbers look like Visa/Mastercard test numbers (e.g.
`4111111111111111` is a well-known Visa test number) - these pass basic
format/Luhn checks even though they're not real cards. 3 fully-disclosed
accounts exist for testing:

- `tok_live_9f2c8a41` / `4111104332181963` / exp 11/2027 / cvv 482
- `tok_live_7d51e6b0` / `4111001338908383` / exp 3/2028 / cvv 915
- `tok_live_c3a9f204` / `4111637940265421` / exp 8/2028 / cvv 067

## Happy-day example

A real, captured request and response against a genuinely valid purchase
(captured once, deterministically, while writing this spec - not part of
any test run):

Request:
```json
{"auth_token": "tok_live_9f2c8a41", "card_number": "4111104332181963", "expiry_month": 11, "expiry_year": 2027, "cvv": "482", "credit_count": 10}
```

Response:
```json
{"status": "approved", "decline_reason": null, "credits_purchased": 10, "total_charged": 0.2, "new_credit_balance": 10, "transaction_id": "txn_000001"}
```
