from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from constructs import Construct

BLOCKED_MESSAGE = (
    "Sorry, I can't help with that request. I can help with your orders, your account and "
    "refunds. Please don't share card numbers or passwords."
)
APPLY_POLICY_NAME = "support-agent-apply-guardrail"

# Secrets a support chat never needs: blocked when typed in, masked if they ever come out.
SECRET_TYPES = (
    "CREDIT_DEBIT_CARD_NUMBER",
    "CREDIT_DEBIT_CARD_CVV",
    "US_BANK_ACCOUNT_NUMBER",
    "US_SOCIAL_SECURITY_NUMBER",
    "PASSWORD",
    "AWS_ACCESS_KEY",
    "AWS_SECRET_KEY",
)
HARMFUL_CONTENT_TYPES = ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT")


class SupportGuardrail(Construct):
    """Bedrock Guardrail around the model, a pinned version, and the IAM policy to apply it."""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        filters = [
            # Prompt-attack detection only applies to input.
            bedrock.CfnGuardrail.ContentFilterConfigProperty(
                type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE"
            ),
            *(
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type=kind, input_strength="MEDIUM", output_strength="MEDIUM"
                )
                for kind in HARMFUL_CONTENT_TYPES
            ),
        ]
        secrets = [
            bedrock.CfnGuardrail.PiiEntityConfigProperty(
                type=kind, action="BLOCK", input_action="BLOCK", output_action="ANONYMIZE"
            )
            for kind in SECRET_TYPES
        ]

        self.guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name="support-agent-guardrail",
            description="Blocks prompt attacks, harmful content and secrets for the support agent",
            blocked_input_messaging=BLOCKED_MESSAGE,
            blocked_outputs_messaging=BLOCKED_MESSAGE,
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=filters
            ),
            sensitive_information_policy_config=(
                bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                    pii_entities_config=secrets
                )
            ),
        )
        # A pinned version; edits to the guardrail only reach the agent with a new version.
        self.version = bedrock.CfnGuardrailVersion(
            self,
            "Version",
            guardrail_identifier=self.guardrail.attr_guardrail_id,
            description="v1: prompt attack HIGH, harmful content MEDIUM, secrets blocked",
        )

        # Attached to the agent's runtime role; allows applying this guardrail and nothing else.
        self.apply_policy = iam.ManagedPolicy(
            self,
            "ApplyPolicy",
            managed_policy_name=APPLY_POLICY_NAME,
            statements=[
                iam.PolicyStatement(
                    actions=["bedrock:ApplyGuardrail"],
                    resources=[
                        self.guardrail.attr_guardrail_arn,
                        f"{self.guardrail.attr_guardrail_arn}:*",
                    ],
                )
            ],
        )
