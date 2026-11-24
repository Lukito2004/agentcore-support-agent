from functools import lru_cache

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

import telemetry
from caller import AuthError, SessionRegistry, caller_from_headers
from gateway import connect_from_env
from hooks import RetryHook, ToolCallGuard
from memory import memory_session_manager
from model.load import load_model
from prompts import build_system_prompt
from validation import InvalidRequestError, validate_payload, validate_session_id

# Keeps the last N messages so a long session cannot overflow the model context.
CONVERSATION_WINDOW = 20

sessions = SessionRegistry()
# Business tools come from AgentCore Gateway over MCP; None under `agentcore dev`.
gateway = connect_from_env()


def _error(code: str, message: str) -> dict:
    # Every rejected or failed request is marked in its trace.
    telemetry.record("request_failed", error_code=code)
    return {"error": {"code": code, "message": message}}


@lru_cache(maxsize=32)
def _get_agent(session_id: str, actor_id: str, customer_id: str) -> Agent:
    """One agent per (session, user); it holds the in-session conversation history.

    Deployed, each session has its own microVM, so this cache only ever holds one entry there.
    AgentCore Memory restores the session after a microVM restart and adds long-term context.
    """
    return Agent(
        model=load_model(),
        system_prompt=build_system_prompt(customer_id),
        tools=[gateway.client] if gateway else [],
        hooks=[ToolCallGuard(customer_id, actor_id, session_id), RetryHook()],
        session_manager=memory_session_manager(session_id, actor_id),
        conversation_manager=SlidingWindowConversationManager(window_size=CONVERSATION_WINDOW),
    )


def create_app() -> BedrockAgentCoreApp:
    app = BedrockAgentCoreApp()
    log = app.logger

    @app.entrypoint
    async def invoke(payload, context):
        session_id = getattr(context, "session_id", None)
        if not session_id:
            yield _error("MISSING_SESSION", "a runtime session ID is required")
            return
        try:
            validate_session_id(session_id)
        except InvalidRequestError as exc:
            # The ID is client input, so it is not logged.
            log.warning("Rejected a malformed session ID: %s", exc)
            yield _error("INVALID_REQUEST", str(exc))
            return

        try:
            caller = caller_from_headers(getattr(context, "request_headers", None))
        except AuthError as exc:
            log.warning("Unauthenticated request in session %s: %s", session_id, exc)
            yield _error("UNAUTHENTICATED", str(exc))
            return

        if not sessions.claim(session_id, caller.actor_id):
            log.warning("Session %s reused by another user %s", session_id, caller.log_id)
            yield _error("SESSION_FORBIDDEN", "this session belongs to another user")
            return

        try:
            prompt = validate_payload(payload)
        except InvalidRequestError as exc:
            log.warning("Rejected request in session %s: %s", session_id, exc)
            yield _error("INVALID_REQUEST", str(exc))
            return

        if gateway:
            try:
                await gateway.token.ensure_fresh()
            except Exception:
                log.exception("Could not get a Gateway token in session %s", session_id)
                yield _error("TOOLS_UNAVAILABLE", "support tools are unavailable, please retry")
                return

        # Log metadata only; prompts can contain personal data.
        log.info(
            "Invoking agent: session=%s actor=%s prompt_chars=%d",
            session_id,
            caller.log_id,
            len(prompt),
        )
        try:
            agent = _get_agent(session_id, caller.actor_id, caller.customer_id)
            async for event in agent.stream_async(prompt):
                if not isinstance(event, dict) or "event" not in event:
                    continue
                block_start = event["event"].get("contentBlockStart")
                if block_start is not None and not block_start.get("start"):
                    continue
                yield event
        except Exception:
            log.exception("Agent invocation failed in session %s", session_id)
            yield _error("INTERNAL_ERROR", "the assistant failed to respond, please try again")

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
