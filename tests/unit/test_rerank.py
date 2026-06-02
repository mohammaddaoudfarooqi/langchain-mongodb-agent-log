"""Retriever filters + best-effort rerank + index forwarding — REQ-311/312/313."""
from __future__ import annotations

from datetime import UTC, datetime
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


def _patch_hybrid(docs: list[Any]) -> Any:
    p = patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    )
    cls = p.start()
    instance = MagicMock()
    instance.invoke.return_value = docs
    cls.return_value = instance
    return p, cls


# REQ-312: thread_id + since narrow the pre_filter; user_id is always present.
def test_TC_312_compound_prefilter(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    p, cls = _patch_hybrid([])
    try:
        r = AgentLogRetriever(coll, embeddings=_FakeEmbedder())
        since = datetime(2026, 1, 1, tzinfo=UTC)
        r.invoke("q", user_id="alice", thread_id="t-7", since=since)
        pre = cls.call_args.kwargs["pre_filter"]
        assert pre["user_id"] == {"$eq": "alice"}
        assert pre["thread_id"] == {"$eq": "t-7"}
        assert pre["ts"] == {"$gte": since}
    finally:
        p.stop()


def test_TC_312_user_id_always_present(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    p, cls = _patch_hybrid([])
    try:
        r = AgentLogRetriever(coll, embeddings=_FakeEmbedder())
        r.invoke("q", user_id="bob", thread_id="t-7")  # thread set, no since
        pre = cls.call_args.kwargs["pre_filter"]
        assert pre["user_id"] == {"$eq": "bob"}
        assert "ts" not in pre
    finally:
        p.stop()


# REQ-313: a reranker reorders results; top_k is honored.
def test_TC_313_rerank_applied(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    docs = [MagicMock(page_content=str(i)) for i in range(6)]
    p, _ = _patch_hybrid(docs)
    try:
        reranker = MagicMock()
        reranker.compress_documents.return_value = list(reversed(docs))
        r = AgentLogRetriever(coll, embeddings=_FakeEmbedder(), top_k=2, reranker=reranker)
        out = r.invoke("q", user_id="u1")
        assert reranker.compress_documents.called
        assert out == list(reversed(docs))[:2]
    finally:
        p.stop()


# REQ-313: a reranker that raises falls back to RRF order, never propagates.
def test_TC_313_rerank_fallback_on_error(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.retriever import AgentLogRetriever

    docs = [MagicMock(page_content=str(i)) for i in range(6)]
    p, _ = _patch_hybrid(docs)
    try:
        reranker = MagicMock()
        reranker.compress_documents.side_effect = RuntimeError("rerank down")
        r = AgentLogRetriever(coll, embeddings=_FakeEmbedder(), top_k=3, reranker=reranker)
        out = r.invoke("q", user_id="u1")  # must not raise
        assert out == docs[:3]
    finally:
        p.stop()


# REQ-311: build_tool forwards index names + reranker to the retriever.
def test_TC_311_build_tool_forwards_index_names(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval import tool as tool_mod

    with patch.object(tool_mod, "AgentLogRetriever") as RetrieverCls:
        tool_mod.build_tool(
            coll,
            _FakeEmbedder(),
            search_index="sx",
            vector_index="vx",
        )
        kwargs = RetrieverCls.call_args.kwargs
        assert kwargs["search_index"] == "sx"
        assert kwargs["vector_index"] == "vx"
