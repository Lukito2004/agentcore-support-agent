import asyncio
import logging

from strands.hooks import (
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from guards import add_amount_cents, bind_customer_id
from reliability import LoopGuard, RetryTracker, add_idempotency_key

log = logging.getLogger(__name__)


class ToolCallGuard(HookProvider):
    """Rewrites every tool call before it runs and stops runaway tool loops.

    Sets the signed-in customer_id, the refund amount in cents and the idempotency key from
    code, so none of them depend on what the model wrote.
    """

    def __init__(self, customer_id: str, actor_id: str, session_id: str) -> None:
        self.customer_id = customer_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.loop_guard = LoopGuard()

    def register_hooks(self, registry: HookRegistry, **_kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, lambda _event: self.loop_guard.reset())
        registry.add_callback(BeforeToolCallEvent, self._guard)

    def _guard(self, event: BeforeToolCallEvent) -> None:
        tool_use, overridden = bind_customer_id(dict(event.tool_use), self.customer_id)
        if overridden:
            log.warning("Overrode a foreign customer_id in a %s call", tool_use["name"])
        tool_use = add_amount_cents(tool_use)
        tool_use = add_idempotency_key(tool_use, self.actor_id, self.session_id)
        event.tool_use = tool_use

        reason = self.loop_guard.check(
            str(tool_use.get("toolUseId")), tool_use["name"], tool_use.get("input")
        )
        if reason:
            log.warning("Loop guard cancelled a %s call: %s", tool_use["name"], reason)
            event.cancel_tool = reason


class RetryHook(HookProvider):
    """Retries a failed tool call with exponential backoff when it is retryable and safe."""

    def __init__(self) -> None:
        self.tracker = RetryTracker()

    def register_hooks(self, registry: HookRegistry, **_kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self._maybe_retry)

    async def _maybe_retry(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        delay = self.tracker.next_delay(
            str(event.tool_use.get("toolUseId")), name, event.result, event.exception
        )
        if delay is None:
            return
        log.warning("Retrying %s in %.2fs after a retryable failure", name, delay)
        await asyncio.sleep(delay)
        event.retry = True
