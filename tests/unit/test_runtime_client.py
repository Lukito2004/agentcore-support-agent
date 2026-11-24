import json
import re

import httpx
import pytest

from runtime_client import (
    SESSION_HEADER,
    AgentError,
    RuntimeClient,
    invocation_url,
    new_session_id,
    parse_events,
)

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/support_agent-abc"


def delta(text: str) -> str:
    return "data: " + json.dumps({"event": {"contentBlockDelta": {"delta": {"text": text}}}})


def test_text_deltas_are_joined_and_other_lines_ignored():
    lines = [
        ": keep-alive",
        delta("Your order "),
        "data: not json",
        "data: [1, 2]",
        "data: " + json.dumps({"event": {"messageStart": {"role": "assistant"}}}),
        delta("is delayed."),
    ]
    assert "".join(parse_events(lines)) == "Your order is delayed."


def test_text_after_a_tool_call_starts_a_new_paragraph():
    def event(body: dict) -> str:
        return "data: " + json.dumps({"event": body})

    lines = [
        delta("I'll check order 123."),
        event({"contentBlockStop": {"contentBlockIndex": 0}}),
        event({"contentBlockStart": {"start": {"toolUse": {"name": "get_order_status"}}}}),
        event({"contentBlockStop": {"contentBlockIndex": 1}}),
        delta("It is delayed."),
        delta(" Sorry."),
        event({"contentBlockStop": {"contentBlockIndex": 0}}),
    ]
    assert "".join(parse_events(lines)) == "I'll check order 123.\n\nIt is delayed. Sorry."


def test_error_event_raises_with_its_code():
    lines = [delta("Hi"), 'data: {"error": {"code": "SESSION_FORBIDDEN", "message": "no"}}']
    events = parse_events(lines)
    assert next(events) == "Hi"
    with pytest.raises(AgentError) as err:
        next(events)
    assert err.value.code == "SESSION_FORBIDDEN"


def test_session_ids_are_long_unique_and_valid_for_memory():
    first, second = new_session_id(), new_session_id()
    assert first != second
    assert len(first) >= 33
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-_]*", first)


def test_invocation_url_encodes_the_runtime_arn():
    url = invocation_url("us-east-1", ARN)
    assert url.startswith("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws")
    assert "runtime%2Fsupport_agent-abc/invocations?qualifier=DEFAULT" in url


def client_with(handler) -> RuntimeClient:
    return RuntimeClient(
        "us-east-1", ARN, http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_reply_is_streamed_with_token_and_session_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text="\n".join([delta("Hello"), delta(" there")]))

    text = "".join(client_with(handler).stream_reply("access-123", "chat-abc", "Hi"))
    assert text == "Hello there"
    assert seen["authorization"] == "Bearer access-123"
    assert seen[SESSION_HEADER.lower()] == "chat-abc"
    assert seen["body"] == {"prompt": "Hi"}


@pytest.mark.parametrize(
    ("status", "code"), [(401, "UNAUTHENTICATED"), (429, "THROTTLED"), (500, "UNAVAILABLE")]
)
def test_http_errors_become_codes_without_the_body(status, code):
    client = client_with(lambda _req: httpx.Response(status, text="internal stack trace"))
    with pytest.raises(AgentError) as err:
        list(client.stream_reply("t", "chat-abc", "Hi"))
    assert err.value.code == code
    assert "stack trace" not in str(err.value)


def test_network_failure_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AgentError) as err:
        list(client_with(handler).stream_reply("t", "chat-abc", "Hi"))
    assert err.value.code == "UNAVAILABLE"
