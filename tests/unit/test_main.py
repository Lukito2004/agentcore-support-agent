import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import pytest

from caller import SessionRegistry
from main import handle

SESSION = "session-test-" + "a" * 32
LOG = logging.getLogger("test_main")


def bearer(**claims) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    token_claims = {"token_use": "access", "sub": "user-1", "customer_id": "CUST-1001", **claims}
    return f"Bearer {part({'alg': 'none'})}.{part(token_claims)}.signature"


def context(session_id=SESSION, authorization=None):
    headers = {"Authorization": authorization if authorization is not None else bearer()}
    return SimpleNamespace(session_id=session_id, request_headers=headers)


def never_called(*_args):
    raise AssertionError("the agent must not run for a rejected request")


class FakeAgent:
    def __init__(self, events, fail=False):
        self.events, self.fail, self.prompts = events, fail, []

    async def stream_async(self, prompt):
        self.prompts.append(prompt)
        for event in self.events:
            yield event
        if self.fail:
            raise RuntimeError("model call failed")


class FakeGateway:
    def __init__(self, fail=False):
        async def ensure_fresh():
            if fail:
                raise RuntimeError("token endpoint down")

        self.token = SimpleNamespace(ensure_fresh=ensure_fresh)


def run(payload, ctx, *, sessions=None, gateway=None, agent_for=never_called) -> list:
    async def collect():
        return [
            event
            async for event in handle(
                payload,
                ctx,
                sessions=sessions or SessionRegistry(),
                gateway=gateway,
                agent_for=agent_for,
                log=LOG,
            )
        ]

    return asyncio.run(collect())


def error_code(events) -> str:
    [event] = events
    return event["error"]["code"]


@pytest.fixture(autouse=True)
def no_local_dev(monkeypatch):
    monkeypatch.delenv("LOCAL_DEV", raising=False)


@pytest.mark.parametrize(
    ("ctx", "payload", "code"),
    [
        (context(session_id=None), {"prompt": "hi"}, "MISSING_SESSION"),
        (context(session_id="has spaces " + "a" * 30), {"prompt": "hi"}, "INVALID_REQUEST"),
        (context(authorization=""), {"prompt": "hi"}, "UNAUTHENTICATED"),
        # An ID token instead of an access token.
        (context(authorization=bearer(**{"token_use": "id"})), {"prompt": "hi"}, "UNAUTHENTICATED"),
        (context(authorization=bearer(customer_id="nobody")), {"prompt": "hi"}, "UNAUTHENTICATED"),
        (context(), {"prompt": "hi", "actorId": "someone-else"}, "INVALID_REQUEST"),
        (context(), {"prompt": "   "}, "INVALID_REQUEST"),
    ],
)
def test_rejected_requests_never_reach_the_agent(ctx, payload, code):
    assert error_code(run(payload, ctx)) == code


def test_a_session_belongs_to_its_first_user():
    sessions = SessionRegistry()
    sessions.claim(SESSION, "another-user")
    assert error_code(run({"prompt": "hi"}, context(), sessions=sessions)) == "SESSION_FORBIDDEN"


def test_no_gateway_token_means_no_agent_run():
    events = run({"prompt": "hi"}, context(), gateway=FakeGateway(fail=True))
    assert error_code(events) == "TOOLS_UNAVAILABLE"


def test_a_valid_request_streams_only_real_events():
    text = {"event": {"contentBlockDelta": {"delta": {"text": "Hello"}}}}
    tool_start = {"event": {"contentBlockStart": {"start": {"toolUse": {"name": "x"}}}}}
    agent = FakeAgent(
        [
            {"event": {"contentBlockStart": {"start": {}}}},  # empty text block start: dropped
            "not a dict",
            {"data": "raw text, not an event"},
            tool_start,
            text,
        ]
    )
    calls = []

    def agent_for(*args):
        calls.append(args)
        return agent

    events = run({"prompt": "  Why is order 123 late?  "}, context(), agent_for=agent_for)
    assert events == [tool_start, text]
    # Identity comes from the token, and the prompt arrives cleaned.
    assert calls == [(SESSION, "user-1", "CUST-1001")]
    assert agent.prompts == ["Why is order 123 late?"]


def test_an_agent_failure_ends_with_a_safe_error():
    text = {"event": {"contentBlockDelta": {"delta": {"text": "Let me check"}}}}
    agent = FakeAgent([text], fail=True)
    events = run({"prompt": "hi"}, context(), gateway=FakeGateway(), agent_for=lambda *_: agent)
    assert events[0] == text
    assert events[1]["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "the assistant failed to respond, please try again",
    }
