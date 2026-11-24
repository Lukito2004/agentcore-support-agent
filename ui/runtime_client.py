"""Calls the agent on AgentCore Runtime over HTTPS and turns its event stream into text."""

import json
import uuid
from collections.abc import Iterable, Iterator
from urllib.parse import quote

import httpx

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
# Replies stream for a while when the agent calls tools, so only connecting is kept short.
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
HTTP_ERROR_CODES = {401: "UNAUTHENTICATED", 403: "UNAUTHENTICATED", 429: "THROTTLED"}


class AgentError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def new_session_id() -> str:
    """Made by the app, never taken from the browser; 37 characters Memory accepts."""
    return f"chat-{uuid.uuid4().hex}"


def invocation_url(region: str, runtime_arn: str) -> str:
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT"
    )


def parse_events(lines: Iterable[str]) -> Iterator[str]:
    """Yield reply text from server-sent events; raise AgentError on an error event."""
    # Text before and after a tool call comes in separate blocks; each new one starts a paragraph.
    text_seen = text_ended = False
    for line in lines:
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[len("data: ") :])
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if isinstance(event.get("error"), dict):
            error = event["error"]
            raise AgentError(str(error.get("code", "UNKNOWN")), str(error.get("message", "")))
        body = event.get("event", {})
        if "contentBlockStop" in body and text_seen:
            text_ended, text_seen = True, False
        if text := body.get("contentBlockDelta", {}).get("delta", {}).get("text"):
            yield f"\n\n{text}" if text_ended else text
            text_ended, text_seen = False, True


class RuntimeClient:
    def __init__(self, region: str, runtime_arn: str, http: httpx.Client | None = None):
        self._url = invocation_url(region, runtime_arn)
        self._http = http or httpx.Client(timeout=TIMEOUT)

    def stream_reply(self, access_token: str, session_id: str, prompt: str) -> Iterator[str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            SESSION_HEADER: session_id,
            "Accept": "text/event-stream",
        }
        try:
            with self._http.stream(
                "POST", self._url, headers=headers, json={"prompt": prompt}
            ) as response:
                if response.status_code >= 400:
                    # The body may hold internal details, so only the status is used.
                    code = HTTP_ERROR_CODES.get(response.status_code, "UNAVAILABLE")
                    raise AgentError(code, f"HTTP {response.status_code}")
                yield from parse_events(response.iter_lines())
        except httpx.HTTPError as exc:
            raise AgentError("UNAVAILABLE", type(exc).__name__) from exc
