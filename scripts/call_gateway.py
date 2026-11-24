"""Call an AgentCore Gateway tool directly with the agent's machine identity, skipping the LLM.

Simulates a compromised or manipulated agent: whatever it asks for, the Gateway policy decides.
The client secret is read from Cognito at run time and never printed or saved.

Usage:
  uv run python scripts/call_gateway.py tools/list
  uv run python scripts/call_gateway.py refunds___refund_customer customer_id=CUST-1001
      order_id=123 amount=5000 amount_cents=500000 reason=Test idempotency_key=direct-5000
"""

import argparse
import json
import urllib.parse
import urllib.request

import boto3

from invoke_tool import _parse_arg
from stack_outputs import REGION, get_stack_outputs

GATEWAY_NAME_PART = "support-tools"
SCOPE = "support-gateway/tools.invoke"


def _gateway_url() -> str:
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    for gateway in control.list_gateways()["items"]:
        if GATEWAY_NAME_PART in gateway["name"]:
            return control.get_gateway(gatewayIdentifier=gateway["gatewayId"])["gatewayUrl"]
    raise SystemExit("support-tools gateway not found")


def _machine_token(outputs: dict[str, str]) -> str:
    client = boto3.client("cognito-idp", region_name=REGION).describe_user_pool_client(
        UserPoolId=outputs["UserPoolId"], ClientId=outputs["GatewayClientId"]
    )["UserPoolClient"]
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client["ClientId"],
            "client_secret": client["ClientSecret"],
            "scope": SCOPE,
        }
    ).encode()
    request = urllib.request.Request(outputs["TokenEndpoint"], data=body, method="POST")  # noqa: S310
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.loads(response.read())["access_token"]


def _rpc(url: str, token: str, method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": "direct-call", "method": method, "params": params}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")  # noqa: S310
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        text = response.read().decode()
    # Streamable HTTP may answer as server-sent events; the JSON-RPC message is the data line.
    data_lines = [line[6:] for line in text.splitlines() if line.startswith("data: ")]
    return json.loads(data_lines[-1] if data_lines else text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "tool", help="tools/list, or a full tool name like refunds___refund_customer"
    )
    parser.add_argument("args", nargs="*", type=_parse_arg, help="arguments as key=value")
    parsed = parser.parse_args()

    token = _machine_token(get_stack_outputs())
    if parsed.tool == "tools/list":
        result = _rpc(_gateway_url(), token, "tools/list", {})
    else:
        params = {"name": parsed.tool, "arguments": dict(parsed.args)}
        result = _rpc(_gateway_url(), token, "tools/call", params)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
