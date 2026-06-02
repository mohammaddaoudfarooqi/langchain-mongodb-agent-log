"""Async ainvoke smoke test — confirm the daemon worker drains and the
embedder fires on the final super-step under ``graph.ainvoke``.
"""
from __future__ import annotations

import mongomock
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage

# Hermetic — mongomock + FakeMessagesListChatModel; not gated on Atlas.


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.0] * 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]


async def test_async_ainvoke_writes_log_with_embedding() -> None:
    from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

    coll = mongomock.MongoClient()["t"]["agent_log"]
    embedder = _FakeEmbedder()
    log = AgentLog(collection=coll, embeddings=embedder)

    agent = create_agent(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
        tools=[],
        middleware=[AgentLogMiddleware(log)],
    )

    await agent.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "ta", "user_id": "u1"}},
    )
    log.flush_for_tests()

    assert coll.count_documents({}) >= 1
    final = coll.find_one({"agent_log_embedding": {"$exists": True}})
    assert final is not None, "no doc with embedding fields was written"
    assert final["agent_log_text"]
    assert isinstance(final["agent_log_embedding"], list)
    assert embedder.calls, "embedder was never called"
