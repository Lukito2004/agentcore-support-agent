"""Span events that make guard, retry and rejection decisions visible in AgentCore traces."""

from opentelemetry import trace

EVENT_PREFIX = "support."

Attribute = str | bool | int | float


def record(event: str, **attributes: Attribute | None) -> None:
    """Add an event to the active span; None values are left out. Never raises."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    values = {key: value for key, value in attributes.items() if value is not None}
    span.add_event(f"{EVENT_PREFIX}{event}", values)
