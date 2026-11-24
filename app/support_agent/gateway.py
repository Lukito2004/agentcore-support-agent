"""MCP connection to AgentCore Gateway, authenticated with an M2M token from AgentCore Identity."""

import logging
import os

import httpx
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
from bedrock_agentcore.services.identity import IdentityClient
from strands.tools.mcp import MCPClient

from token_cache import CachedToken

# Injected by the AgentCore CLI into every runtime of the project.
GATEWAY_URL_ENV = "AGENTCORE_GATEWAY_SUPPORT_TOOLS_URL"
CREDENTIAL_NAME_ENV = "CREDENTIAL_SUPPORT_TOOLS_OAUTH_NAME"
GATEWAY_SCOPE = "support-gateway/tools.invoke"

log = logging.getLogger(__name__)


class _BearerAuth(httpx.Auth):
    """Adds the cached Gateway token to each MCP request (MCP runs on its own thread)."""

    def __init__(self, token: CachedToken) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self._token.value}"
        yield request


class GatewayConnection:
    def __init__(self, url: str, credential_name: str, region: str) -> None:
        self._identity = IdentityClient(region)
        self._provider_name = credential_name
        self.token = CachedToken(self._fetch_token)
        self.client = MCPClient(url=url, auth_provider=_BearerAuth(self.token))

    async def _fetch_token(self) -> str:
        # The client secret never reaches this code: the token vault exchanges it for us.
        workload_token = BedrockAgentCoreContext.get_workload_access_token()
        if not workload_token:
            raise RuntimeError("no workload access token on this request")
        return await self._identity.get_token(
            provider_name=self._provider_name,
            scopes=[GATEWAY_SCOPE],
            auth_flow="M2M",
            agent_identity_token=workload_token,
        )


def connect_from_env() -> GatewayConnection | None:
    url, credential = os.getenv(GATEWAY_URL_ENV), os.getenv(CREDENTIAL_NAME_ENV)
    if not url or not credential:
        log.warning("Gateway env vars not set; running without business tools")
        return None
    return GatewayConnection(url, credential, os.getenv("AWS_REGION", "us-east-1"))
