from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
# Only code goes into the Lambda package.
ASSET_EXCLUDES = ["tool_schemas", "seed", "**/__pycache__", "**/*.pyc"]


def backend_function(
    scope: Construct, description: str, handler: str, environment: dict[str, str] | None = None
) -> lambda_.Function:
    """A Lambda from backend/ with the shared runtime settings and its own IAM role."""
    log_group = logs.LogGroup(
        scope,
        "Logs",
        retention=logs.RetentionDays.TWO_WEEKS,
        removal_policy=RemovalPolicy.DESTROY,
    )
    return lambda_.Function(
        scope,
        "Function",
        description=description,
        runtime=lambda_.Runtime.PYTHON_3_14,
        architecture=lambda_.Architecture.ARM_64,
        handler=handler,
        code=lambda_.Code.from_asset(str(BACKEND_DIR), exclude=ASSET_EXCLUDES),
        memory_size=256,
        timeout=Duration.seconds(10),
        tracing=lambda_.Tracing.ACTIVE,
        log_group=log_group,
        environment=environment or {},
    )
