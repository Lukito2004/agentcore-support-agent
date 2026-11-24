"""Review refunds that wait for human approval. Runs with your own AWS credentials.

Usage:
  uv run python scripts/approve_refund.py list [--order 129] [--json]
  uv run python scripts/approve_refund.py show RF-ABC123DEF456
  uv run python scripts/approve_refund.py approve RF-ABC123DEF456 [--note "Checked the photos"]
  uv run python scripts/approve_refund.py reject RF-ABC123DEF456 --note "Outside the return window"
  uv run python scripts/approve_refund.py subscribe approver@example.com
"""

import argparse
import json
import sys
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


def _summary(refund: dict) -> dict:
    return {field: refund[field] for field in SUMMARY_FIELDS if field in refund}


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, default=float))


def _scan(table, condition) -> list[dict]:
    # An admin tool on a small table; the agent's tools never scan.
    items, kwargs = [], {"FilterExpression": condition, "ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _find(table, refund_id: str) -> dict:
    found = _scan(table, Attr("refund_id").eq(refund_id))
    if not found:
        sys.exit(f"No refund {refund_id}.")
    return found[0]


def _wait_for(table, refund_id: str, ready, seconds: int) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        refund = _find(table, refund_id)
        if ready(refund) or time.monotonic() > deadline:
            return refund
        time.sleep(2)


def list_pending(table, order_id: str | None, as_json: bool) -> None:
    condition = Attr("status").eq(PENDING)
    if order_id:
        condition &= Attr("order_id").eq(order_id)
    refunds = sorted(
        (_summary(item) for item in _scan(table, condition)), key=lambda r: r["created_at"]
    )
    if as_json:
        _print({"refunds": refunds})
        return
    if not refunds:
        print("No refunds are waiting for approval.")
    for r in refunds:
        amount = f"{float(r['amount']):.2f} {r['currency']}"
        print(f"{r['refund_id']}  order {r['order_id']}  {amount}  {r['reason']}")


def decide(table, refund_id: str, approve: bool, note: str) -> None:
    refund = _find(table, refund_id)
    if refund["status"] != PENDING:
        _print(_summary(refund))
        sys.exit(f"Refund {refund_id} is already {refund['status']}.")
    refund = _wait_for(table, refund_id, lambda r: "approval_token" in r, TOKEN_WAIT_SECONDS)
    if "approval_token" not in refund:
        sys.exit("The review has not started yet. Try again in a minute.")

    sfn = boto3.client("stepfunctions", region_name=REGION)
    try:
        if approve:
            sfn.send_task_success(
                taskToken=refund["approval_token"], output=json.dumps({"note": note})
            )
        else:
            sfn.send_task_failure(taskToken=refund["approval_token"], error="Rejected", cause=note)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("TaskTimedOut", "TaskDoesNotExist", "InvalidToken"):
            sys.exit(f"The review of {refund_id} has already ended.")
        raise

    decided = _wait_for(table, refund_id, lambda r: r["status"] != PENDING, DECISION_WAIT_SECONDS)
    _print(_summary(decided))


def subscribe(email: str) -> None:
    topic_arn = get_stack_outputs()["ApprovalTopicArn"]
    boto3.client("sns", region_name=REGION).subscribe(
        TopicArn=topic_arn, Protocol="email", Endpoint=email
    )
    print("Subscribed. Open the confirmation email from AWS and confirm it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="refunds waiting for approval")
    listing.add_argument("--order", help="only this order ID")
    listing.add_argument("--json", action="store_true")
    commands.add_parser("show", help="one refund").add_argument("refund_id")
    approve = commands.add_parser("approve", help="approve a pending refund")
    approve.add_argument("refund_id")
    approve.add_argument("--note", default="Approved")
    reject = commands.add_parser("reject", help="reject a pending refund")
    reject.add_argument("refund_id")
    reject.add_argument("--note", required=True, help="why it was rejected")
    commands.add_parser("subscribe", help="email approval requests to this address").add_argument(
        "email"
    )
    args = parser.parse_args()

    if args.command == "subscribe":
        subscribe(args.email)
        return
    table = boto3.resource("dynamodb", region_name=REGION).Table(
        get_stack_outputs()["RefundsTableName"]
    )
    if args.command == "list":
        list_pending(table, args.order, args.json)
    elif args.command == "show":
        _print(_summary(_find(table, args.refund_id)))
    else:
        decide(table, args.refund_id, args.command == "approve", args.note)


if __name__ == "__main__":
    main()
