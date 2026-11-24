import time
from collections.abc import Awaitable, Callable

from caller import decode_jwt_claims

# Refresh this long before expiry, so a token never runs out in the middle of an invocation.
REFRESH_MARGIN_SECONDS = 300


class CachedToken:
    """An access token reused across invocations and refreshed shortly before it expires.

    Sessions can last hours while Cognito tokens last one, so the token is checked at the start
    of every invocation instead of once at startup.
    """

    def __init__(self, fetch: Callable[[], Awaitable[str]], clock: Callable[[], float] = time.time):
        self._fetch = fetch
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    async def ensure_fresh(self) -> str:
        if self._token is None or self._expires_at - self._clock() < REFRESH_MARGIN_SECONDS:
            token = await self._fetch()
            self._expires_at = float(decode_jwt_claims(token).get("exp", 0))
            self._token = token
        return self._token

    @property
    def value(self) -> str:
        if self._token is None:
            raise RuntimeError("token used before ensure_fresh() was awaited")
        return self._token
