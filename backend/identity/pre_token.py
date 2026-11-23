"""Cognito pre-token-generation trigger (V2): signs the user's customer_id into their tokens.

The agent trusts this claim because Cognito signs it and users cannot change the attribute.
"""

CUSTOMER_ATTRIBUTE = "custom:customer_id"


def handler(event: dict, _context) -> dict:
    customer_id = event.get("request", {}).get("userAttributes", {}).get(CUSTOMER_ATTRIBUTE)
    if not customer_id:
        # Raising makes Cognito refuse the sign-in, so no token exists without a customer.
        raise ValueError("user has no customer_id; ask an admin to link the account")

    claims = {"claimsToAddOrOverride": {"customer_id": customer_id}}
    event.setdefault("response", {})["claimsAndScopeOverrideDetails"] = {
        "accessTokenGeneration": claims,
        "idTokenGeneration": claims,
    }
    return event
