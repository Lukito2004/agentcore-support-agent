"""Deterministic checks applied to every tool call, independent of what the model decided."""

# Gateway prefixes tool names with the target, e.g. "customer-orders___get_customer".
TARGET_SEPARATOR = "___"
CUSTOMER_BOUND_TOOLS = frozenset({"get_customer", "get_order_status", "refund_customer"})


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
