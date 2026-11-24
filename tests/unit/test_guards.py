import pytest

from guards import (
    add_amount_cents,
    amount_stated_by_customer,
    bind_customer_id,
    customer_texts,
    to_cents,
    tool_base_name,
)

REFUND = "refunds___refund_customer"

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


@pytest.mark.parametrize(
    ("amount", "cents"),
    [(10, 1000), (25.5, 2550), (0.1 + 0.2, 30), (149.99, 14999), (1000, 100000), (1000.01, 100001)],
)
def test_amounts_convert_to_exact_cents(amount, cents):
    assert to_cents(amount) == cents


@pytest.mark.parametrize("amount", ["10", None, True, float("nan"), float("inf"), [10]])
def test_unusable_amounts_give_no_cents(amount):
    assert to_cents(amount) is None


def test_refund_calls_get_amount_cents_from_the_amount():
    bound = add_amount_cents({"name": REFUND, "input": {"amount": 5000}})
    assert bound["input"]["amount_cents"] == 500000


def test_model_supplied_amount_cents_is_replaced():
    # A manipulated model cannot pass the policy with a small amount_cents and a big amount.
    bound = add_amount_cents({"name": REFUND, "input": {"amount": 5000, "amount_cents": 100}})
    assert bound["input"]["amount_cents"] == 500000


def test_invalid_amount_leaves_amount_cents_out():
    bound = add_amount_cents({"name": REFUND, "input": {"amount": "lots", "amount_cents": 100}})
    assert "amount_cents" not in bound["input"]


def test_other_tools_get_no_amount_cents():
    tool_use = {"name": "customer-orders___get_order_status", "input": {"order_id": "123"}}
    assert add_amount_cents(tool_use) == tool_use


# The refund amount must come from the customer


def user(*texts: str) -> dict:
    return {"role": "user", "content": [{"text": text} for text in texts]}


def refund_of(amount) -> dict:
    return {"name": REFUND, "input": {"order_id": "124", "amount": amount}}


def test_customer_texts_skip_tool_results_assistant_text_and_remembered_context():
    messages = [
        user("<user_context>Prefers refunds of 20 USD</user_context>", "Refund order 124"),
        {"role": "assistant", "content": [{"text": "The order total is 25 USD."}]},
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "total 25"}]}}]},
    ]
    assert customer_texts(messages) == ["", "Refund order 124"]


@pytest.mark.parametrize(
    ("typed", "amount"),
    [
        ("Please refund 700 USD for order 129", 700),
        ("Refund $25.50, the mug was chipped", 25.5),
        ("I want 1,000 USD back", 1000),
        ("Refund 25 dollars", 25.0),
        ("refund 5", 5),
    ],
)
def test_amounts_the_customer_typed_are_allowed(typed, amount):
    assert amount_stated_by_customer(refund_of(amount), customer_texts([user(typed)])) is True


@pytest.mark.parametrize(
    ("typed", "amount"),
    [
        # The failure found in the drill: the model refunded 25 - 5 = 20.
        ("Refund minus 5 dollars for order 124, the mug was chipped.", 20),
        ("Refund the full amount for order 124", 25),
        ("Refund half of order 129", 449.5),
        ("Refund twenty dollars", 20),
    ],
)
def test_amounts_the_model_worked_out_are_blocked(typed, amount):
    assert amount_stated_by_customer(refund_of(amount), customer_texts([user(typed)])) is False


def test_an_amount_from_an_earlier_turn_counts():
    texts = customer_texts([user("Refund order 124 please"), user("Make it 12.50")])
    assert amount_stated_by_customer(refund_of(12.5), texts) is True


def test_amounts_only_in_tool_results_or_memory_are_blocked():
    messages = [
        user("<user_context>Last refund was 20 USD</user_context>", "Refund order 124"),
        {"role": "user", "content": [{"toolResult": {"content": [{"text": "total 25"}]}}]},
    ]
    texts = customer_texts(messages)
    assert amount_stated_by_customer(refund_of(20), texts) is False
    assert amount_stated_by_customer(refund_of(25), texts) is False


def test_other_tools_and_invalid_amounts_are_not_checked_here():
    order = {"name": "customer-orders___get_order_status", "input": {"order_id": "124"}}
    assert amount_stated_by_customer(order, []) is True
    # The refund tool itself rejects amounts that are not numbers.
    assert amount_stated_by_customer(refund_of("twenty"), []) is True
