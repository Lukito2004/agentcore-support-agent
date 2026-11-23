from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from support_backend.functions import backend_function

GATEWAY_SCOPE = "tools.invoke"
GATEWAY_RESOURCE_SERVER = "support-gateway"


class UserIdentity(Construct):
    """Cognito user pool: who may call the agent, and how the agent proves itself to Gateway."""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            # Accounts are provisioned by an admin and linked to an existing customer record.
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=False)
            ),
            custom_attributes={
                "customer_id": cognito.StringAttribute(min_len=8, max_len=20, mutable=False)
            },
            password_policy=cognito.PasswordPolicy(
                min_length=12, require_lowercase=True, require_uppercase=True, require_digits=True
            ),
            account_recovery=cognito.AccountRecovery.NONE,
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        pre_token = backend_function(
            Construct(self, "PreToken"),
            "Adds the customer_id claim to Cognito tokens",
            "identity.pre_token.handler",
        )
        self.user_pool.add_trigger(
            cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG,
            pre_token,
            cognito.LambdaVersion.V2_0,
        )

        # Public client for the chat UI and scripts: no secret, cannot edit any attribute.
        self.chat_client = self.user_pool.add_client(
            "ChatClient",
            user_pool_client_name="support-chat",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            disable_o_auth=True,
            prevent_user_existence_errors=True,
            access_token_validity=Duration.minutes(60),
            id_token_validity=Duration.minutes(60),
            refresh_token_validity=Duration.days(1),
            read_attributes=cognito.ClientAttributes()
            .with_standard_attributes(email=True, email_verified=True)
            .with_custom_attributes("customer_id"),
            write_attributes=cognito.ClientAttributes(),
        )

        # Machine identity the agent uses toward AgentCore Gateway (client credentials grant).
        gateway_scope = cognito.ResourceServerScope(
            scope_name=GATEWAY_SCOPE, scope_description="Call support tools through Gateway"
        )
        resource_server = self.user_pool.add_resource_server(
            "GatewayResourceServer", identifier=GATEWAY_RESOURCE_SERVER, scopes=[gateway_scope]
        )
        self.gateway_client = self.user_pool.add_client(
            "GatewayClient",
            user_pool_client_name="agent-gateway",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(resource_server, gateway_scope)],
            ),
            access_token_validity=Duration.minutes(60),
            write_attributes=cognito.ClientAttributes(),
        )

        # The domain serves the OAuth token endpoint for the client credentials grant.
        self.domain = self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"support-agent-{self.node.addr[-8:]}"
            ),
        )

    @property
    def discovery_url(self) -> str:
        region = Stack.of(self).region
        return (
            f"https://cognito-idp.{region}.amazonaws.com/"
            f"{self.user_pool.user_pool_id}/.well-known/openid-configuration"
        )

    @property
    def token_endpoint(self) -> str:
        return f"{self.domain.base_url()}/oauth2/token"
