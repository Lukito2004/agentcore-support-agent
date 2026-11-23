import pytest

from identity import pre_token


def cognito_event(attributes: dict) -> dict:
    return {"version": "2", "request": {"userAttributes": attributes}, "response": {}}


def test_customer_id_is_added_to_both_tokens():
    event = pre_token.handler(cognito_event({"custom:customer_id": "CUST-1001"}), None)
    details = event["response"]["claimsAndScopeOverrideDetails"]
    for token in ("accessTokenGeneration", "idTokenGeneration"):
        assert details[token]["claimsToAddOrOverride"] == {"customer_id": "CUST-1001"}


def test_user_without_customer_cannot_get_a_token():
    with pytest.raises(ValueError, match="no customer_id"):
        pre_token.handler(cognito_event({"email": "someone@example.com"}), None)
