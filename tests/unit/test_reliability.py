import json

import pytest

from reliability import (
    MAX_ATTEMPTS,
    MAX_DELAY_SECONDS,
    MAX_IDENTICAL_CALLS,
    MAX_TOOL_CALLS_PER_TURN,
    LoopGuard,
    RetryTracker,
    add_idempotency_key,
    backoff_seconds,
    idempotency_key,
    is_retryable,
)

REFUND = "refunds___refund_customer"
ORDER = "customer-orders___get_order_status"


def tool_result(payload, status="success") -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"toolUseId": "t1", "status": status, "content": [{"text": text}]}


def failure(code: str, retryable: bool) -> dict:
    error = {"code": code, "message": "x", "retryable": retryable}
    return tool_result({"ok": False, "error": error})


# Idempotency keys


def test_key_is_stable_for_the_same_operation():
    assert idempotency_key("u1", "s1", "124", 500) == idempotency_key("u1", "s1", "124", 500)


@pytest.mark.parametrize(
    "other",
    [
        ("u2", "s1", "124", 500),
        ("u1", "s2", "124", 500),
        ("u1", "s1", "125", 500),
        ("u1", "s1", "124", 501),
    ],
)
def test_key_changes_with_user_session_order_or_amount(other):
    assert idempotency_key("u1", "s1", "124", 500) != idempotency_key(*other)


def test_key_fits_the_backend_format():
    key = idempotency_key("u1", "s1", "124", 500)
    assert key.startswith("op-") and len(key) == 35


def test_model_chosen_key_is_replaced():
    tool_use = {
        "name": REFUND,
        "input": {"order_id": "124", "amount_cents": 500, "idempotency_key": "x"},
    }
    bound = add_idempotency_key(tool_use, "u1", "s1")
    assert bound["input"]["idempotency_key"] == idempotency_key("u1", "s1", "124", 500)


def test_key_is_not_added_to_other_tools():
    tool_use = {"name": ORDER, "input": {"order_id": "124"}}
    assert add_idempotency_key(tool_use, "u1", "s1") == tool_use


def test_key_is_left_alone_when_the_refund_input_is_invalid():
    tool_use = {"name": REFUND, "input": {"order_id": "124", "idempotency_key": "model-key"}}
    assert add_idempotency_key(tool_use, "u1", "s1")["input"]["idempotency_key"] == "model-key"


# Retry decisions


@pytest.mark.parametrize("code", ["BACKEND_UNAVAILABLE", "ORDER_CHANGED"])
def test_errors_marked_retryable_are_retried(code):
    assert is_retryable(REFUND, failure(code, retryable=True), None) is True


@pytest.mark.parametrize(
    "code", ["INVALID_ARGUMENT", "NOT_FOUND", "IDEMPOTENCY_CONFLICT", "REFUND_LIMIT_EXCEEDED"]
)
def test_business_and_validation_errors_are_not_retried(code):
    assert is_retryable(REFUND, failure(code, retryable=False), None) is False


def test_policy_deny_is_not_retried():
    deny = tool_result("Tool Execution Denied: Tool call not allowed due to policy", "error")
    assert is_retryable(REFUND, deny, None) is False


@pytest.mark.parametrize("exc", [TimeoutError("read timed out"), ConnectionError("reset")])
def test_transport_failures_are_retried(exc):
    assert is_retryable(ORDER, None, exc) is True


def test_unexpected_exceptions_are_not_retried():
    assert is_retryable(ORDER, None, ValueError("bad schema")) is False


def test_transient_error_text_is_retried():
    assert is_retryable(ORDER, tool_result("Gateway timeout (504)", "error"), None) is True


def test_success_is_not_retried():
    assert is_retryable(ORDER, tool_result({"ok": True, "data": {}}), None) is False


def test_tools_not_marked_safe_are_never_retried():
    assert is_retryable("other___send_email", None, TimeoutError()) is False


def test_backoff_grows_and_is_capped():
    ceilings = [backoff_seconds(attempt, rng=lambda: 1.0) for attempt in range(1, 7)]
    assert ceilings == [0.5, 1.0, 2.0, 4.0, MAX_DELAY_SECONDS, MAX_DELAY_SECONDS]
    assert backoff_seconds(3, rng=lambda: 0.0) == 0.0  # full jitter


def test_tracker_stops_after_max_attempts():
    tracker = RetryTracker(rng=lambda: 1.0)
    failed = failure("BACKEND_UNAVAILABLE", retryable=True)
    delays = [tracker.next_delay("t1", REFUND, failed, None) for _ in range(MAX_ATTEMPTS + 1)]
    assert delays[: MAX_ATTEMPTS - 1] == [0.5, 1.0]
    assert delays[MAX_ATTEMPTS - 1] is None  # third attempt failed too: give up


def test_tracker_counts_each_tool_call_separately():
    tracker = RetryTracker(rng=lambda: 1.0)
    failed = failure("BACKEND_UNAVAILABLE", retryable=True)
    assert tracker.next_delay("t1", REFUND, failed, None) == 0.5
    assert tracker.next_delay("t2", REFUND, failed, None) == 0.5


# Loop guard


def test_identical_calls_beyond_the_limit_are_cancelled():
    guard = LoopGuard()
    verdicts = [
        guard.check(f"t{i}", ORDER, {"order_id": "123"}) for i in range(MAX_IDENTICAL_CALLS + 1)
    ]
    assert verdicts[:-1] == [None] * MAX_IDENTICAL_CALLS
    assert "already called" in verdicts[-1]


def test_retries_of_the_same_call_are_not_counted():
    guard = LoopGuard()
    assert all(guard.check("t1", ORDER, {"order_id": "123"}) is None for _ in range(10))


def test_total_tool_budget_per_turn():
    guard = LoopGuard()
    verdicts = [
        guard.check(f"t{i}", ORDER, {"order_id": str(i)})
        for i in range(MAX_TOOL_CALLS_PER_TURN + 1)
    ]
    assert verdicts[:-1] == [None] * MAX_TOOL_CALLS_PER_TURN
    assert "budget" in verdicts[-1]


def test_reset_starts_a_new_turn():
    guard = LoopGuard()
    for i in range(MAX_IDENTICAL_CALLS):
        guard.check(f"t{i}", ORDER, {"order_id": "123"})
    guard.reset()
    assert guard.check("t-new", ORDER, {"order_id": "123"}) is None
