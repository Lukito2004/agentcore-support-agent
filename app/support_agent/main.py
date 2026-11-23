from functools import lru_cache

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from model.load import load_model
from prompts import SYSTEM_PROMPT
from validation import InvalidRequestError, validate_payload

# Business tools are not wired in yet; they will come from AgentCore Gateway over MCP.
TOOLS: list = []

# Keeps the last N messages so a long session cannot overflow the model context.
CONVERSATION_WINDOW = 20


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


@lru_cache(maxsize=32)
def _get_agent(session_id: str) -> Agent:
    """One agent per runtime session; it holds the in-session conversation history.

    Deployed, each session has its own microVM, so this cache only ever holds one entry there.
    """
    return Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
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
            prompt = validate_payload(payload)
        except InvalidRequestError as exc:
            log.warning("Rejected request in session %s: %s", session_id, exc)
            yield _error("INVALID_REQUEST", str(exc))
            return

        # Log metadata only; prompts can contain personal data.
        log.info("Invoking agent: session=%s prompt_chars=%d", session_id, len(prompt))
        try:
            async for event in _get_agent(session_id).stream_async(prompt):
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
