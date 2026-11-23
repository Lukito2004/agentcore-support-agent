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
