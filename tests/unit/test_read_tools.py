from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from common import dynamo
from read_tools import handler


def call(tool: str, args, lambda_context, target: str = "customer-orders___"):
    return handler.lambda_handler(args, lambda_context(f"{target}{tool}"))


def test_get_customer_returns_profile(seeded_tables, lambda_context):
    result = call("get_customer", {"customer_id": "CUST-1001"}, lambda_context)
    assert result["ok"] is True
    assert result["data"] == {
        "customer_id": "CUST-1001",
        "name": "Alex Morgan",
        "email": "alex.morgan@example.com",
        "tier": "gold",
        "member_since": "2021-03-14",
    }


def test_get_order_status_explains_delay(seeded_tables, lambda_context):
    result = call("get_order_status", {"order_id": "123"}, lambda_context)
    assert result["ok"] is True
    assert result["data"]["status"] == "DELAYED"
    assert result["data"]["delay_reason"] == "Carrier backlog in warehouse zone 4."
    assert result["data"]["total"] == 149.99  # Decimal converted to a plain number


def test_tool_name_without_target_prefix_is_accepted(seeded_tables, lambda_context):
    result = call("get_order_status", {"order_id": "124"}, lambda_context, target="")
    assert result["data"]["status"] == "DELIVERED"


@pytest.mark.parametrize(
    ("tool", "args"),
    [("get_customer", {"customer_id": "CUST-9999"}), ("get_order_status", {"order_id": "999"})],
)
def test_missing_records_return_not_found(seeded_tables, lambda_context, tool, args):
    result = call(tool, args, lambda_context)
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_customer", {}),
        ("get_customer", {"customer_id": "1001"}),
        ("get_customer", {"customer_id": 1001}),
        ("get_order_status", {"order_id": "ORD-123"}),
        ("get_order_status", {"order_id": "123; DROP TABLE"}),
    ],
)
def test_invalid_arguments_are_rejected(seeded_tables, lambda_context, tool, args):
    result = call(tool, args, lambda_context)
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["retryable"] is False


def test_unknown_tool_is_rejected(seeded_tables, lambda_context):
    result = call("delete_customer", {"customer_id": "CUST-1001"}, lambda_context)
    assert result["error"]["code"] == "UNKNOWN_TOOL"


def test_missing_client_context_is_rejected(seeded_tables):
    result = handler.lambda_handler({"order_id": "123"}, SimpleNamespace(client_context=None))
    assert result["error"]["code"] == "UNKNOWN_TOOL"


def test_non_object_arguments_are_rejected(seeded_tables, lambda_context):
    result = call("get_order_status", ["123"], lambda_context)
    assert result["error"]["code"] == "INVALID_ARGUMENT"


class _FailingTable:
    def __init__(self, exc: Exception):
        self.exc = exc

    def get_item(self, **_):
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (ClientError({"Error": {"Code": "ThrottlingException"}}, "GetItem"), True),
        (EndpointConnectionError(endpoint_url="https://dynamodb"), True),
        (ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetItem"), False),
    ],
)
def test_backend_failures_are_classified(monkeypatch, lambda_context, exc, retryable):
    monkeypatch.setattr(dynamo, "table", lambda _env: _FailingTable(exc))
    result = call("get_order_status", {"order_id": "123"}, lambda_context)
    assert result["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert result["error"]["retryable"] is retryable
