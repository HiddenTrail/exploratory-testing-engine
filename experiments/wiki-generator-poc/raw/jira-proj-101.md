# PROJ-101

<!-- Transcribed verbatim from the mock ticket store in
     engine/bootstrap/jira_mock.py - not rediscovered, not fabricated.
     Stands in for a real fetched JIRA ticket. -->

**Summary:** Exploratory testing needed for the credits-purchase API

**Description:**

This is a credits-purchase API for an app that sells in-app credits.

Normal usage: a client authenticates with a valid auth token, then submits a
credit-card charge (card number, expiry month/year, CVV) to buy a specific
number of credits. A successful purchase returns the number of credits
purchased, the amount charged, and the new credit balance.

Known normal-use values: real test card numbers look like Visa/Mastercard
test numbers (e.g. 4111111111111111 is a well-known Visa test number, and
5555555555554444 is a well-known Mastercard test number) - these pass basic
format/Luhn checks even though they're not real cards. A 3-digit CVV and a
near-future expiry date (e.g. next year) are typical valid values. Purchases
are usually small, realistic quantities of credits (1-100), not huge or
zero/negative amounts.
