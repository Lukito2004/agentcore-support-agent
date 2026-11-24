import os

import boto3

BACKEND_STACK = "SupportAgentBackend"
REGION = os.getenv("AWS_REGION", "us-east-1")


def get_stack_outputs(stack_name: str = BACKEND_STACK) -> dict[str, str]:
    """Return a CloudFormation stack's outputs as {OutputKey: OutputValue}."""
    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(
        StackName=stack_name
    )["Stacks"][0]
    return {output["OutputKey"]: output["OutputValue"] for output in stack.get("Outputs", [])}


def find_output(stack_name: str, *parts: str) -> str:
    """The value of the one output whose key contains every part (CDK adds hashes to keys)."""
    matches = [v for k, v in get_stack_outputs(stack_name).items() if all(p in k for p in parts)]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected one output in {stack_name} matching {parts}, found {len(matches)}"
        )
    return matches[0]


if __name__ == "__main__":
    import sys

    # Usage: uv run python scripts/stack_outputs.py STACK KEY_PART [KEY_PART ...]
    print(find_output(sys.argv[1], *sys.argv[2:]))
