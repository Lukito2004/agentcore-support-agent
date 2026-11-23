from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

from support_backend.functions import backend_function


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
        self.function = backend_function(
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
        self.function = backend_function(
            self,
            "Idempotent refund tool: refund_customer",
            "refund_tool.handler.lambda_handler",
            {"ORDERS_TABLE": orders.table_name, "REFUNDS_TABLE": refunds.table_name},
        )

        # Writes only through the refund transaction; no access to customers or deletes.
        refunds.grant(self.function, "dynamodb:GetItem", "dynamodb:PutItem")
        orders.grant(self.function, "dynamodb:GetItem", "dynamodb:UpdateItem")
