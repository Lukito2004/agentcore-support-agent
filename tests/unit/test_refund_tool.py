from decimal import Decimal

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from common import dynamo
from guards import to_cents
from refund_tool import handler

# Order 124 belongs to CUST-1001, is DELIVERED and cost 25.00 USD.
BASE = {
    "customer_id": "CUST-1001",
    "order_id": "124",
    "amount": 10,
    "reason": "Mug arrived chipped",
    "idempotency_key": "operation-123",
}


def refund(lambda_context, **overrides):
    """Call the tool as the agent does: amount_cents is derived from amount unless overridden."""
    args = {**BASE, **overrides}
    if "amount_cents" not in overrides:
        args["amount_cents"] = to_cents(args.get("amount"))
    return handler.lambda_handler(args, lambda_context("refunds___refund_customer"))


def refunded_total(table, order_id: str = "124") -> Decimal:
    return (
        table("ORDERS_TABLE")
        .get_item(Key={"order_id": order_id})["Item"]
        .get("refunded_total", Decimal(0))
    )


def test_refund_is_recorded_and_order_total_updated(table, lambda_context):
    result = refund(lambda_context)
    assert result["ok"] is True
    assert result["data"]["status"] == "COMPLETED"
    assert result["data"]["amount"] == 10
    assert result["data"]["replayed"] is False
    assert result["data"]["refund_id"].startswith("RF-")
    assert refunded_total(table) == Decimal("10.00")


def test_retry_with_same_key_returns_original_and_refunds_once(table, lambda_context):
    first = refund(lambda_context)
    second = refund(lambda_context, reason="Reworded by the model on retry")
    assert second["ok"] is True
    assert second["data"]["replayed"] is True
    assert second["data"]["refund_id"] == first["data"]["refund_id"]
    assert table("REFUNDS_TABLE").scan()["Count"] == 1
    assert refunded_total(table) == Decimal("10.00")


def test_same_key_for_a_different_refund_is_a_conflict(table, lambda_context):
    refund(lambda_context)
    result = refund(lambda_context, amount=12)
    assert result["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert refunded_total(table) == Decimal("10.00")


def test_refunds_cannot_exceed_the_order_total(table, lambda_context):
    assert refund(lambda_context, amount=20)["ok"] is True
    result = refund(lambda_context, amount=10, idempotency_key="operation-124")
    assert result["error"]["code"] == "EXCEEDS_ORDER_TOTAL"
    assert "5.00" in result["error"]["message"]
    assert refunded_total(table) == Decimal("20.00")


@pytest.mark.parametrize(("amount", "ok"), [(1000, True), (1000.01, False), (5000, False)])
def test_refund_limit(table, lambda_context, amount, ok):
    # Order 125 (CUST-1002, 1299.00 USD) is large enough to test the limit itself.
    result = refund(lambda_context, customer_id="CUST-1002", order_id="125", amount=amount)
    assert result["ok"] is ok
    if not ok:
        assert result["error"]["code"] == "REFUND_LIMIT_EXCEEDED"
        assert table("REFUNDS_TABLE").scan()["Count"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "one thousand dollars"},
        {"amount": "10"},
        {"amount": True},
        {"amount": 0},
        {"amount": -5},
        {"amount": 10.999},
        {"amount": float("nan")},
        {"reason": "   "},
        {"reason": "x" * 501},
        {"idempotency_key": "short"},
        {"idempotency_key": "has spaces in it"},
        {"customer_id": "1001"},
    ],
)
def test_invalid_arguments_write_nothing(table, lambda_context, overrides):
    result = refund(lambda_context, **overrides)
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["retryable"] is False
    assert table("REFUNDS_TABLE").scan()["Count"] == 0


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"customer_id": "CUST-1002"}, "ORDER_NOT_FOUND"),  # someone else's order
        ({"order_id": "999"}, "ORDER_NOT_FOUND"),
        ({"customer_id": "CUST-1003", "order_id": "127"}, "NOT_REFUNDABLE"),  # cancelled
        ({"customer_id": "CUST-1002", "order_id": "126"}, "NOT_REFUNDABLE"),  # processing
    ],
)
def test_order_must_belong_to_customer_and_be_refundable(table, lambda_context, overrides, code):
    result = refund(lambda_context, **overrides)
    assert result["error"]["code"] == code
    assert table("REFUNDS_TABLE").scan()["Count"] == 0


def test_timeout_is_retryable_and_retry_does_not_duplicate(table, lambda_context, monkeypatch):
    real_write = handler._write

    def commit_then_time_out(refund_item, order):
        real_write(refund_item, order)
        raise ReadTimeoutError(endpoint_url="https://dynamodb")

    monkeypatch.setattr(handler, "_write", commit_then_time_out)
    first = refund(lambda_context)
    assert first["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert first["error"]["retryable"] is True

    monkeypatch.setattr(handler, "_write", real_write)
    retry = refund(lambda_context)
    assert retry["data"]["replayed"] is True
    assert refunded_total(table) == Decimal("10.00")


def test_concurrent_call_with_same_key_is_caught_by_the_transaction(
    table, lambda_context, monkeypatch
):
    first = refund(lambda_context)
    real_get_item = dynamo.get_item
    calls = {"refunds": 0}

    def miss_first_refund_lookup(env_var, key):
        # Pretend the parallel call had not committed yet when this one checked.
        if env_var == "REFUNDS_TABLE" and calls["refunds"] == 0:
            calls["refunds"] += 1
            return None
        return real_get_item(env_var, key)

    monkeypatch.setattr(dynamo, "get_item", miss_first_refund_lookup)
    second = refund(lambda_context)
    assert second["data"]["replayed"] is True
    assert second["data"]["refund_id"] == first["data"]["refund_id"]
    assert refunded_total(table) == Decimal("10.00")


def test_throttling_is_retryable(seeded_tables, lambda_context, monkeypatch):
    class Throttled:
        def get_item(self, **_):
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "GetItem")

    monkeypatch.setattr(dynamo, "table", lambda _env: Throttled())
    result = refund(lambda_context)
    assert result["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert result["error"]["retryable"] is True


@pytest.mark.parametrize(
    ("amount", "amount_cents"),
    [(10, 100), (10, 1001), (10, None), (10, "1000"), (10, 1000.0), (10, True)],
)
def test_amount_cents_must_match_amount(table, lambda_context, amount, amount_cents):
    result = refund(lambda_context, amount=amount, amount_cents=amount_cents)
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert table("REFUNDS_TABLE").scan()["Count"] == 0


def test_caller_skipping_the_agent_cannot_hide_a_big_amount(table, lambda_context):
    # Small amount_cents to pass the Gateway policy, big amount to get paid: still rejected.
    result = refund(
        lambda_context, customer_id="CUST-1002", order_id="125", amount=999, amount_cents=100
    )
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert table("REFUNDS_TABLE").scan()["Count"] == 0
