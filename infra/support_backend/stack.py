from aws_cdk import CfnOutput, Stack
from constructs import Construct

from support_backend.data import BusinessTables
from support_backend.identity import UserIdentity
from support_backend.tools import ReadTools, RefundTool


class SupportAgentBackendStack(Stack):
    """Business APIs the agent reaches through AgentCore Gateway, plus user identity."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tables = BusinessTables(self, "Tables")
        read_tools = ReadTools(self, "ReadTools", customers=tables.customers, orders=tables.orders)
        refund_tool = RefundTool(self, "RefundTool", orders=tables.orders, refunds=tables.refunds)
        identity = UserIdentity(self, "Identity")

        # Scripts and the AgentCore config read these instead of hardcoding names.
        outputs = {
            "CustomersTableName": tables.customers.table_name,
            "OrdersTableName": tables.orders.table_name,
            "RefundsTableName": tables.refunds.table_name,
            "ReadToolsFunctionName": read_tools.function.function_name,
            "ReadToolsFunctionArn": read_tools.function.function_arn,
            "RefundToolFunctionName": refund_tool.function.function_name,
            "RefundToolFunctionArn": refund_tool.function.function_arn,
            "UserPoolId": identity.user_pool.user_pool_id,
            "DiscoveryUrl": identity.discovery_url,
            "ChatClientId": identity.chat_client.user_pool_client_id,
            "GatewayClientId": identity.gateway_client.user_pool_client_id,
            "TokenEndpoint": identity.token_endpoint,
        }
        for name, value in outputs.items():
            CfnOutput(self, name, value=value)
