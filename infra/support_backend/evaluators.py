from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from support_backend.functions import backend_function


class RefundArgumentsEvaluator(Construct):
    """Code-based AgentCore evaluator that re-checks every refund call in a trace."""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        # No environment and no grants: it only reads the spans it is sent.
        self.function = backend_function(
            self,
            "AgentCore evaluator: checks refund_customer arguments in traces",
            "evaluators.refund_arguments.lambda_handler",
        )
        # Only AgentCore Evaluations in this account may call it.
        self.function.add_permission(
            "AgentCoreEvaluations",
            principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            source_account=Stack.of(self).account,
        )
