import base64
import json

import pytest
from botocore.exceptions import ClientError

from auth import AuthError, CognitoAuth, Tokens, token_claims
from config import load_config

NOW = 1_000_000.0


def jwt(claims: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


class FakeCognito:
    """Records calls and answers like Cognito's initiate_auth."""

    def __init__(self, result=None, error_code=None):
        self.result, self.error_code, self.calls, self.revoked = result, error_code, [], []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.error_code:
            raise ClientError({"Error": {"Code": self.error_code}}, "InitiateAuth")
        return self.result

    def revoke_token(self, **kwargs):
        self.revoked.append(kwargs)


def issued(access="access-1", refresh="refresh-1"):
    result = {"AccessToken": access, "ExpiresIn": 3600}
    if refresh:
        result["RefreshToken"] = refresh
    return {"AuthenticationResult": result}


def test_sign_in_returns_tokens_with_expiry():
    cognito = FakeCognito(issued())
    tokens = CognitoAuth("client-1", "us-east-1", cognito).sign_in("a@example.com", "pw", NOW)
    assert tokens == Tokens("access-1", "refresh-1", NOW + 3600)
    assert cognito.calls[0]["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert cognito.calls[0]["ClientId"] == "client-1"


@pytest.mark.parametrize(
    ("error_code", "message"),
    [
        ("NotAuthorizedException", "Wrong email or password."),
        ("UserNotFoundException", "Wrong email or password."),
        ("TooManyRequestsException", "Sign-in is unavailable"),
    ],
)
def test_sign_in_errors_are_safe_messages(error_code, message):
    auth = CognitoAuth("client-1", "us-east-1", FakeCognito(error_code=error_code))
    with pytest.raises(AuthError, match=message):
        auth.sign_in("a@example.com", "pw")


def test_account_needing_a_new_password_cannot_sign_in():
    cognito = FakeCognito({"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "s"})
    with pytest.raises(AuthError, match="cannot sign in here yet"):
        CognitoAuth("client-1", "us-east-1", cognito).sign_in("a@example.com", "pw")


def test_empty_credentials_are_not_sent():
    cognito = FakeCognito(issued())
    with pytest.raises(AuthError):
        CognitoAuth("client-1", "us-east-1", cognito).sign_in("", "")
    assert cognito.calls == []


def test_fresh_tokens_are_reused_and_expiring_ones_refreshed():
    cognito = FakeCognito(issued(access="access-2", refresh=None))
    auth = CognitoAuth("client-1", "us-east-1", cognito)
    tokens = Tokens("access-1", "refresh-1", NOW + 3600)

    assert auth.fresh(tokens, NOW) is tokens
    assert cognito.calls == []

    refreshed = auth.fresh(tokens, NOW + 3550)
    assert refreshed == Tokens("access-2", "refresh-1", NOW + 3550 + 3600)
    assert cognito.calls[0]["AuthFlow"] == "REFRESH_TOKEN_AUTH"


def test_failed_refresh_asks_to_sign_in_again():
    auth = CognitoAuth("client-1", "us-east-1", FakeCognito(error_code="NotAuthorizedException"))
    with pytest.raises(AuthError, match="sign in again"):
        auth.fresh(Tokens("a", "r", NOW), NOW)


def test_sign_out_revokes_the_refresh_token():
    cognito = FakeCognito()
    CognitoAuth("client-1", "us-east-1", cognito).sign_out(Tokens("a", "refresh-1", NOW))
    assert cognito.revoked == [{"Token": "refresh-1", "ClientId": "client-1"}]


def test_token_claims_reads_the_customer_id():
    assert token_claims(jwt({"customer_id": "CUST-1001"}))["customer_id"] == "CUST-1001"


def test_config_prefers_env_vars_over_stack_outputs():
    def no_stacks(*_):
        raise AssertionError("stack outputs should not be read")

    env = {"AGENT_RUNTIME_ARN": "arn:runtime", "COGNITO_CLIENT_ID": "client-1"}
    config = load_config(env, no_stacks)
    assert (config.region, config.runtime_arn, config.chat_client_id) == (
        "us-east-1",
        "arn:runtime",
        "client-1",
    )


def test_config_finds_the_runtime_arn_by_output_prefix():
    outputs = {
        "AgentCore-SupportAgent-default": {
            "ApplicationRuntimeSupportAgentRuntimeIdOutputAB12": "id",
            "ApplicationRuntimeSupportAgentRuntimeArnOutput11CA84D7": "arn:runtime",
        },
        "SupportAgentBackend": {"ChatClientId": "client-1"},
    }
    config = load_config({}, lambda stack, _region: outputs[stack])
    assert config.runtime_arn == "arn:runtime"
    assert config.chat_client_id == "client-1"
