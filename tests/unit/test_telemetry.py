import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import telemetry
from caller import pseudonym
from reliability import RetryTracker, tool_outcome
from validation import InvalidRequestError, validate_session_id


@pytest.fixture
def tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def test_record_adds_an_event_without_empty_values(tracer):
    test_tracer, exporter = tracer
    with test_tracer.start_as_current_span("cycle"):
        telemetry.record("tool_retry", tool="get_order_status", next_attempt=2, error_code=None)
    [span] = exporter.get_finished_spans()
    [event] = span.events
    assert event.name == "support.tool_retry"
    assert dict(event.attributes) == {"tool": "get_order_status", "next_attempt": 2}


def test_record_without_an_active_span_does_nothing():
    telemetry.record("tool_call", tool="get_customer")


def result(payload, status="success") -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"status": status, "content": [{"text": text}]}


@pytest.mark.parametrize(
    ("tool_result", "exception", "expected"),
    [
        (result({"ok": True, "data": {}}), None, ("ok", None)),
        (
            result({"ok": False, "error": {"code": "ORDER_NOT_FOUND"}}),
            None,
            ("error", "ORDER_NOT_FOUND"),
        ),
        (result("Tool Execution Denied", status="error"), None, ("error", "POLICY_DENIED")),
        (result("Lambda failed", status="error"), None, ("error", "TOOL_ERROR")),
        (None, TimeoutError("read timed out"), ("exception", "TimeoutError")),
    ],
)
def test_tool_outcome(tool_result, exception, expected):
    assert tool_outcome(tool_result, exception) == expected


def test_retry_tracker_reports_the_attempt_that_just_finished():
    tracker = RetryTracker(rng=lambda: 0.5)
    failed = result({"ok": False, "error": {"code": "X", "retryable": True}})
    order = "customer-orders___get_order_status"
    assert tracker.attempt("t1") == 1
    tracker.next_delay("t1", order, failed, None)
    assert tracker.attempt("t1") == 2


def test_pseudonym_is_stable_and_hides_the_id():
    assert pseudonym("user-123") == pseudonym("user-123")
    assert "user-123" not in pseudonym("user-123")
    assert len(pseudonym("user-123")) == 12


@pytest.mark.parametrize(
    "session_id", ["session-small-6b4bf7ef-ee6b-4157-a02b-b0bce2d62cb3", "chat-" + "a" * 32]
)
def test_valid_session_ids_pass(session_id):
    validate_session_id(session_id)


@pytest.mark.parametrize(
    "session_id",
    [
        "session-700 USD refund-fc92198e-9e08-4e30-ad1e-91d7b574a5df",  # spaces
        "short-id",
        "-starts-with-a-dash-0123456789012345678",
        "x" * 101,
        "session/" + "a" * 40,
    ],
)
def test_invalid_session_ids_are_rejected(session_id):
    with pytest.raises(InvalidRequestError, match="session ID"):
        validate_session_id(session_id)
