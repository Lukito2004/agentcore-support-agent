"""Shared entry point for tool Lambdas invoked by AgentCore Gateway."""

import logging
import time
from collections.abc import Callable

from common import responses
from common.errors import ToolError

# Gateway prefixes tool names with the target name, e.g. "customer-orders___get_customer".
TOOL_NAME_KEY = "bedrockAgentCoreToolName"
TARGET_SEPARATOR = "___"

Tool = Callable[[dict], dict]


def tool_name(context) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return str(custom.get(TOOL_NAME_KEY, "")).split(TARGET_SEPARATOR, 1)[-1]


def run_tool(tools: dict[str, Tool], event, context, log: logging.Logger) -> dict:
    """Route to the named tool and always return a structured result, never an exception."""
    tool = tool_name(context)
    started = time.perf_counter()
    try:
        if tool not in tools:
            raise ToolError("UNKNOWN_TOOL", f"unknown tool '{tool}'")
        if not isinstance(event, dict):
            raise ToolError("INVALID_ARGUMENT", "tool arguments must be a JSON object")
        result = responses.ok(tools[tool](event))
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
