from collections.abc import Mapping

GUARDRAIL_ID_ENV = "GUARDRAIL_ID"
GUARDRAIL_VERSION_ENV = "GUARDRAIL_VERSION"


def guardrail_config(env: Mapping[str, str]) -> dict:
    """Strands BedrockModel guardrail settings, or {} without a guardrail (local dev)."""
    guardrail_id, version = env.get(GUARDRAIL_ID_ENV), env.get(GUARDRAIL_VERSION_ENV)
    if not guardrail_id or not version:
        return {}
    return {
        "guardrail_id": guardrail_id,
        "guardrail_version": version,
        "guardrail_trace": "enabled",
        # Check only the newest user message: cheaper, and old turns are not re-blocked.
        "guardrail_latest_message": True,
        # Replace a blocked message in the history so an attack does not linger in context.
        "guardrail_redact_input": True,
        "guardrail_redact_input_message": "[Message removed by the content filter]",
    }
