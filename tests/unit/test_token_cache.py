import asyncio
import base64
import json

import pytest

from token_cache import REFRESH_MARGIN_SECONDS, CachedToken


def jwt_expiring_at(exp: int, marker: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp, "m": marker}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


class FakeIdentity:
    def __init__(self, now: float, lifetime: int = 3600):
        self.now = now
        self.lifetime = lifetime
        self.calls = 0

    async def fetch(self) -> str:
        self.calls += 1
        return jwt_expiring_at(int(self.now) + self.lifetime, f"token-{self.calls}")


def test_token_is_fetched_once_and_reused():
    identity = FakeIdentity(now=1_000_000)
    token = CachedToken(identity.fetch, clock=lambda: identity.now)
    first = asyncio.run(token.ensure_fresh())
    identity.now += 1800  # half an hour later, still valid
    assert asyncio.run(token.ensure_fresh()) == first
    assert identity.calls == 1
    assert token.value == first


def test_token_is_refreshed_before_it_expires():
    identity = FakeIdentity(now=1_000_000)
    token = CachedToken(identity.fetch, clock=lambda: identity.now)
    first = asyncio.run(token.ensure_fresh())
    identity.now += 3600 - REFRESH_MARGIN_SECONDS + 1  # inside the refresh margin
    second = asyncio.run(token.ensure_fresh())
    assert second != first
    assert identity.calls == 2


def test_value_before_first_fetch_is_an_error():
    token = CachedToken(FakeIdentity(now=0).fetch)
    with pytest.raises(RuntimeError, match="ensure_fresh"):
        _ = token.value


def test_fetch_failure_propagates_and_keeps_no_token():
    async def failing_fetch() -> str:
        raise ConnectionError("identity service down")

    token = CachedToken(failing_fetch)
    with pytest.raises(ConnectionError):
        asyncio.run(token.ensure_fresh())
    with pytest.raises(RuntimeError):
        _ = token.value
