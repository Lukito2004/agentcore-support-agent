import os

from aws_cdk import App, Environment, Tags

from support_backend.stack import SupportAgentBackendStack

app = App()
SupportAgentBackendStack(
    app,
    "SupportAgentBackend",
    env=Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="us-east-1"),
    description="Business backend for the AgentCore customer support agent",
)
Tags.of(app).add("project", "agentcore-support-agent")
app.synth()
