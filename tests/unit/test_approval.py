from decimal import Decimal

import pytest

from approval import handler
from guards import to_cents
from refund_tool import handler as refund_handler

KEY = "operation-700"
CALLBACK = "callback-from-step-functions"


@pytest.fixture
def pending_refund(table, lambda_context):
    """A 700 USD refund on order 125 (CUST-1002, 1299.00 USD) waiting for review."""
    args = {
        "customer_id": "CUST-1002",
        "order_id": "125",
        "amount": 700,
        "amount_cents": to_cents(700),
        "reason": "Screen flickers",
        "idempotency_key": KEY,
    }
    result = refund_handler.lambda_handler(args, lambda_context("refunds___refund_customer"))
    assert result["data"]["status"] == "PENDING_APPROVAL"
    return table("REFUNDS_TABLE").get_item(Key={"idempotency_key": KEY})["Item"]


def stored(table) -> dict:
    return table("REFUNDS_TABLE").get_item(Key={"idempotency_key": KEY})["Item"]


def totals(table) -> tuple[Decimal, Decimal]:
    order = table("ORDERS_TABLE").get_item(Key={"order_id": "125"})["Item"]
    return order["refunded_total"], order["pending_refund_total"]


def finalize(decision: str, details: dict | None = None) -> dict:
    return handler.finalize(
        {"idempotency_key": KEY, "decision": decision, "details": details}, None
    )


def test_approval_completes_the_refund(table, pending_refund):
    result = finalize("APPROVED", {"note": "Checked the photos"})
    assert result["status"] == "COMPLETED"
    assert result["changed"] is True
    refund = stored(table)
    assert refund["status"] == "COMPLETED"
    assert refund["decision_note"] == "Checked the photos"
    assert totals(table) == (Decimal(700), Decimal(0))


@pytest.mark.parametrize(
    ("decision", "details", "note"),
    [
        ("REJECTED", {"Error": "Rejected", "Cause": "Outside the return window"}, "Outside"),
        ("EXPIRED", {"Error": "States.Timeout"}, "no decision before the time limit"),
    ],
)
def test_rejection_and_expiry_give_the_held_amount_back(
    table, pending_refund, decision, details, note
):
    result = finalize(decision, details)
    assert result["status"] == decision
    refund = stored(table)
    assert refund["status"] == decision
    assert note in refund["decision_note"]
    assert "approval_token" not in refund
    assert totals(table) == (Decimal(0), Decimal(0))


def test_finalize_twice_changes_nothing_the_second_time(table, pending_refund):
    finalize("APPROVED", {"note": "ok"})
    again = finalize("REJECTED", {"Cause": "late click"})
    assert again == {
        "refund_id": pending_refund["refund_id"],
        "order_id": "125",
        "status": "COMPLETED",
        "changed": False,
    }
    assert totals(table) == (Decimal(700), Decimal(0))


def test_finalize_still_decides_when_the_order_was_reset(table, pending_refund):
    # Re-seeding the demo data drops the held amount from the order.
    table("ORDERS_TABLE").update_item(
        Key={"order_id": "125"}, UpdateExpression="REMOVE refunded_total, pending_refund_total"
    )
    assert finalize("REJECTED", {"Cause": "no"})["status"] == "REJECTED"
    assert stored(table)["status"] == "REJECTED"


class FakeSns:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)


@pytest.fixture
def sns(monkeypatch):
    fake = FakeSns()
    monkeypatch.setenv("TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:approvals")
    monkeypatch.setattr(handler, "_sns", lambda: fake)
    return fake


def test_notify_stores_the_token_and_emails_the_approver(table, pending_refund, sns):
    assert handler.notify({"token": CALLBACK, "refund": pending_refund}, None) == {"notified": True}
    assert stored(table)["approval_token"] == CALLBACK
    [message] = sns.messages
    assert pending_refund["refund_id"] in message["Subject"]
    assert "approve_refund.py approve" in message["Message"]
    assert CALLBACK not in message["Message"]


def test_notify_skips_a_refund_that_is_already_decided(table, pending_refund, sns):
    finalize("APPROVED", {"note": "ok"})
    assert handler.notify({"token": CALLBACK, "refund": pending_refund}, None) == {
        "notified": False
    }
    assert "approval_token" not in stored(table)
    assert sns.messages == []
