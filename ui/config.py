"""Where the chat app finds the agent and Cognito: env vars first, else the deployed stacks."""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import boto3

BACKEND_STACK = "SupportAgentBackend"
AGENT_STACK = "AgentCore-SupportAgent-default"
# CDK adds a hash to output names, so the runtime ARN is found by prefix.
RUNTIME_ARN_OUTPUT_PREFIX = "ApplicationRuntimeSupportAgentRuntimeArnOutput"


@dataclass(frozen=True)
class UiConfig:
    region: str
    runtime_arn: str
    chat_client_id: str


def stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    stack = boto3.client("cloudformation", region_name=region).describe_stacks(
        StackName=stack_name
    )["Stacks"][0]
    return {output["OutputKey"]: output["OutputValue"] for output in stack.get("Outputs", [])}


def load_config(
    env: Mapping[str, str] = os.environ,
    outputs: Callable[[str, str], dict[str, str]] = stack_outputs,
) -> UiConfig:
    region = env.get("AWS_REGION", "us-east-1")
    runtime_arn = env.get("AGENT_RUNTIME_ARN")
    if not runtime_arn:
        agent = outputs(AGENT_STACK, region)
        runtime_arn = next(v for k, v in agent.items() if k.startswith(RUNTIME_ARN_OUTPUT_PREFIX))
    client_id = env.get("COGNITO_CLIENT_ID") or outputs(BACKEND_STACK, region)["ChatClientId"]
    return UiConfig(region=region, runtime_arn=runtime_arn, chat_client_id=client_id)
