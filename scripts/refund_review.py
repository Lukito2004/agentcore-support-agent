"""Refund review logic shared by scripts/approve_refund.py and the staff app. Uses your AWS role."""

import json
import time

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from stack_outputs import REGION, get_stack_outputs

PENDING = "PENDING_APPROVAL"
SUMMARY_FIELDS = (
    "refund_id",
    "customer_id",
    "order_id",
    "amount",
    "currency",
    "reason",
    "status",
    "created_at",
    "decided_at",
    "decision_note",
)
# The workflow stores its callback token a moment after the refund is created.
TOKEN_WAIT_SECONDS = 20
DECISION_WAIT_SECONDS = 30
ENDED_REVIEW_CODES = ("TaskTimedOut", "TaskDoesNotExist", "InvalidToken")


class ReviewError(Exception):
    """A review action that cannot be done; the message is safe to show."""


def refunds_table():
    return boto3.resource("dynamodb", region_name=REGION).Table(
        get_stack_outputs()["RefundsTableName"]
    )


def summary(refund: dict) -> dict:
    return {field: refund[field] for field in SUMMARY_FIELDS if field in refund}


def _scan(table, condition) -> list[dict]:
    # A staff tool on a small table; the agent's tools never scan.
    items, kwargs = [], {"FilterExpression": condition, "ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def find(table, refund_id: str) -> dict:
    found = _scan(table, Attr("refund_id").eq(refund_id))
    if not found:
        raise ReviewError(f"No refund {refund_id}.")
    return found[0]


def pending_refunds(table, order_id: str | None = None) -> list[dict]:
    """Refunds waiting for review, oldest first."""
    condition = Attr("status").eq(PENDING)
    if order_id:
        condition &= Attr("order_id").eq(order_id)
    return sorted(
        (summary(item) for item in _scan(table, condition)), key=lambda r: r["created_at"]
    )


def _wait_for(table, refund_id: str, ready, seconds: int) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        refund = find(table, refund_id)
        if ready(refund) or time.monotonic() > deadline:
            return refund
        time.sleep(2)


def decide(table, refund_id: str, approve: bool, note: str) -> dict:
    """Send the decision to the waiting workflow, then return the refund once it is applied."""
    note = note.strip()
    if not approve and not note:
        raise ReviewError("Add a note saying why the refund is rejected.")
    refund = find(table, refund_id)
    if refund["status"] != PENDING:
        raise ReviewError(f"Refund {refund_id} is already {refund['status']}.")
    refund = _wait_for(table, refund_id, lambda r: "approval_token" in r, TOKEN_WAIT_SECONDS)
    if "approval_token" not in refund:
        raise ReviewError("The review has not started yet. Try again in a minute.")

    sfn = boto3.client("stepfunctions", region_name=REGION)
    try:
        if approve:
            sfn.send_task_success(
                taskToken=refund["approval_token"], output=json.dumps({"note": note or "Approved"})
            )
        else:
            sfn.send_task_failure(taskToken=refund["approval_token"], error="Rejected", cause=note)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ENDED_REVIEW_CODES:
            raise ReviewError(f"The review of {refund_id} has already ended.") from exc
        raise

    decided = _wait_for(table, refund_id, lambda r: r["status"] != PENDING, DECISION_WAIT_SECONDS)
    return summary(decided)


def subscribe(email: str) -> None:
    boto3.client("sns", region_name=REGION).subscribe(
        TopicArn=get_stack_outputs()["ApprovalTopicArn"], Protocol="email", Endpoint=email
    )
