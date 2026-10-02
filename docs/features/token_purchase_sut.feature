# token_purchase: a mock credit-purchase API with a mock payment backend.
#
# A reference SUT with one request in and one response out, and rich decline logic:
# auth token, card ownership, Luhn check, expiry, CVV, credit count, tiered pricing
# and a per-card spending capacity that no response ever reveals. No bug was planted
# in it. It was written with ordinary care, so whether it has a bug was unknown going
# in. Two known, accepted findings come from the order of its checks: a card not on
# file is refused before the Luhn check, and a mismatched expiry before the expiry
# age, so "invalid_card_number" and "expired_card" can't be reached from outside.
#
# Start it with: uvicorn engine.adapters.token_purchase.sut:app --port 8000
#
# Code: engine/adapters/token_purchase/sut.py, engine/adapters/token_purchase/adapter.py,
# engine/tests/test_sut_regression.py

Feature: A mock purchase API with real decline rules to test against
  As someone developing the engine
  I want a realistic purchase API whose rules the adapter matches predictions against
  So that the engine is measured on a single-request system with many ways to say no

  Background:
    Given the token_purchase mock SUT is running
    And the account with auth_token "tok_live_9f2c8a41", card "4111104332181963", expiry 11/2027 and cvv "482" is on file

  Scenario Outline: Checks run in a fixed order and the first failure is the decline reason
    # Every decline comes back as HTTP 200 with status "declined". Only a body the
    # request model can't parse gets a 422.
    When I POST to "/purchase" with <request>
    Then the response is HTTP 200 with status "declined" and decline_reason "<reason>"

    Examples:
      | request                                                           | reason               |
      | an auth_token that isn't on file                                  | invalid_auth_token   |
      | a card number not on file, even "1234567890"                      | card_not_authorized  |
      | another account's card                                            | card_not_authorized  |
      | the right card with expiry_year 2020                              | expiry_mismatch      |
      | the right card and expiry with cvv "000"                          | invalid_cvv          |
      | everything right with credit_count 0                              | invalid_credit_count |
      | everything right with a price past the card's remaining capacity  | insufficient_funds   |

  Scenario: A decline shows what was charged and the balance
    When a purchase is declined for "invalid_cvv"
    Then credits_purchased is 0, total_charged is 0.0 and transaction_id is null
    And new_credit_balance is the user's current credit balance
    But after "invalid_auth_token" new_credit_balance is null, because no account was found

  Scenario Outline: The whole order is priced at its bulk tier
    When I buy <credits> credits with everything right
    Then the purchase is approved with total_charged <dollars>

    Examples:
      | credits | dollars |
      | 10      | 0.2     |
      | 99      | 1.98    |
      | 100     | 1.8     |
      | 1000    | 15.0    |

  Scenario: An approved purchase adds credits and spends capacity under a lock
    When I buy 10 credits with everything right
    Then the response has status "approved", decline_reason null and credits_purchased 10
    And new_credit_balance has grown by 10
    And transaction_id is "txn_" followed by a six-digit counter, like "txn_000001"
    And the price is taken from the card's capacity, which is never returned in any response

  Scenario Outline: The adapter matches the prediction against status and decline reason
    Given a cast test predicting status "<predicted_status>" with decline reason "<predicted_reason>"
    When the SUT answers status "<actual_status>" with decline reason "<actual_reason>"
    Then prediction_matched is <matched>
    And the outcome effect is "<effect>"

    Examples:
      | predicted_status | predicted_reason | actual_status | actual_reason       | matched | effect     |
      | approved         |                  | approved      |                     | true    | transition |
      | declined         | invalid_cvv      | declined      | invalid_cvv         | true    | none       |
      | declined         | invalid_cvv      | declined      | card_not_authorized | false   | none       |
      | approved         |                  | declined      | insufficient_funds  | false   | none       |

  Scenario: The Driver is given three real accounts and a ranked oracle
    When a token_purchase run starts
    Then the onboarding evidence lists the 3 known accounts with token, card, expiry and cvv
    And the happy-day request is the first account buying 10 credits
    And the top 15 ranked oracle ideas are included, unless "TOKEN_PURCHASE_ORACLE" is "off"
    And a cast test predicting "declined" must name one of the 8 documented decline reasons
    And the defaults are 2 checkpoints, 5 tests in the first round and 4 after
