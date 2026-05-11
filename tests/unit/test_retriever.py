"""Retriever tests — REQ-032, REQ-033, INV-004."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import mongomock
import pytest


class _FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


# REQ-032: AgentLogRetriever wraps MongoDBAtlasHybridSearchRetriever
def test_TC_032_retriever_uses_hybrid_class(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    fake_docs = [MagicMock(metadata={"thread_id": "t1"}, page_content="hi")]

    with patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    ) as cls:
        instance = MagicMock()
        instance.invoke.return_value = fake_docs
        cls.return_value = instance

        retriever = AgentLogRetriever(coll, embeddings=_FakeEmbedder())
        result = retriever.invoke("query", user_id="u1")

        assert cls.called
        assert result == fake_docs


# REQ-033: per-user pre_filter
def test_TC_033_per_user_pre_filter(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    with patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    ) as cls:
        instance = MagicMock()
        instance.invoke.return_value = []
        cls.return_value = instance

        retriever = AgentLogRetriever(coll, embeddings=_FakeEmbedder())
        retriever.invoke("q", user_id="alice")

        kwargs = cls.call_args.kwargs
        assert kwargs.get("pre_filter") == {"user_id": {"$eq": "alice"}}


# INV-004: cross-user retrieval impossible because pre_filter is mandatory
def test_TC_INV_004_cross_user_blocked_via_prefilter(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    with patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    ) as cls:
        instance = MagicMock()
        instance.invoke.return_value = []
        cls.return_value = instance

        retriever = AgentLogRetriever(coll, embeddings=_FakeEmbedder())
        retriever.invoke("q", user_id="bob")

        kwargs = cls.call_args.kwargs
        # Anywhere alice's data is in the index, bob's call must filter it out.
        assert kwargs["pre_filter"]["user_id"]["$eq"] == "bob"
