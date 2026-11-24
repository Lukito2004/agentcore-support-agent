"""Who is calling. Identity comes only from the JWT, never from the request payload."""

import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

CUSTOMER_ID_PATTERN = re.compile(r"^CUST-\d{3,10}$")


class AuthError(Exception):
    """The caller could not be identified. The message is safe to return."""


@dataclass(frozen=True)
class Caller:
    actor_id: str
    customer_id: str

    @property
    def log_id(self) -> str:
        """Stable pseudonym for logs, so raw user IDs never reach CloudWatch."""
        return hashlib.sha256(self.actor_id.encode()).hexdigest()[:12]


# Used only under `agentcore dev`, which has no authorizer in front of it.
LOCAL_DEV_CALLER = Caller(actor_id="local-dev-user", customer_id="CUST-1001")


def decode_jwt_claims(token: str) -> dict:
    """Decode a JWT payload without checking its signature; raises ValueError if malformed."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, binascii.Error) as exc:
        raise ValueError("malformed JWT") from exc
    if not isinstance(claims, dict):
        raise ValueError("malformed JWT")
    return claims


def _claims(token: str) -> dict:
    """The signature, issuer, expiry and client are already verified by the AgentCore Runtime
    authorizer before the request reaches this code, so the claims can be trusted here.
    """
    try:
        return decode_jwt_claims(token)
    except ValueError as exc:
        raise AuthError("malformed bearer token") from exc


def caller_from_headers(headers: Mapping[str, str] | None) -> Caller:
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    authorization = headers.get("authorization", "")
    if not authorization:
        if os.getenv("LOCAL_DEV") == "1":
            return LOCAL_DEV_CALLER
        raise AuthError("missing bearer token")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("expected a bearer token")

    claims = _claims(token.strip())
    if claims.get("token_use") != "access":
        raise AuthError("an access token is required")
    actor_id, customer_id = claims.get("sub"), claims.get("customer_id")
    if not isinstance(actor_id, str) or not actor_id:
        raise AuthError("token has no subject")
    if not isinstance(customer_id, str) or not CUSTOMER_ID_PATTERN.fullmatch(customer_id):
        raise AuthError("account is not linked to a customer")
    return Caller(actor_id=actor_id, customer_id=customer_id)


class SessionRegistry:
    """Binds each runtime session to the first user who used it.

    AgentCore does not enforce session-to-user mapping, so the app must: a session ID sent
    by a different user is rejected instead of exposing someone else's conversation.
    """

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def claim(self, session_id: str, actor_id: str) -> bool:
        return self._owners.setdefault(session_id, actor_id) == actor_id
