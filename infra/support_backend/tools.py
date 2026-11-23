from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
# Only code goes into the Lambda package.
ASSET_EXCLUDES = ["tool_schemas", "seed", "**/__pycache__", "**/*.pyc"]


def _tool_function(
    scope: Construct, description: str, handler: str, environment: dict[str, str]
) -> lambda_.Function:
    """A tool Lambda with the shared runtime settings; each one gets its own IAM role."""
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
        environment=environment,
    )


class ReadTools(Construct):
    """Lambda serving get_customer and get_order_status, with read-only table access."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        customers: dynamodb.ITableV2,
        orders: dynamodb.ITableV2,
    ) -> None:
        super().__init__(scope, construct_id)
        self.function = _tool_function(
            self,
            "Read-only support tools: get_customer, get_order_status",
            "read_tools.handler.lambda_handler",
            {"CUSTOMERS_TABLE": customers.table_name, "ORDERS_TABLE": orders.table_name},
        )

        # Least privilege: only the read calls the tools make (no Scan), on these two tables.
        customers.grant(self.function, "dynamodb:GetItem")
        orders.grant(self.function, "dynamodb:GetItem", "dynamodb:Query")


class RefundTool(Construct):
    """Lambda serving refund_customer; the only code allowed to write refunds."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        orders: dynamodb.ITableV2,
        refunds: dynamodb.ITableV2,
    ) -> None:
        super().__init__(scope, construct_id)
        self.function = _tool_function(
            self,
            "Idempotent refund tool: refund_customer",
            "refund_tool.handler.lambda_handler",
            {"ORDERS_TABLE": orders.table_name, "REFUNDS_TABLE": refunds.table_name},
        )

        # Writes only through the refund transaction; no access to customers or deletes.
        refunds.grant(self.function, "dynamodb:GetItem", "dynamodb:PutItem")
        orders.grant(self.function, "dynamodb:GetItem", "dynamodb:UpdateItem")
