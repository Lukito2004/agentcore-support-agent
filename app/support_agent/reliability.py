"""Retry, idempotency and loop rules for tool calls. Pure logic, wired in by hooks.py."""

import hashlib
import json
import random
from collections import Counter
from collections.abc import Callable

from guards import REFUND_TOOL, tool_base_name

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 4.0

# Retrying needs a retryable error AND an operation that is safe to repeat. Reads are safe;
# refund_customer is safe only because every call carries a code-generated idempotency key.
SAFE_TO_RETRY = frozenset({"get_customer", "get_order_status", "refund_customer"})

MAX_IDENTICAL_CALLS = 2
MAX_TOOL_CALLS_PER_TURN = 8

_TRANSIENT_MARKERS = ("timed out", "timeout", "temporarily unavailable", "throttl", "503", "504")
_DECISION_MARKERS = ("tool execution denied",)  # a policy deny is a decision, not a failure


def idempotency_key(actor_id: str, session_id: str, order_id: str, amount_cents: int) -> str:
    """Same user, conversation, order and amount -> same key, so a repeat replays the refund."""
    digest = hashlib.sha256(f"{actor_id}|{session_id}|{order_id}|{amount_cents}".encode())
    return f"op-{digest.hexdigest()[:32]}"


def add_idempotency_key(tool_use: dict, actor_id: str, session_id: str) -> dict:
    """Replace whatever key the model chose; models invent new keys on retry, which breaks dedupe.

    Expects amount_cents to be set already (see guards.add_amount_cents).
    """
    if tool_base_name(str(tool_use.get("name", ""))) != REFUND_TOOL:
        return tool_use
    tool_input = dict(tool_use.get("input") or {})
    order_id, cents = tool_input.get("order_id"), tool_input.get("amount_cents")
    if isinstance(order_id, str) and isinstance(cents, int):
        tool_input["idempotency_key"] = idempotency_key(actor_id, session_id, order_id, cents)
    return {**tool_use, "input": tool_input}


def _result_text(result: dict | None) -> str:
    content = (result or {}).get("content") or []
    return " ".join(block.get("text", "") for block in content if isinstance(block, dict))


def is_retryable(tool_name: str, result: dict | None, exception: BaseException | None) -> bool:
    if tool_base_name(tool_name) not in SAFE_TO_RETRY:
        return False
    if exception is not None:
        message = str(exception).lower()
        return isinstance(exception, TimeoutError | ConnectionError) or any(
            marker in message for marker in _TRANSIENT_MARKERS
        )

    text = _result_text(result)
    lowered = text.lower()
    if any(marker in lowered for marker in _DECISION_MARKERS):
        return False
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("ok") is False:
        return bool((payload.get("error") or {}).get("retryable"))
    is_error = (result or {}).get("status") == "error"
    return is_error and any(marker in lowered for marker in _TRANSIENT_MARKERS)


def backoff_seconds(attempt: int, rng: Callable[[], float] = random.random) -> float:
    """Full-jitter exponential backoff: a random delay up to 0.5s, 1s, 2s, ... capped at 4s."""
    ceiling = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2 ** (attempt - 1))
    return ceiling * rng()


class RetryTracker:
    """Decides, per tool call, whether to retry and after how long."""

    def __init__(self, rng: Callable[[], float] = random.random) -> None:
        self._attempts: dict[str, int] = {}
        self._rng = rng

    def next_delay(
        self, tool_use_id: str, tool_name: str, result: dict | None, exception: BaseException | None
    ) -> float | None:
        """Seconds to wait before retrying, or None to accept the result as final."""
        attempt = self._attempts.get(tool_use_id, 1)
        if attempt >= MAX_ATTEMPTS or not is_retryable(tool_name, result, exception):
            self._attempts.pop(tool_use_id, None)
            return None
        self._attempts[tool_use_id] = attempt + 1
        return backoff_seconds(attempt, self._rng)


class LoopGuard:
    """Stops a turn from repeating the same tool call or calling tools without end."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._seen_ids: set[str] = set()
        self._calls: Counter[str] = Counter()
        self._total = 0

    def check(self, tool_use_id: str, tool_name: str, tool_input: object) -> str | None:
        """Returns a cancel message, or None to let the call run. Retries are not counted."""
        if tool_use_id in self._seen_ids:
            return None
        self._seen_ids.add(tool_use_id)
        self._total += 1
        signature = f"{tool_name}:{json.dumps(tool_input, sort_keys=True, default=str)}"
        self._calls[signature] += 1
        if self._calls[signature] > MAX_IDENTICAL_CALLS:
            return "This tool was already called with these arguments. Answer from that result."
        if self._total > MAX_TOOL_CALLS_PER_TURN:
            return "The tool budget for this turn is used up. Answer with what you have."
        return None
