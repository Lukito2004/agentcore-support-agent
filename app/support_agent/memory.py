"""AgentCore Memory: customer preferences across sessions, scoped to one signed-in user.

Only preferences are kept long term. Business state (orders, refunds, accounts) lives in
DynamoDB and is always read through tools; a copy in memory would go stale and hold PII.
"""

import os
from typing import Any, NamedTuple

# Injected by the AgentCore CLI for the project's "supportMemory" resource.
MEMORY_ID_ENV = "MEMORY_SUPPORTMEMORY_ID"
# Remembered context is added to the customer's message inside this XML tag.
MEMORY_CONTEXT_TAG = "user_context"


class Retrieval(NamedTuple):
    top_k: int
    min_relevance: float


def retrieval_namespaces(actor_id: str) -> dict[str, Retrieval]:
    """Long-term namespaces to search each turn. Each one is scoped to this actor only."""
    if not actor_id or "/" in actor_id:
        raise ValueError("actor_id must be a non-empty ID without '/'")
    return {f"/users/{actor_id}/preferences": Retrieval(top_k=5, min_relevance=0.3)}


def memory_session_manager(session_id: str, actor_id: str) -> Any | None:
    """Strands session manager backed by AgentCore Memory; None when no memory is configured."""
    memory_id = os.getenv(MEMORY_ID_ENV)
    if not memory_id:
        return None

    # Imported here so the pure helpers above stay testable without the agent's dependencies.
    from bedrock_agentcore.memory.integrations.strands.config import (
        AgentCoreMemoryConfig,
        RetrievalConfig,
    )
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )

    config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=actor_id,
        retrieval_config={
            namespace: RetrievalConfig(top_k=r.top_k, relevance_score=r.min_relevance)
            for namespace, r in retrieval_namespaces(actor_id).items()
        },
        context_tag=MEMORY_CONTEXT_TAG,
        # Old tool results are not replayed; order data is always fetched fresh from DynamoDB.
        filter_restored_tool_context=True,
    )
    return AgentCoreMemorySessionManager(config, os.getenv("AWS_REGION", "us-east-1"))
