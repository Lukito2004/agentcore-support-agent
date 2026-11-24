"""Read-only business tools, invoked by AgentCore Gateway as a Lambda target."""

from common import dynamo
from common.dispatch import Tool, run_tool
from common.errors import ToolError
from common.log import get_logger
from common.validation import CUSTOMER_ID_PATTERN, ORDER_ID_PATTERN, require_id

ORDER_FIELDS = (
    "order_id",
    "customer_id",
    "status",
    "items",
    "total",
    "refunded_total",
    "currency",
    "carrier",
    "tracking_number",
    "estimated_delivery",
    "delay_reason",
    "updated_at",
)

log = get_logger("read_tools")


def get_customer(args: dict) -> dict:
    customer_id = require_id(args, "customer_id", CUSTOMER_ID_PATTERN)
    item = dynamo.get_item("CUSTOMERS_TABLE", {"customer_id": customer_id})
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
    customer_id = require_id(args, "customer_id", CUSTOMER_ID_PATTERN)
    order_id = require_id(args, "order_id", ORDER_ID_PATTERN)
    item = dynamo.get_item("ORDERS_TABLE", {"order_id": order_id})
    # Same answer for "missing" and "someone else's", so order IDs cannot be probed.
    if item is None or item["customer_id"] != customer_id:
        raise ToolError("NOT_FOUND", f"no order {order_id} for customer {customer_id}")
    return {field: item[field] for field in ORDER_FIELDS if field in item}


TOOLS: dict[str, Tool] = {
    "get_customer": get_customer,
    "get_order_status": get_order_status,
}


def lambda_handler(event, context) -> dict:
    return run_tool(TOOLS, event, context, log)
