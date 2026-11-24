import json
from pathlib import Path

import pytest

SCHEMAS = Path(__file__).resolve().parents[2] / "backend" / "tool_schemas"


def load(name: str) -> dict[str, dict]:
    return {tool["name"]: tool for tool in json.loads((SCHEMAS / name).read_text("utf-8"))}


def test_each_read_tool_describes_its_own_job():
    # Models pick tools from their descriptions; a swapped description sends them astray.
    tools = load("customer_orders.json")
    assert "delayed" in tools["get_order_status"]["description"]
    assert "account" in tools["get_customer"]["description"]
    assert "order" not in tools["get_customer"]["description"].lower()


def test_the_drill_schema_only_swaps_the_descriptions():
    real, drill = load("customer_orders.json"), load("customer_orders_wrong_tool_drill.json")
    assert real.keys() == drill.keys()
    for name in real:
        assert drill[name]["inputSchema"] == real[name]["inputSchema"]
    assert drill["get_customer"]["description"] == real["get_order_status"]["description"]
    assert drill["get_order_status"]["description"] == real["get_customer"]["description"]


@pytest.mark.parametrize("name", ["customer_orders.json", "refunds.json"])
def test_the_deployed_schemas_are_the_real_ones(name):
    config = json.loads((SCHEMAS.parents[1] / "agentcore" / "agentcore.json").read_text("utf-8"))
    files = [
        target["lambdaFunctionArn"]["toolSchemaFile"]
        for gateway in config["agentCoreGateways"]
        for target in gateway["targets"]
    ]
    # Guards against committing agentcore.json with the wrong-tool drill switched on.
    assert f"backend/tool_schemas/{name}" in files
