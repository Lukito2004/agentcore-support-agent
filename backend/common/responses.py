from decimal import Decimal
from typing import Any

from common.errors import ToolError


def to_plain(value: Any) -> Any:
    """Convert DynamoDB Decimals to int/float so results serialize as normal JSON."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    return value


def ok(data: dict) -> dict:
    return {"ok": True, "data": to_plain(data)}


def error(err: ToolError) -> dict:
    return {
        "ok": False,
        "error": {"code": err.code, "message": err.message, "retryable": err.retryable},
    }
