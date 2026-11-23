"""Call a deployed tool Lambda the same way AgentCore Gateway does.

Usage: uv run python scripts/invoke_tool.py get_order_status order_id=123
"""

import argparse
import base64
import json

import boto3

from stack_outputs import REGION, get_stack_outputs

TARGET_NAME = "customer-orders"


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
    parser.add_argument("--function-output", default="ReadToolsFunctionName")
    parsed = parser.parse_args()

    client_context = {"custom": {"bedrockAgentCoreToolName": f"{TARGET_NAME}___{parsed.tool}"}}
    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=get_stack_outputs()[parsed.function_output],
        Payload=json.dumps(dict(parsed.args)).encode(),
        ClientContext=base64.b64encode(json.dumps(client_context).encode()).decode(),
    )
    print(json.dumps(json.loads(response["Payload"].read()), indent=2))


if __name__ == "__main__":
    main()
