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

import refund_review


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, default=float))


def _list(table, order_id: str | None, as_json: bool) -> None:
    refunds = refund_review.pending_refunds(table, order_id)
    if as_json:
        _print({"refunds": refunds})
        return
    if not refunds:
        print("No refunds are waiting for approval.")
    for r in refunds:
        amount = f"{float(r['amount']):.2f} {r['currency']}"
        print(f"{r['refund_id']}  order {r['order_id']}  {amount}  {r['reason']}")


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

    try:
        if args.command == "subscribe":
            refund_review.subscribe(args.email)
            print("Subscribed. Open the confirmation email from AWS and confirm it.")
            return
        table = refund_review.refunds_table()
        if args.command == "list":
            _list(table, args.order, args.json)
        elif args.command == "show":
            _print(refund_review.summary(refund_review.find(table, args.refund_id)))
        else:
            _print(
                refund_review.decide(table, args.refund_id, args.command == "approve", args.note)
            )
    except refund_review.ReviewError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
