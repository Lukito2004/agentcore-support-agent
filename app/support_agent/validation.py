import re

from memory import MEMORY_CONTEXT_TAG

MAX_PROMPT_CHARS = 4000
ALLOWED_FIELDS = frozenset({"prompt"})

# Runtime session IDs are at least 33 characters; Memory allows only these characters.
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{32,99}$")

# Only Memory may add remembered-context blocks; the guardrail check relies on it (model/).
_CONTEXT_TAGS = re.compile(rf"<\s*/?\s*{MEMORY_CONTEXT_TAG}\s*>", re.IGNORECASE)

# Control characters except tab, newline and carriage return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_context_tags(text: str) -> str:
    # Repeated, so nesting like "<user_<user_context>context>" cannot rebuild a tag.
    while (stripped := _CONTEXT_TAGS.sub("", text)) != text:
        text = stripped
    return text


class InvalidRequestError(ValueError):
    """A payload failed validation. The message is safe to return to the caller."""


def validate_session_id(session_id: str) -> None:
    """Reject IDs that Memory would refuse later with an unhandled error."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise InvalidRequestError(
            "session ID must be 33-100 characters of letters, digits, - and _"
        )


def validate_payload(payload: object) -> str:
    """Return the cleaned prompt, or raise InvalidRequestError.

    Only a plain string prompt is accepted. Identity (actorId) and conversation history
    are never taken from the client, so callers cannot impersonate users or forge turns.
    """
    if not isinstance(payload, dict):
        raise InvalidRequestError("payload must be a JSON object")

    unexpected = sorted(set(payload) - ALLOWED_FIELDS)
    if unexpected:
        raise InvalidRequestError(f"unsupported fields: {', '.join(map(str, unexpected))}")

    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise InvalidRequestError("prompt must be a string")

    prompt = _strip_context_tags(_CONTROL_CHARS.sub("", prompt)).strip()
    if not prompt:
        raise InvalidRequestError("prompt must not be empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidRequestError(f"prompt must be at most {MAX_PROMPT_CHARS} characters")

    return prompt
