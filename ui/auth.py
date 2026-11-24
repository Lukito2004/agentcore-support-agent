"""Cognito sign-in for the chat app. Tokens stay in server memory, never in the browser."""

import base64
import contextlib
import json
import time
from dataclasses import dataclass, replace

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Refresh a little early so a token never expires halfway through a reply.
REFRESH_MARGIN_SECONDS = 120
WRONG_CREDENTIALS = ("NotAuthorizedException", "UserNotFoundException")


class AuthError(Exception):
    """A sign-in problem; the message is safe to show to the user."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float

    def expiring(self, now: float) -> bool:
        return now >= self.expires_at - REFRESH_MARGIN_SECONDS


def token_claims(token: str) -> dict:
    """Read a JWT's claims for display only; the agent's runtime does the real validation."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class CognitoAuth:
    def __init__(self, client_id: str, region: str, client=None):
        self._client_id = client_id
        self._cognito = client or boto3.client("cognito-idp", region_name=region)

    def _authenticate(self, flow: str, parameters: dict) -> dict:
        result = self._cognito.initiate_auth(
            ClientId=self._client_id, AuthFlow=flow, AuthParameters=parameters
        )
        if "AuthenticationResult" not in result:
            # e.g. NEW_PASSWORD_REQUIRED for an account an admin has not finished setting up.
            raise AuthError("This account cannot sign in here yet. Please contact support.")
        return result["AuthenticationResult"]

    def sign_in(self, email: str, password: str, now: float | None = None) -> Tokens:
        if not email or not password:
            raise AuthError("Enter your email and password.")
        try:
            result = self._authenticate(
                "USER_PASSWORD_AUTH", {"USERNAME": email, "PASSWORD": password}
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in WRONG_CREDENTIALS:
                raise AuthError("Wrong email or password.") from exc
            raise AuthError("Sign-in is unavailable right now. Please try again.") from exc
        except BotoCoreError as exc:
            raise AuthError("Sign-in is unavailable right now. Please try again.") from exc
        return Tokens(
            access_token=result["AccessToken"],
            refresh_token=result["RefreshToken"],
            expires_at=(now or time.time()) + result["ExpiresIn"],
        )

    def fresh(self, tokens: Tokens, now: float | None = None) -> Tokens:
        """Return usable tokens, refreshing the access token when it is about to expire."""
        now = now or time.time()
        if not tokens.expiring(now):
            return tokens
        try:
            result = self._authenticate(
                "REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": tokens.refresh_token}
            )
        except (ClientError, BotoCoreError) as exc:
            raise AuthError("Your sign-in has expired. Please sign in again.") from exc
        # Cognito keeps the same refresh token on refresh.
        return replace(
            tokens, access_token=result["AccessToken"], expires_at=now + result["ExpiresIn"]
        )

    def sign_out(self, tokens: Tokens) -> None:
        """Revoke the refresh token so it cannot mint new access tokens."""
        # Best effort: local sign-out happens anyway, and the token expires on its own.
        with contextlib.suppress(ClientError, BotoCoreError):
            self._cognito.revoke_token(Token=tokens.refresh_token, ClientId=self._client_id)
