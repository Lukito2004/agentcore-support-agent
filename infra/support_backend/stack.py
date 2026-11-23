from aws_cdk import CfnOutput, Stack
from constructs import Construct

from support_backend.data import BusinessTables
from support_backend.tools import ReadTools, RefundTool


class SupportAgentBackendStack(Stack):
    """Business APIs the agent reaches through AgentCore Gateway."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tables = BusinessTables(self, "Tables")
        read_tools = ReadTools(self, "ReadTools", customers=tables.customers, orders=tables.orders)
        refund_tool = RefundTool(self, "RefundTool", orders=tables.orders, refunds=tables.refunds)

        # Scripts and the Gateway setup read these instead of hardcoding names.
        CfnOutput(self, "CustomersTableName", value=tables.customers.table_name)
        CfnOutput(self, "OrdersTableName", value=tables.orders.table_name)
        CfnOutput(self, "RefundsTableName", value=tables.refunds.table_name)
        CfnOutput(self, "ReadToolsFunctionName", value=read_tools.function.function_name)
        CfnOutput(self, "ReadToolsFunctionArn", value=read_tools.function.function_arn)
        CfnOutput(self, "RefundToolFunctionName", value=refund_tool.function.function_name)
        CfnOutput(self, "RefundToolFunctionArn", value=refund_tool.function.function_arn)
