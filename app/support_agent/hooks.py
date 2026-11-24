import asyncio
import logging

from strands.hooks import (
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

import telemetry
from caller import pseudonym
from guards import (
    AMOUNT_NOT_STATED,
    REFUND_TOOL,
    add_amount_cents,
    amount_stated_by_customer,
    bind_customer_id,
    customer_texts,
    tool_base_name,
)
from reliability import LoopGuard, RetryTracker, add_idempotency_key, is_retryable, tool_outcome

log = logging.getLogger(__name__)


class ToolCallGuard(HookProvider):
    """Rewrites every tool call before it runs, blocks unrequested refunds, stops tool loops.

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

        tool = tool_base_name(tool_use["name"])
        key = (tool_use.get("input") or {}).get("idempotency_key") if tool == REFUND_TOOL else None
        telemetry.record(
            "tool_call",
            tool=tool,
            actor=pseudonym(self.actor_id),
            customer_id_overridden=overridden,
            idempotency_key=key,
        )

        # Money moves only for an amount the customer typed, never one the model worked out.
        if not amount_stated_by_customer(tool_use, customer_texts(event.agent.messages)):
            log.warning("Blocked a refund for an amount the customer never typed")
            telemetry.record(
                "refund_amount_blocked",
                tool=tool,
                amount_cents=(tool_use.get("input") or {}).get("amount_cents"),
            )
            event.cancel_tool = AMOUNT_NOT_STATED
            return

        reason = self.loop_guard.check(
            str(tool_use.get("toolUseId")), tool_use["name"], tool_use.get("input")
        )
        if reason:
            log.warning("Loop guard cancelled a %s call: %s", tool_use["name"], reason)
            telemetry.record("loop_guard_blocked", tool=tool, reason=reason)
            event.cancel_tool = reason


class RetryHook(HookProvider):
    """Retries a failed tool call with exponential backoff when it is retryable and safe."""

    def __init__(self) -> None:
        self.tracker = RetryTracker()

    def register_hooks(self, registry: HookRegistry, **_kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self._maybe_retry)

    async def _maybe_retry(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        tool_use_id = str(event.tool_use.get("toolUseId"))
        attempt = self.tracker.attempt(tool_use_id)
        outcome, error_code = tool_outcome(event.result, event.exception)
        telemetry.record(
            "tool_result",
            tool=tool_base_name(name),
            attempt=attempt,
            outcome=outcome,
            error_code=error_code,
            retryable=is_retryable(name, event.result, event.exception) if error_code else None,
        )
        delay = self.tracker.next_delay(tool_use_id, name, event.result, event.exception)
        if delay is None:
            return
        log.warning("Retrying %s in %.2fs after a retryable failure", name, delay)
        telemetry.record(
            "tool_retry", tool=tool_base_name(name), next_attempt=attempt + 1, delay_s=delay
        )
        await asyncio.sleep(delay)
        event.retry = True
