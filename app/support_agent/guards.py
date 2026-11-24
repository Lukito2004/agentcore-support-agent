"""Deterministic checks applied to every tool call, independent of what the model decided."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Gateway prefixes tool names with the target, e.g. "customer-orders___get_customer".
TARGET_SEPARATOR = "___"
CUSTOMER_BOUND_TOOLS = frozenset({"get_customer", "get_order_status", "refund_customer"})
REFUND_TOOL = "refund_customer"


def tool_base_name(name: str) -> str:
    return name.split(TARGET_SEPARATOR, 1)[-1]


def bind_customer_id(tool_use: dict, customer_id: str) -> tuple[dict, bool]:
    """Force customer_id to the signed-in customer. Returns (tool_use, was_overridden).

    The model may be talked into asking about another customer (prompt injection); this makes
    that impossible, because the value comes from the verified sign-in token, not the model.
    """
    if tool_base_name(str(tool_use.get("name", ""))) not in CUSTOMER_BOUND_TOOLS:
        return tool_use, False
    raw_input = tool_use.get("input")
    tool_input = dict(raw_input) if isinstance(raw_input, dict) else {}
    overridden = "customer_id" in tool_input and tool_input["customer_id"] != customer_id
    tool_input["customer_id"] = customer_id
    return {**tool_use, "input": tool_input}, overridden


def to_cents(amount: object) -> int | None:
    """USD amount -> integer cents, or None if it is not a usable number (the tool rejects it)."""
    if isinstance(amount, bool) or not isinstance(amount, int | float):
        return None
    try:
        cents = (Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return int(cents) if cents.is_finite() else None


def add_amount_cents(tool_use: dict) -> dict:
    """Give refund calls an integer amount_cents so the Cedar policy compares whole numbers.

    Computed here from the model's amount and never taken from the model itself.
    """
    if tool_base_name(str(tool_use.get("name", ""))) != REFUND_TOOL:
        return tool_use
    raw_input = tool_use.get("input")
    tool_input = dict(raw_input) if isinstance(raw_input, dict) else {}
    tool_input.pop("amount_cents", None)
    cents = to_cents(tool_input.get("amount"))
    if cents is not None:
        tool_input["amount_cents"] = cents
    return {**tool_use, "input": tool_input}
