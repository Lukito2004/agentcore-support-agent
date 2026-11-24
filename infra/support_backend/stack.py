from aws_cdk import CfnOutput, Stack
from constructs import Construct

from support_backend.approval import RefundApproval
from support_backend.data import BusinessTables
from support_backend.guardrail import SupportGuardrail
from support_backend.identity import UserIdentity
from support_backend.tools import ReadTools, RefundTool


class SupportAgentBackendStack(Stack):
    """Business APIs the agent reaches through AgentCore Gateway, user identity and guardrail."""

    DEFAULT_REVIEW_TIMEOUT_MINUTES = 15

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tables = BusinessTables(self, "Tables")
        # Off unless deployed with: cdk deploy -c fault_injection=enabled
        fault_injection = self.node.try_get_context("fault_injection") == "enabled"
        read_tools = ReadTools(
            self,
            "ReadTools",
            customers=tables.customers,
            orders=tables.orders,
            fault_injection=fault_injection,
        )
        approval = RefundApproval(
            self,
            "RefundApproval",
            orders=tables.orders,
            refunds=tables.refunds,
            timeout_minutes=int(
                self.node.try_get_context("review_timeout_minutes")
                or self.DEFAULT_REVIEW_TIMEOUT_MINUTES
            ),
        )
        refund_tool = RefundTool(
            self,
            "RefundTool",
            orders=tables.orders,
            refunds=tables.refunds,
            review=approval.state_machine,
        )
        identity = UserIdentity(self, "Identity")
        guardrail = SupportGuardrail(self, "Guardrail")

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
            "GuardrailId": guardrail.guardrail.attr_guardrail_id,
            "GuardrailVersion": guardrail.version.attr_version,
            "ApplyGuardrailPolicyArn": guardrail.apply_policy.managed_policy_arn,
            "ApprovalStateMachineArn": approval.state_machine.state_machine_arn,
            "ApprovalTopicArn": approval.topic.topic_arn,
            "ApprovalTimeoutMinutes": str(approval.timeout_minutes),
            "FaultInjection": "enabled" if fault_injection else "disabled",
        }
        for name, value in outputs.items():
            CfnOutput(self, name, value=value)
