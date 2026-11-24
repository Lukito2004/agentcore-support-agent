"""Deterministic checks applied to every tool call, independent of what the model decided."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from memory import MEMORY_CONTEXT_TAG

# Gateway prefixes tool names with the target, e.g. "customer-orders___get_customer".
TARGET_SEPARATOR = "___"
CUSTOMER_BOUND_TOOLS = frozenset({"get_customer", "get_order_status", "refund_customer"})
REFUND_TOOL = "refund_customer"
AMOUNT_NOT_STATED = (
    "The customer has not typed this amount. Ask them to type the exact refund amount in "
    "numbers. Never work out an amount yourself."
)

# Remembered context is added to the user's message by Memory; the customer did not type it.
_USER_CONTEXT = re.compile(rf"<{MEMORY_CONTEXT_TAG}>.*?</{MEMORY_CONTEXT_TAG}>", re.DOTALL)
# 25, 25.50, 1,000 and 1,000.00; commas are read as thousands separators.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def customer_texts(messages: list) -> list[str]:
    """What the customer typed in this conversation: no tool results, no remembered context."""
    texts = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        for block in message.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(_USER_CONTEXT.sub("", block["text"]))
    return texts


def _stated_cents(texts: list[str]) -> set[int]:
    cents = set()
    for text in texts:
        for token in _NUMBER.findall(text):
            try:
                value = (Decimal(token.replace(",", "")) * 100).quantize(Decimal(1), ROUND_HALF_UP)
            except InvalidOperation:
                continue
            cents.add(int(value))
    return cents


def amount_stated_by_customer(tool_use: dict, texts: list[str]) -> bool:
    """False for a refund whose amount the customer never typed, e.g. one the model calculated.

    Invalid amounts pass here; the refund tool rejects those itself.
    """
    if tool_base_name(str(tool_use.get("name", ""))) != REFUND_TOOL:
        return True
    raw_input = tool_use.get("input")
    cents = to_cents(raw_input.get("amount")) if isinstance(raw_input, dict) else None
    return cents is None or cents in _stated_cents(texts)
