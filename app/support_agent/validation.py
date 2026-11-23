import re

MAX_PROMPT_CHARS = 4000
ALLOWED_FIELDS = frozenset({"prompt"})

# Control characters except tab, newline and carriage return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InvalidRequestError(ValueError):
    """A payload failed validation. The message is safe to return to the caller."""


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

    prompt = _CONTROL_CHARS.sub("", prompt).strip()
    if not prompt:
        raise InvalidRequestError("prompt must not be empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidRequestError(f"prompt must be at most {MAX_PROMPT_CHARS} characters")

    return prompt
