import os

from botocore.config import Config
from strands.models.bedrock import BedrockModel

from model.settings import guardrail_config, unguard_memory_context

# Haiku 4.5 keeps costs low; set MODEL_ID to us.anthropic.claude-sonnet-4-6 if it falls short.
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Adaptive mode retries throttling and 5xx with backoff and slows down under sustained throttling.
BEDROCK_CLIENT_CONFIG = Config(
    retries={"mode": "adaptive", "max_attempts": 4}, connect_timeout=5, read_timeout=120
)


class SupportBedrockModel(BedrockModel):
    """BedrockModel whose guardrail checks the customer's text but not Memory's context block."""

    # Overrides a private Strands method. If it is ever renamed, this stops applying and the
    # context is simply guarded again, which blocks more, never less.
    def _format_bedrock_messages(self, messages, *args, **kwargs):
        return unguard_memory_context(super()._format_bedrock_messages(messages, *args, **kwargs))


def load_model() -> BedrockModel:
    """Create the Bedrock model client, authenticated with the runtime's IAM role."""
    return SupportBedrockModel(
        model_id=os.getenv("MODEL_ID", DEFAULT_MODEL_ID),
        boto_client_config=BEDROCK_CLIENT_CONFIG,
        **guardrail_config(os.environ),
    )
