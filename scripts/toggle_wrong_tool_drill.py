"""Switch the customer-orders Gateway target between its real schema and the wrong-tool drill.

The drill schema swaps the two read tools' descriptions, which tempts the model to pick the
wrong one. Deploy with `agentcore deploy` after switching, and switch back when done.

Usage: uv run python scripts/toggle_wrong_tool_drill.py on|off
"""

import json
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "agentcore" / "agentcore.json"
TARGET = "customer-orders"
SCHEMAS = {
    "off": "backend/tool_schemas/customer_orders.json",
    "on": "backend/tool_schemas/customer_orders_wrong_tool_drill.json",
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in SCHEMAS:
        sys.exit(__doc__.splitlines()[-1].strip())
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    for gateway in config["agentCoreGateways"]:
        for target in gateway["targets"]:
            if target["name"] == TARGET:
                target["lambdaFunctionArn"]["toolSchemaFile"] = SCHEMAS[sys.argv[1]]
    # Same format the AgentCore CLI writes: 2-space indent, no trailing newline.
    CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8", newline="\n")
    print(f"Wrong-tool drill {sys.argv[1]}: {TARGET} uses {SCHEMAS[sys.argv[1]]}.")
    print("Now run: agentcore deploy")


if __name__ == "__main__":
    main()
