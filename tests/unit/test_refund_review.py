import json
from decimal import Decimal

from botocore.exceptions import ClientError

from common import workflow
from guards import to_cents
from refund_tool import handler

# Order 125 belongs to CUST-1002, is SHIPPED and cost 1299.00 USD.
BASE = {
    "customer_id": "CUST-1002",
    "order_id": "125",
    "amount": 700,
    "reason": "Screen flickers",
    "idempotency_key": "operation-700",
}


def refund(lambda_context, **overrides):
    args = {**BASE, **overrides}
    args["amount_cents"] = to_cents(args["amount"])
    return handler.lambda_handler(args, lambda_context("refunds___refund_customer"))


def totals(table) -> tuple[Decimal, Decimal]:
    order = table("ORDERS_TABLE").get_item(Key={"order_id": "125"})["Item"]
    return order.get("refunded_total", Decimal(0)), order.get("pending_refund_total", Decimal(0))


def test_small_refund_completes_without_review(table, lambda_context, review_workflow):
    result = refund(lambda_context, amount=100)
    assert result["data"]["status"] == "COMPLETED"
    assert "note" not in result["data"]
    assert review_workflow() == []
    assert totals(table) == (Decimal(100), Decimal(0))


def test_refund_of_500_or_more_is_held_for_review(table, lambda_context, review_workflow):
    result = refund(lambda_context)
    assert result["ok"] is True
    assert result["data"]["status"] == "PENDING_APPROVAL"
    assert "Not refunded yet" in result["data"]["note"]
    assert totals(table) == (Decimal(700), Decimal(700))

    [execution] = review_workflow()
    assert execution["name"] == result["data"]["refund_id"]


def test_review_input_is_the_same_for_a_stored_refund(table, lambda_context):
    refund(lambda_context)
    stored = table("REFUNDS_TABLE").get_item(Key={"idempotency_key": "operation-700"})["Item"]
    data = json.loads(workflow.review_input(stored))
    assert data["amount"] == "700.00"
    assert data["idempotency_key"] == "operation-700"


def test_splitting_a_refund_does_not_skip_review(table, lambda_context, review_workflow):
    assert refund(lambda_context, amount=450)["data"]["status"] == "COMPLETED"
    second = refund(lambda_context, amount=50, idempotency_key="operation-050")
    assert second["data"]["status"] == "PENDING_APPROVAL"
    assert len(review_workflow()) == 1


def test_limit_still_applies_to_reviewed_refunds(table, lambda_context, review_workflow):
    assert refund(lambda_context, amount=1000)["data"]["status"] == "PENDING_APPROVAL"
    result = refund(lambda_context, amount=1000.01, idempotency_key="operation-big")
    assert result["error"]["code"] == "REFUND_LIMIT_EXCEEDED"


def test_retry_while_pending_replays_without_a_second_review(
    table, lambda_context, review_workflow
):
    first = refund(lambda_context)
    second = refund(lambda_context, reason="Reworded on retry")
    assert second["data"]["replayed"] is True
    assert second["data"]["status"] == "PENDING_APPROVAL"
    assert second["data"]["refund_id"] == first["data"]["refund_id"]
    assert len(review_workflow()) == 1
    assert totals(table) == (Decimal(700), Decimal(700))


def test_failed_review_start_is_retryable_and_the_retry_starts_it(
    table, lambda_context, review_workflow, monkeypatch
):
    class Unavailable:
        def start_execution(self, **_):
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "StartExecution")

    real_client = workflow.client
    monkeypatch.setattr(workflow, "client", lambda: Unavailable())
    first = refund(lambda_context)
    assert first["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert first["error"]["retryable"] is True
    assert review_workflow() == []

    monkeypatch.setattr(workflow, "client", real_client)
    retry = refund(lambda_context)
    assert retry["data"]["replayed"] is True
    assert len(review_workflow()) == 1
    # The refund was saved once, so the amount is held once.
    assert totals(table) == (Decimal(700), Decimal(700))


def test_concurrent_small_refunds_cannot_skip_the_review(table, lambda_context, monkeypatch):
    # Two 300 USD refunds read the order at the same moment, before either was written.
    stale_order = table("ORDERS_TABLE").get_item(Key={"order_id": "125"})["Item"]
    first = refund(lambda_context, amount=300, idempotency_key="operation-first")
    assert first["data"]["status"] == "COMPLETED"

    real_load = handler._load_refundable_order
    monkeypatch.setattr(handler, "_load_refundable_order", lambda *_: stale_order)
    second = refund(lambda_context, amount=300, idempotency_key="operation-second")
    assert second["error"]["code"] == "ORDER_CHANGED"
    assert second["error"]["retryable"] is True
    assert totals(table) == (Decimal(300), Decimal(0))

    # The agent retries with the same key; the fresh read now sends it to review.
    monkeypatch.setattr(handler, "_load_refundable_order", real_load)
    retried = refund(lambda_context, amount=300, idempotency_key="operation-second")
    assert retried["data"]["status"] == "PENDING_APPROVAL"
    assert totals(table) == (Decimal(600), Decimal(300))


def test_refunds_in_sequence_still_complete_below_the_threshold(table, lambda_context):
    assert refund(lambda_context, amount=200, idempotency_key="operation-a")["ok"] is True
    second = refund(lambda_context, amount=299.99, idempotency_key="operation-b")
    assert second["data"]["status"] == "COMPLETED"
    assert totals(table) == (Decimal("499.99"), Decimal(0))
