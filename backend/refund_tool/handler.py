"""Idempotent refund tool, invoked by AgentCore Gateway as its own Lambda target.

A refund and the order's refunded_total are written in one DynamoDB transaction, so a retry
with the same idempotency key can never refund twice, and refunds can never exceed the order.
Larger refunds are saved as PENDING_APPROVAL, their amount is held, and a human review starts.
"""

import hashlib
import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

from common import dynamo, workflow
from common.dispatch import Tool, run_tool
from common.errors import ToolError, from_aws_error
from common.log import get_logger
from common.validation import CUSTOMER_ID_PATTERN, ORDER_ID_PATTERN, require_id

MAX_REFUND = Decimal("1000")
# Counted over all refunds of an order, so a big refund cannot be split into small ones.
REVIEW_THRESHOLD = Decimal("500")
COMPLETED = "COMPLETED"
PENDING = "PENDING_APPROVAL"
STATUS_NOTES = {
    PENDING: "Waiting for a review by the support team. Not refunded yet.",
    "REJECTED": "The support team did not approve this refund.",
    "EXPIRED": "The review was not completed in time, so this refund was not made.",
}
CENTS = Decimal("0.01")
REFUNDABLE_STATUSES = ("DELIVERED", "SHIPPED", "DELAYED")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
MAX_REASON_CHARS = 500

log = get_logger("refund_tool")
_serializer = TypeSerializer()


def _amount(args: dict) -> Decimal:
    value = args.get("amount")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ToolError("INVALID_ARGUMENT", "amount must be a number in USD, e.g. 25.50")
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ToolError("INVALID_ARGUMENT", "amount must be greater than zero")
    if amount.as_tuple().exponent < -2:
        raise ToolError("INVALID_ARGUMENT", "amount can have at most two decimal places")
    if amount > MAX_REFUND:
        raise ToolError(
            "REFUND_LIMIT_EXCEEDED", f"refunds above {MAX_REFUND} USD need manual review"
        )
    return amount.quantize(CENTS)


def _check_amount_cents(args: dict, amount: Decimal) -> None:
    """amount_cents is what the Gateway policy compares, so it must be exactly amount in cents."""
    value = args.get("amount_cents")
    if isinstance(value, bool) or not isinstance(value, int) or value != int(amount * 100):
        raise ToolError("INVALID_ARGUMENT", "amount_cents must equal amount in whole cents")


def _text(args: dict, field: str, max_chars: int) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ToolError("INVALID_ARGUMENT", f"{field} must be 1-{max_chars} characters")
    return value.strip()


def _idempotency_key(args: dict) -> str:
    value = args.get("idempotency_key")
    if not isinstance(value, str) or not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise ToolError("INVALID_ARGUMENT", "idempotency_key must be 8-128 of [A-Za-z0-9_-]")
    return value


def _fingerprint(customer_id: str, order_id: str, amount: Decimal) -> str:
    # The reason is free text and may be reworded on retry, so only money fields count.
    return hashlib.sha256(f"{customer_id}|{order_id}|{amount}".encode()).hexdigest()


PUBLIC_FIELDS = (
    "refund_id",
    "idempotency_key",
    "customer_id",
    "order_id",
    "amount",
    "currency",
    "reason",
    "status",
    "created_at",
)


def _public(refund: dict, *, replayed: bool) -> dict:
    result = {**{field: refund[field] for field in PUBLIC_FIELDS}, "replayed": replayed}
    if refund["status"] in STATUS_NOTES:
        result["note"] = STATUS_NOTES[refund["status"]]
    return result


def _replay(existing: dict, fingerprint: str) -> dict:
    if existing["request_fingerprint"] != fingerprint:
        raise ToolError(
            "IDEMPOTENCY_CONFLICT", "this idempotency key was already used for a different refund"
        )
    if existing["status"] == PENDING:
        # Resumes a review whose first start failed; a running one is left as it is.
        workflow.start_review(existing)
    return _public(existing, replayed=True)


def _needs_review(amount: Decimal, order: dict) -> bool:
    return Decimal(order.get("refunded_total", 0)) + amount >= REVIEW_THRESHOLD


