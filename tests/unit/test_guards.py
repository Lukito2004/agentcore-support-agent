import pytest

from guards import bind_customer_id, tool_base_name

SIGNED_IN = "CUST-1001"


@pytest.mark.parametrize(
    "name",
    [
        "customer-orders___get_order_status",
        "customer-orders___get_customer",
        "refunds___refund_customer",
    ],
)
def test_foreign_customer_id_is_overridden(name):
    tool_use = {
        "toolUseId": "t1",
        "name": name,
        "input": {"customer_id": "CUST-1002", "order_id": "125"},
    }
    bound, overridden = bind_customer_id(tool_use, SIGNED_IN)
    assert overridden is True
    assert bound["input"] == {"customer_id": SIGNED_IN, "order_id": "125"}
    assert bound["toolUseId"] == "t1"


def test_missing_customer_id_is_filled_in_without_counting_as_override():
    tool_use = {"name": "customer-orders___get_order_status", "input": {"order_id": "123"}}
    bound, overridden = bind_customer_id(tool_use, SIGNED_IN)
    assert overridden is False
    assert bound["input"]["customer_id"] == SIGNED_IN


def test_matching_customer_id_is_not_an_override():
    tool_use = {"name": "refunds___refund_customer", "input": {"customer_id": SIGNED_IN}}
    assert bind_customer_id(tool_use, SIGNED_IN)[1] is False


def test_other_tools_are_untouched():
    tool_use = {"name": "x_amz_bedrock_agentcore_search", "input": {"query": "refund"}}
    assert bind_customer_id(tool_use, SIGNED_IN) == (tool_use, False)


def test_original_tool_use_is_not_mutated():
    original = {"name": "customer-orders___get_customer", "input": {"customer_id": "CUST-1002"}}
    bind_customer_id(original, SIGNED_IN)
    assert original["input"]["customer_id"] == "CUST-1002"


def test_non_dict_input_becomes_a_bound_object():
    bound, _ = bind_customer_id(
        {"name": "customer-orders___get_customer", "input": None}, SIGNED_IN
    )
    assert bound["input"] == {"customer_id": SIGNED_IN}


def test_tool_base_name_strips_the_target_prefix():
    assert tool_base_name("refunds___refund_customer") == "refund_customer"
    assert tool_base_name("refund_customer") == "refund_customer"
