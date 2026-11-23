import os

from strands.models.bedrock import BedrockModel

# Haiku 4.5 keeps costs low; set MODEL_ID to us.anthropic.claude-sonnet-4-6 if it falls short.
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def load_model() -> BedrockModel:
    """Create the Bedrock model client, authenticated with the runtime's IAM role."""
    return BedrockModel(model_id=os.getenv("MODEL_ID", DEFAULT_MODEL_ID))
