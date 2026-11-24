"""Call a deployed tool Lambda the same way AgentCore Gateway does.

Usage:
  uv run python scripts/invoke_tool.py get_order_status customer_id=CUST-1001 order_id=123
  uv run python scripts/invoke_tool.py --target refunds refund_customer customer_id=CUST-1001
      order_id=124 amount=10 reason=Damaged idempotency_key=operation-123
"""

import argparse
import base64
import json

import boto3

from stack_outputs import REGION, get_stack_outputs

# Gateway target name -> stack output holding that target's Lambda name.
TARGETS = {
    "customer-orders": "ReadToolsFunctionName",
    "refunds": "RefundToolFunctionName",
}


def _parse_arg(pair: str) -> tuple[str, object]:
    key, sep, raw = pair.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected key=value, got '{pair}'")
    try:
        value = json.loads(raw)  # numbers, booleans, null
    except json.JSONDecodeError:
        value = raw
    # IDs like "123" must stay strings.
    return key, raw if isinstance(value, int) and key.endswith("_id") else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tool", help="tool name, e.g. get_order_status")
    parser.add_argument("args", nargs="*", type=_parse_arg, help="arguments as key=value")
    parser.add_argument("--target", choices=TARGETS, default="customer-orders")
    parsed = parser.parse_args()

    client_context = {"custom": {"bedrockAgentCoreToolName": f"{parsed.target}___{parsed.tool}"}}
    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=get_stack_outputs()[TARGETS[parsed.target]],
        Payload=json.dumps(dict(parsed.args)).encode(),
        ClientContext=base64.b64encode(json.dumps(client_context).encode()).decode(),
    )
    print(json.dumps(json.loads(response["Payload"].read()), indent=2))


if __name__ == "__main__":
    main()
