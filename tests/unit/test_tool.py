"""search_past_conversations tool tests — REQ-034..036."""
from __future__ import annotations

import json
import logging
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


def _planted_doc() -> Any:
    d = MagicMock()
    d.metadata = {
        "thread_id": "t1",
        "step": 3,
        "ts": datetime(2026, 1, 1, tzinfo=UTC),
        "agent_name": "main",
        "model_id": "claude-haiku",
    }
    d.page_content = "hello world"
    return d


# REQ-034: @tool returns a JSON list with the right fields
def test_TC_034_tool_returns_json_list(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.tool import build_tool

    with patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    ) as cls:
        cls.return_value.invoke.return_value = [_planted_doc()]
        tool = build_tool(coll, embeddings=_FakeEmbedder())
        result = tool.invoke(
            {"query": "anything"},
            config={"configurable": {"user_id": "u1"}},
        )

    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert parsed[0]["thread_id"] == "t1"
    assert parsed[0]["step"] == 3
    assert parsed[0]["snippet"] == "hello world"
    assert parsed[0]["agent_name"] == "main"
    assert parsed[0]["model_id"] == "claude-haiku"


# REQ-035: missing user_id → REFUSED string
def test_TC_035_missing_user_id_refused(coll: Any) -> None:
    from langchain_mongodb_agent_log.retrieval.tool import build_tool

    tool = build_tool(coll, embeddings=_FakeEmbedder())
    result = tool.invoke({"query": "x"}, config={"configurable": {}})
    assert result == "REFUSED: missing user_id in config"


# REQ-036: retriever raises → "[]" returned + warning
def test_TC_036_retriever_failure_returns_empty(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log.retrieval.tool import build_tool

    with patch(
        "langchain_mongodb_agent_log.retrieval.retriever.MongoDBAtlasHybridSearchRetriever"
    ) as cls:
        cls.return_value.invoke.side_effect = RuntimeError("atlas down")
        tool = build_tool(coll, embeddings=_FakeEmbedder())
        with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
            result = tool.invoke(
                {"query": "x"}, config={"configurable": {"user_id": "u1"}}
            )

    assert result == "[]"
    assert any(
        "search_past_conversations" in r.getMessage() for r in caplog.records
    )
