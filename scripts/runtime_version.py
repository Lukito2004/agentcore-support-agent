"""Print the deployed agent runtime and its version, to stamp test logs with what they tested.

Usage: uv run python scripts/runtime_version.py
"""

import boto3

from stack_outputs import REGION, find_output

AGENT_STACK = "AgentCore-SupportAgent-default"


def main() -> None:
    runtime_id = find_output(AGENT_STACK, "Runtime", "IdOutput")
    runtime = boto3.client("bedrock-agentcore-control", region_name=REGION).get_agent_runtime(
        agentRuntimeId=runtime_id
    )
    print(f"runtime {runtime_id} version {runtime['agentRuntimeVersion']}")


if __name__ == "__main__":
    main()
