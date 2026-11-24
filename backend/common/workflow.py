"""Starts the human review of a refund (a Step Functions workflow)."""

import json
import os
from decimal import Decimal
from functools import cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from common.dynamo import RETRY_CONFIG
from common.errors import ToolError

REVIEW_FIELDS = (
    "refund_id",
    "idempotency_key",
    "customer_id",
    "order_id",
    "currency",
    "reason",
    "created_at",
)


@cache
def client():
    return boto3.client("stepfunctions", config=RETRY_CONFIG)


def review_input(refund: dict) -> str:
    """The same refund always gives the same input, so a repeated start is recognized."""
    data = {field: refund[field] for field in REVIEW_FIELDS}
    data["amount"] = f"{Decimal(refund['amount']):.2f}"
    return json.dumps(data, sort_keys=True)


def start_review(refund: dict) -> None:
    """Start the review once per refund; the execution is named after the refund ID."""
    try:
        client().start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"],
            name=refund["refund_id"],
            input=review_input(refund),
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ExecutionAlreadyExists":
            return
        raise _review_unavailable() from exc
    except BotoCoreError as exc:
        raise _review_unavailable() from exc


def _review_unavailable() -> ToolError:
    # The refund is saved as pending; a retry with the same key replays it and starts the review.
    return ToolError(
        "BACKEND_UNAVAILABLE",
        "the refund is saved but its review could not be requested, please retry",
        retryable=True,
    )
