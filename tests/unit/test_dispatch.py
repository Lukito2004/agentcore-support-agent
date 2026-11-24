import json
import logging
from types import SimpleNamespace

from common.dispatch import run_tool
from common.errors import ToolError
from common.log import JsonFormatter


class Lines(logging.Handler):
    """Collects formatted log lines."""

    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


def logger():
    log = logging.getLogger("test_dispatch")
    log.handlers = [handler := Lines()]
    log.setLevel(logging.INFO)
    log.propagate = False
    return log, handler


def context(tool: str = "target___tool"):
    return SimpleNamespace(
        aws_request_id="req-1",
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool}),
    )


def test_an_unexpected_error_becomes_a_structured_internal_error():
    def broken(_args):
        return {}["missing"]

    log, lines = logger()
    result = run_tool({"tool": broken}, {}, context(), log)
    assert result == {
        "ok": False,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "the tool failed unexpectedly",
            "retryable": False,
        },
    }
    [failure, finished] = lines.lines
    assert failure["level"] == "ERROR"
    assert "KeyError" in failure["exception"]
    assert finished["error_code"] == "INTERNAL_ERROR"


def test_expected_errors_keep_their_code_and_log_no_stack_trace():
    def not_found(_args):
        raise ToolError("ORDER_NOT_FOUND", "no such order")

    log, lines = logger()
    result = run_tool({"tool": not_found}, {}, context(), log)
    assert result["error"]["code"] == "ORDER_NOT_FOUND"
    assert len(lines.lines) == 1
    assert "exception" not in lines.lines[0]


def test_success_is_wrapped_and_logged_once():
    log, lines = logger()
    result = run_tool({"tool": lambda args: {"echo": args["x"]}}, {"x": 1}, context(), log)
    assert result == {"ok": True, "data": {"echo": 1}}
    assert lines.lines[0]["outcome"] == "ok"
