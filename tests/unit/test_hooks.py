import asyncio
import json
from types import SimpleNamespace

import pytest
from strands.hooks import AfterToolCallEvent, BeforeInvocationEvent, BeforeToolCallEvent

import hooks
from guards import AMOUNT_NOT_STATED
from hooks import RetryHook, ToolCallGuard
from reliability import MAX_ATTEMPTS, idempotency_key

SESSION = "session-test-" + "a" * 32
REFUND = "refunds___refund_customer"
ORDER = "customer-orders___get_order_status"


def guard() -> ToolCallGuard:
    return ToolCallGuard("CUST-1001", "user-1", SESSION)


def before(name: str, tool_input: dict, typed: str = "", tool_id: str = "t1"):
    """A stand-in for Strands' BeforeToolCallEvent: only the fields the hook uses."""
    messages = [{"role": "user", "content": [{"text": typed}]}]
    return SimpleNamespace(
        tool_use={"toolUseId": tool_id, "name": name, "input": tool_input},
        agent=SimpleNamespace(messages=messages),
        cancel_tool=False,
    )


# ToolCallGuard


def test_refund_fields_come_from_code_not_from_the_model():
    event = before(
        REFUND,
        {
            "customer_id": "CUST-9999",
            "order_id": "124",
            "amount": 25,
            "amount_cents": 1,
            "idempotency_key": "model-made",
        },
        typed="Please refund 25 USD for order 124",
    )
    guard()._guard(event)
    tool_input = event.tool_use["input"]
    assert tool_input["customer_id"] == "CUST-1001"
    assert tool_input["amount_cents"] == 2500
    # The key needs amount_cents, so it must be computed after it.
    assert tool_input["idempotency_key"] == idempotency_key("user-1", SESSION, "124", 2500)
    assert event.cancel_tool is False


def test_a_refund_amount_the_customer_never_typed_is_cancelled():
    event = before(
        REFUND,
        {"order_id": "124", "amount": 20, "reason": "chipped"},
        typed="Refund minus 5 dollars for order 124, the mug was chipped.",
    )
    guard()._guard(event)
    assert event.cancel_tool == AMOUNT_NOT_STATED


def test_read_tools_are_bound_to_the_customer_without_an_amount_check():
    event = before(ORDER, {"customer_id": "CUST-1002", "order_id": "125"}, typed="order 125?")
    guard()._guard(event)
    assert event.tool_use["input"]["customer_id"] == "CUST-1001"
    assert event.cancel_tool is False


def test_the_third_identical_call_is_cancelled_but_retries_are_not_counted():
    hook = guard()
    outcomes = []
    for tool_id in ("t1", "t1", "t1", "t2", "t3"):  # t1 three times: its retries
        event = before(ORDER, {"order_id": "123"}, tool_id=tool_id)
        hook._guard(event)
        outcomes.append(event.cancel_tool)
    assert outcomes[:4] == [False, False, False, False]
    assert "already called" in outcomes[4]


def test_a_new_turn_resets_the_loop_guard():
    callbacks = {}
    registry = SimpleNamespace(add_callback=lambda kind, cb: callbacks.setdefault(kind, cb))
    hook = guard()
    hook.register_hooks(registry)
    for tool_id in ("t1", "t2"):
        callbacks[BeforeToolCallEvent](before(ORDER, {"order_id": "123"}, tool_id=tool_id))
    callbacks[BeforeInvocationEvent](None)
    event = before(ORDER, {"order_id": "123"}, tool_id="t3")
    callbacks[BeforeToolCallEvent](event)
    assert event.cancel_tool is False
    assert AfterToolCallEvent not in callbacks


# RetryHook


def after(result_payload=None, *, status="success", text=None, tool_id="t1"):
    content = text if text is not None else json.dumps(result_payload)
    return SimpleNamespace(
        tool_use={"toolUseId": tool_id, "name": ORDER},
        result={"toolUseId": tool_id, "status": status, "content": [{"text": content}]},
        exception=None,
        retry=False,
    )


@pytest.fixture
def sleeps(monkeypatch):
    waited = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(hooks.asyncio, "sleep", fake_sleep)
    return waited


def unavailable():
    return after({"ok": False, "error": {"code": "BACKEND_UNAVAILABLE", "retryable": True}})


def test_a_retryable_error_is_retried_after_a_backoff(sleeps):
    event = unavailable()
    asyncio.run(RetryHook()._maybe_retry(event))
    assert event.retry is True
    assert len(sleeps) == 1 and 0 <= sleeps[0] <= 0.5


def test_retries_stop_after_the_last_attempt(sleeps):
    hook = RetryHook()
    decisions = []
    for _ in range(MAX_ATTEMPTS):
        event = unavailable()
        asyncio.run(hook._maybe_retry(event))
        decisions.append(event.retry)
    assert decisions == [True] * (MAX_ATTEMPTS - 1) + [False]


@pytest.mark.parametrize(
    "event",
    [
        after(text="Tool Execution Denied: not allowed by policy", status="error"),
        after({"ok": False, "error": {"code": "ORDER_NOT_FOUND", "retryable": False}}),
        after({"ok": True, "data": {}}),
    ],
)
def test_policy_denials_business_errors_and_success_are_not_retried(sleeps, event):
    asyncio.run(RetryHook()._maybe_retry(event))
    assert event.retry is False
    assert sleeps == []
