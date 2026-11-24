"""Steps of the refund review workflow, run by Step Functions (never reachable through Gateway)."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from common import dynamo
from common.dynamo import RETRY_CONFIG
from common.log import get_logger

PENDING = "PENDING_APPROVAL"
FINAL_STATUS = {"APPROVED": "COMPLETED", "REJECTED": "REJECTED", "EXPIRED": "EXPIRED"}
MAX_NOTE_CHARS = 500

log = get_logger("approval")
_serializer = TypeSerializer()


@cache
def _sns():
    return boto3.client("sns", config=RETRY_CONFIG)


def _message(refund: dict) -> str:
    refund_id = refund["refund_id"]
    return "\n".join(
        [
            f"Refund {refund_id} needs approval.",
            "",
            f"Customer: {refund['customer_id']}",
            f"Order:    {refund['order_id']}",
            f"Amount:   {refund['amount']} {refund['currency']}",
            f"Reason:   {refund['reason']}",
            f"Asked at: {refund['created_at']}",
            "",
            f"Approve: uv run python scripts/approve_refund.py approve {refund_id}",
            f'Reject:  uv run python scripts/approve_refund.py reject {refund_id} --note "why"',
            "Without a decision before the time limit, the refund is rejected automatically.",
        ]
    )


def notify(event, context) -> dict:
    """Store the workflow's callback token on the refund, then email the approver."""
    refund = event["refund"]
    try:
        dynamo.table("REFUNDS_TABLE").update_item(
            Key={"idempotency_key": refund["idempotency_key"]},
            UpdateExpression="SET approval_token = :token",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":token": event["token"], ":pending": PENDING},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        # Already decided; the workflow just times out and finalize changes nothing.
        log.warning("refund is no longer pending", extra={"fields": _ids(refund)})
        return {"notified": False}

    _sns().publish(
        TopicArn=os.environ["TOPIC_ARN"],
        Subject=f"Refund {refund['refund_id']} needs approval",
        Message=_message(refund),
    )
    log.info("approver notified", extra={"fields": _ids(refund)})
    return {"notified": True}


def _note(decision: str, details: dict | None) -> str:
    details = details or {}
    note = details.get("note") or details.get("Cause") or ""
    if not note and decision == "EXPIRED":
        note = "no decision before the time limit"
    return str(note)[:MAX_NOTE_CHARS]


def _values(**values) -> dict:
    return {f":{name}": _serializer.serialize(value) for name, value in values.items()}


def _refund_update(refund: dict, status: str, note: str) -> dict:
    return {
        "Update": {
            "TableName": os.environ["REFUNDS_TABLE"],
            "Key": {"idempotency_key": {"S": refund["idempotency_key"]}},
            "UpdateExpression": "SET #status = :status, decided_at = :at, decision_note = :note "
            "REMOVE approval_token",
            "ConditionExpression": "#status = :pending",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": _values(
                status=status,
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                note=note,
                pending=PENDING,
            ),
        }
    }


def _order_update(refund: dict, status: str) -> dict:
    # Approved: the held amount is now refunded. Otherwise it is given back to the order.
    expression = "SET pending_refund_total = pending_refund_total - :amount"
    condition = "pending_refund_total >= :amount"
    if status != "COMPLETED":
        expression += ", refunded_total = refunded_total - :amount"
        condition += " AND refunded_total >= :amount"
    return {
        "Update": {
            "TableName": os.environ["ORDERS_TABLE"],
            "Key": {"order_id": {"S": refund["order_id"]}},
            "UpdateExpression": expression,
            "ConditionExpression": condition,
            "ExpressionAttributeValues": _values(amount=Decimal(refund["amount"])),
        }
    }


def _reasons(exc: ClientError) -> list[str | None]:
    return [reason.get("Code") for reason in exc.response.get("CancellationReasons", [])]


def finalize(event, context) -> dict:
    """Apply the review's outcome once; running it again for the same refund changes nothing."""
    decision = event["decision"]
    status = FINAL_STATUS[decision]
    note = _note(decision, event.get("details"))
    refund = dynamo.get_item("REFUNDS_TABLE", {"idempotency_key": event["idempotency_key"]})
    if refund is None:
        raise LookupError("refund not found")
    if refund["status"] != PENDING:
        return {**_ids(refund), "status": refund["status"], "changed": False}

    client = dynamo.client()
    try:
        client.transact_write_items(
            TransactItems=[_refund_update(refund, status, note), _order_update(refund, status)]
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
            raise
        reasons = _reasons(exc)
        if reasons[:1] == ["ConditionalCheckFailed"]:
            # Another run decided it first.
            current = dynamo.get_item(
                "REFUNDS_TABLE", {"idempotency_key": refund["idempotency_key"]}
            )
            return {**_ids(refund), "status": current["status"], "changed": False}
        if reasons[1:2] != ["ConditionalCheckFailed"]:
            raise
        # The order no longer holds this amount (e.g. demo data was re-seeded); still decide it.
        log.warning("order totals did not include the refund", extra={"fields": _ids(refund)})
        client.transact_write_items(TransactItems=[_refund_update(refund, status, note)])

    log.info("refund reviewed", extra={"fields": {**_ids(refund), "status": status}})
    return {**_ids(refund), "status": status, "changed": True}


def _ids(refund: dict) -> dict:
    return {"refund_id": refund["refund_id"], "order_id": refund["order_id"]}
