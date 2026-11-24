"""Opt-in failures for drills. Does nothing unless the Lambda has FAULT_INJECTION=enabled."""

import os
import time

from common.errors import ToolError

SLOW_ORDER = "900"  # sleeps past the Lambda timeout
FAILING_ORDER = "901"  # always fails with a retryable error
STUCK_ORDER = "902"  # always "processing", which tempts the model to poll in a loop
SLOW_SECONDS = 15


def enabled() -> bool:
    return os.environ.get("FAULT_INJECTION") == "enabled"


def inject(customer_id: str, order_id: str) -> dict | None:
    """Raise or stall for a drill order; return a fake order for the stuck one, else None."""
    if not enabled():
        return None
    if order_id == SLOW_ORDER:
        time.sleep(SLOW_SECONDS)
    if order_id == FAILING_ORDER:
        raise ToolError("BACKEND_UNAVAILABLE", "the data store did not respond", retryable=True)
    if order_id == STUCK_ORDER:
        return {
            "order_id": order_id,
            "customer_id": customer_id,
            "status": "PROCESSING",
            "status_note": "The status is being updated. Check again in a moment.",
            "refunded_total": 0,
            "pending_refund_total": 0,
        }
    return None