def _load_refundable_order(order_id: str, customer_id: str, amount: Decimal) -> dict:
    order = dynamo.get_item("ORDERS_TABLE", {"order_id": order_id})
    # Same answer for "missing" and "someone else's", so order IDs cannot be probed.
    if order is None or order["customer_id"] != customer_id:
        raise ToolError("ORDER_NOT_FOUND", f"no order {order_id} for customer {customer_id}")
    if order["status"] not in REFUNDABLE_STATUSES:
        raise ToolError("NOT_REFUNDABLE", f"orders in status {order['status']} cannot be refunded")
    remaining = Decimal(order["total"]) - Decimal(order.get("refunded_total", 0))
    if amount > remaining:
        raise ToolError(
            "EXCEEDS_ORDER_TOTAL", f"only {remaining:.2f} USD of this order can still be refunded"
        )
    return order


def _write(refund: dict, order: dict) -> None:
    """Insert the refund and bump refunded_total atomically, re-checking every condition."""
    limit = Decimal(order["total"]) - refund["amount"]
    totals = "SET refunded_total = if_not_exists(refunded_total, :zero) + :amount"
    if refund["status"] == PENDING:
        # Held until the review ends; refunded_total includes it so nothing is refunded twice.
        totals += ", pending_refund_total = if_not_exists(pending_refund_total, :zero) + :amount"
    status_values = {f":s{i}": status for i, status in enumerate(REFUNDABLE_STATUSES)}
    values = {
        ":zero": Decimal(0),
        ":amount": refund["amount"],
        ":customer": refund["customer_id"],
        ":limit": limit,
        **status_values,
    }
    dynamo.client().transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": os.environ["REFUNDS_TABLE"],
                    "Item": {k: _serializer.serialize(v) for k, v in refund.items()},
                    "ConditionExpression": "attribute_not_exists(idempotency_key)",
                }
            },
            {
                "Update": {
                    "TableName": os.environ["ORDERS_TABLE"],
                    "Key": {"order_id": {"S": refund["order_id"]}},
                    "UpdateExpression": totals,
                    "ConditionExpression": "customer_id = :customer"
                    f" AND #status IN ({', '.join(status_values)})"
                    " AND (attribute_not_exists(refunded_total) OR refunded_total <= :limit)",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        k: _serializer.serialize(v) for k, v in values.items()
                    },
                }
            },
        ]
    )


def _handle_cancelled(exc: ClientError, key: str, fingerprint: str) -> dict:
    reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
    if reasons[:1] == ["ConditionalCheckFailed"]:
        # A concurrent call with the same key won the race; return its result.
        existing = dynamo.get_item("REFUNDS_TABLE", {"idempotency_key": key})
        if existing:
            return _replay(existing, fingerprint)
    if reasons[1:2] == ["ConditionalCheckFailed"]:
        raise ToolError(
            "ORDER_CHANGED", "the order changed during the refund, please retry", retryable=True
        )
    raise ToolError("BACKEND_UNAVAILABLE", "the refund could not be saved", retryable=True)


def refund_customer(args: dict) -> dict:
    customer_id = require_id(args, "customer_id", CUSTOMER_ID_PATTERN)
    order_id = require_id(args, "order_id", ORDER_ID_PATTERN)
    amount = _amount(args)
    _check_amount_cents(args, amount)
    reason = _text(args, "reason", MAX_REASON_CHARS)
    key = _idempotency_key(args)
    fingerprint = _fingerprint(customer_id, order_id, amount)

    existing = dynamo.get_item("REFUNDS_TABLE", {"idempotency_key": key})
    if existing:
        return _replay(existing, fingerprint)

    order = _load_refundable_order(order_id, customer_id, amount)
    refund = {
        "idempotency_key": key,
        "refund_id": f"RF-{uuid.uuid4().hex[:12].upper()}",
        "customer_id": customer_id,
        "order_id": order_id,
        "amount": amount,
        "currency": order.get("currency", "USD"),
        "reason": reason,
        "status": PENDING if _needs_review(amount, order) else COMPLETED,
        "request_fingerprint": fingerprint,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        _write(refund, order)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            return _handle_cancelled(exc, key, fingerprint)
        raise from_aws_error(exc) from exc
    except BotoCoreError as exc:
        # A timeout here may still have committed. Retrying with the same key is safe: it replays.
        raise from_aws_error(exc) from exc
    if refund["status"] == PENDING:
        workflow.start_review(refund)
    return _public(refund, replayed=False)


TOOLS: dict[str, Tool] = {"refund_customer": refund_customer}


def lambda_handler(event, context) -> dict:
    return run_tool(TOOLS, event, context, log)
