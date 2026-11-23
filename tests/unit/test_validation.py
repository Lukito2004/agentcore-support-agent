import pytest

from validation import MAX_PROMPT_CHARS, InvalidRequestError, validate_payload


def test_valid_prompt_is_trimmed():
    assert validate_payload({"prompt": "  Where is order 123?  "}) == "Where is order 123?"


def test_control_characters_are_removed_but_newlines_kept():
    assert validate_payload({"prompt": "line one\x00\x1b\nline two"}) == "line one\nline two"


def test_prompt_at_max_length_is_accepted():
    assert len(validate_payload({"prompt": "a" * MAX_PROMPT_CHARS})) == MAX_PROMPT_CHARS


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("just a string", "JSON object"),
        (["prompt"], "JSON object"),
        ({}, "must be a string"),
        ({"prompt": 42}, "must be a string"),
        ({"prompt": None}, "must be a string"),
        ({"prompt": "   \n\t "}, "must not be empty"),
        ({"prompt": "a" * (MAX_PROMPT_CHARS + 1)}, "at most"),
        ({"prompt": "hi", "actorId": "admin"}, "unsupported fields: actorId"),
        ({"prompt": "hi", "messages": []}, "unsupported fields: messages"),
    ],
)
def test_invalid_payloads_are_rejected(payload, reason):
    with pytest.raises(InvalidRequestError, match=reason):
        validate_payload(payload)
