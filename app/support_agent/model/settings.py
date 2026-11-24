import re
from collections.abc import Mapping

from memory import MEMORY_CONTEXT_TAG

GUARDRAIL_ID_ENV = "GUARDRAIL_ID"
GUARDRAIL_VERSION_ENV = "GUARDRAIL_VERSION"

_MEMORY_CONTEXT_BLOCK = re.compile(rf"<{MEMORY_CONTEXT_TAG}>.*</{MEMORY_CONTEXT_TAG}>", re.DOTALL)


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


def _guarded_text(block: object) -> str | None:
    if not isinstance(block, dict):
        return None
    text = block.get("guardContent", {}).get("text", {}).get("text")
    return text if isinstance(text, str) else None


def unguard_memory_context(messages: list[dict]) -> list[dict]:
    """Leave Memory's remembered context out of the guardrail check; the customer's text stays in.

    The context was screened when the customer first typed it, but with an instruction-like
    request it scores as a prompt attack. Only a block that is wholly one context block and is
    followed by more content counts: Memory puts it first, and prompts cannot contain the tag.
    """
    unguarded = []
    for message in messages:
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            unguarded.append(message)
            continue
        blocks = []
        for index, block in enumerate(content):
            text = _guarded_text(block)
            is_last = index == len(content) - 1
            if text is not None and not is_last and _MEMORY_CONTEXT_BLOCK.fullmatch(text):
                block = {"text": text}
            blocks.append(block)
        unguarded.append({**message, "content": blocks})
    return unguarded
