import pytest

from common import faults
from read_tools import handler


def order_status(order_id: str, lambda_context) -> dict:
    args = {"customer_id": "CUST-1001", "order_id": order_id}
    return handler.lambda_handler(args, lambda_context("customer-orders___get_order_status"))


@pytest.fixture
def drills_on(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION", "enabled")
    monkeypatch.setattr(faults, "SLOW_SECONDS", 0)


@pytest.mark.parametrize("order_id", ["900", "901", "902"])
def test_drill_orders_are_ordinary_unknown_orders_when_off(seeded_tables, lambda_context, order_id):
    assert order_status(order_id, lambda_context)["error"]["code"] == "NOT_FOUND"


def test_failing_order_returns_a_retryable_error(seeded_tables, lambda_context, drills_on):
    error = order_status("901", lambda_context)["error"]
    assert error == {
        "code": "BACKEND_UNAVAILABLE",
        "message": "the data store did not respond",
        "retryable": True,
    }


def test_stuck_order_stays_processing(seeded_tables, lambda_context, drills_on):
    data = order_status("902", lambda_context)["data"]
    assert data["status"] == "PROCESSING"
    assert data["customer_id"] == "CUST-1001"


def test_slow_order_sleeps_before_answering(seeded_tables, lambda_context, drills_on, monkeypatch):
    slept = []
    monkeypatch.setattr(faults.time, "sleep", slept.append)
    order_status("900", lambda_context)
    assert slept == [faults.SLOW_SECONDS]


def test_real_orders_are_untouched_when_on(seeded_tables, lambda_context, drills_on):
    assert order_status("123", lambda_context)["data"]["status"] == "DELAYED"


@pytest.mark.parametrize("value", ["", "true", "ENABLED", "1"])
def test_only_the_exact_flag_turns_faults_on(monkeypatch, value):
    monkeypatch.setenv("FAULT_INJECTION", value)
    assert faults.enabled() is False


def test_crash_order_fails_the_lambda_itself(seeded_tables, lambda_context, drills_on):
    with pytest.raises(RuntimeError, match="drill"):
        order_status("903", lambda_context)


def test_crash_order_is_an_ordinary_unknown_order_when_off(seeded_tables, lambda_context):
    assert order_status("903", lambda_context)["error"]["code"] == "NOT_FOUND"
