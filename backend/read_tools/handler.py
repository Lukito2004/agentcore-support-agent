"""Read-only business tools, invoked by AgentCore Gateway as a Lambda target."""

import os
import re
import time
from collections.abc import Callable
from functools import cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from common import responses
from common.errors import ToolError, from_aws_error
from common.log import get_logger

CUSTOMER_ID_PATTERN = re.compile(r"^CUST-\d{3,10}$")
ORDER_ID_PATTERN = re.compile(r"^\d{1,12}$")

# Gateway prefixes tool names with the target name, e.g. "customer-orders___get_customer".
TOOL_NAME_KEY = "bedrockAgentCoreToolName"
TARGET_SEPARATOR = "___"

log = get_logger("read_tools")


@cache
def _table(env_var: str):
    return boto3.resource("dynamodb").Table(os.environ[env_var])


def _require_id(args: dict, field: str, pattern: re.Pattern) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise ToolError("INVALID_ARGUMENT", f"{field} is missing or has an invalid format")
    return value.strip()


def _get_item(env_var: str, key: dict) -> dict | None:
    try:
        return _table(env_var).get_item(Key=key).get("Item")
    except (ClientError, BotoCoreError) as exc:
        raise from_aws_error(exc) from exc


def get_customer(args: dict) -> dict:
    customer_id = _require_id(args, "customer_id", CUSTOMER_ID_PATTERN)
    item = _get_item("CUSTOMERS_TABLE", {"customer_id": customer_id})
    if item is None:
        raise ToolError("NOT_FOUND", f"no customer with ID {customer_id}")
    return {
        "customer_id": item["customer_id"],
        "name": item["name"],
        "email": item["email"],
        "tier": item["tier"],
        "member_since": item["member_since"],
    }


def get_order_status(args: dict) -> dict:
    order_id = _require_id(args, "order_id", ORDER_ID_PATTERN)
    item = _get_item("ORDERS_TABLE", {"order_id": order_id})
    if item is None:
        raise ToolError("NOT_FOUND", f"no order with ID {order_id}")
    fields = (
        "order_id",
        "customer_id",
        "status",
        "items",
        "total",
        "currency",
        "carrier",
        "tracking_number",
        "estimated_delivery",
        "delay_reason",
        "updated_at",
    )
    return {field: item[field] for field in fields if field in item}


TOOLS: dict[str, Callable[[dict], dict]] = {
    "get_customer": get_customer,
    "get_order_status": get_order_status,
}


def _tool_name(context) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return str(custom.get(TOOL_NAME_KEY, "")).split(TARGET_SEPARATOR, 1)[-1]


def lambda_handler(event, context) -> dict:
    tool = _tool_name(context)
    started = time.perf_counter()
    try:
        if tool not in TOOLS:
            raise ToolError("UNKNOWN_TOOL", f"unknown tool '{tool}'")
        if not isinstance(event, dict):
            raise ToolError("INVALID_ARGUMENT", "tool arguments must be a JSON object")
        result = responses.ok(TOOLS[tool](event))
        outcome, code = "ok", None
    except ToolError as err:
        result = responses.error(err)
        outcome, code = "error", err.code

    log.info(
        "tool call finished",
        extra={
            "fields": {
                "tool": tool,
                "outcome": outcome,
                "error_code": code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "request_id": getattr(context, "aws_request_id", None),
            }
        },
    )
    return result
