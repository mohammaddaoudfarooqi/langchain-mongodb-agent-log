"""Graph-node adapter tests — REQ-031."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest


def _msg(*, type: str, content: str) -> Any:
    m = MagicMock()
    m.type = type
    m.content = content
    m.tool_calls = []
    m.tool_call_id = None
    m.usage_metadata = None
    m.additional_kwargs = {}
    return m


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


@pytest.fixture
def log(coll: Any) -> Any:
    from langchain_mongodb_agent_log import AgentLog

    return AgentLog(collection=coll)


def test_TC_031_node_writes_doc_returns_empty_delta(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import agent_log_node

    node = agent_log_node(log)
    state = {"messages": [_msg(type="human", content="hi")]}
    config = {
        "configurable": {
            "thread_id": "t1",
            "user_id": "u1",
            "agent_name": "main",
        }
    }
    result = node(state, config)
    log.flush_for_tests()

    assert result == {}
    assert coll.count_documents({}) == 1


def test_TC_031b_node_skips_when_thread_id_missing(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import agent_log_node

    node = agent_log_node(log)
    state = {"messages": [_msg(type="human", content="hi")]}
    result = node(state, {"configurable": {}})  # missing thread_id/user_id
    log.flush_for_tests()
    assert result == {}
    assert coll.count_documents({}) == 0
