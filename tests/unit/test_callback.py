"""Callback handler tests — REQ-027..030.

The callback adapter pairs ``on_chain_start`` (where LangGraph stamps the
node metadata) with ``on_chain_end`` (where it doesn't), keyed by
``run_id``. Tests fire the matched pair to mimic LangGraph's behavior.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import mongomock
import pytest


def _msg(*, type: str, content: str, **extra: Any) -> Any:
    m = MagicMock()
    m.type = type
    m.content = content
    m.tool_calls = extra.get("tool_calls", [])
    m.tool_call_id = extra.get("tool_call_id")
    m.usage_metadata = extra.get("usage_metadata")
    m.additional_kwargs = extra.get("additional_kwargs", {})
    return m


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


@pytest.fixture
def log(coll: Any) -> Any:
    from langchain_mongodb_agent_log import AgentLog

    return AgentLog(collection=coll)


# REQ-027: subclass of BaseCallbackHandler
def test_TC_027_callback_subclasses_BaseCallbackHandler() -> None:
    from langchain_core.callbacks import BaseCallbackHandler

    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    assert issubclass(AgentLogCallbackHandler, BaseCallbackHandler)


# REQ-028: top-level node end → 1 doc with agent_name = node
def test_TC_028_top_level_node_writes(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    h = AgentLogCallbackHandler(log)
    rid = uuid4()
    meta = {
        "langgraph_node": "supervisor",
        "thread_id": "t1",
        "user_id": "u1",
    }
    h.on_chain_start(None, {}, run_id=rid, tags=["graph:step:1"], metadata=meta)

    outputs = {
        "messages": [
            _msg(type="human", content="hi"),
            _msg(type="ai", content="ok"),
        ]
    }
    h.on_chain_end(outputs, run_id=rid, tags=["graph:step:1"], metadata=None)
    log.flush_for_tests()
    assert coll.count_documents({}) == 1
    assert coll.find_one({})["agent_name"] == "supervisor"


# REQ-029: inner Runnable on_chain_start (no langgraph_node) → no doc
def test_TC_029_inner_runnable_ignored(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    h = AgentLogCallbackHandler(log)
    rid = uuid4()
    # No "langgraph_node" — should be ignored.
    h.on_chain_start(None, {}, run_id=rid, tags=[], metadata={"thread_id": "t1"})
    h.on_chain_end(
        {"messages": [_msg(type="ai", content="ok")]},
        run_id=rid,
        tags=[],
        metadata=None,
    )
    log.flush_for_tests()
    assert coll.count_documents({}) == 0


# REQ-030: async on_chain_*_async fires the same path
async def test_TC_030_async_callback_fires(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    h = AgentLogCallbackHandler(log)
    rid = uuid4()
    meta = {
        "langgraph_node": "researcher",
        "thread_id": "t1",
        "user_id": "u1",
    }
    await h.on_chain_start_async(  # type: ignore[attr-defined]
        None, {}, run_id=rid, tags=[], metadata=meta
    )
    outputs = {
        "messages": [
            _msg(type="human", content="hi"),
            _msg(type="ai", content="ok"),
        ]
    }
    await h.on_chain_end_async(  # type: ignore[attr-defined]
        outputs, run_id=rid, tags=[], metadata=None
    )
    log.flush_for_tests()
    assert coll.count_documents({}) == 1
    assert coll.find_one({})["agent_name"] == "researcher"


# Bonus: missing thread_id from metadata → no write
def test_callback_missing_thread_id_skips(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    h = AgentLogCallbackHandler(log)
    rid = uuid4()
    h.on_chain_start(
        None, {}, run_id=rid, tags=[], metadata={"langgraph_node": "supervisor"}
    )  # no thread/user
    h.on_chain_end({"messages": [_msg(type="ai", content="x")]}, run_id=rid, tags=[], metadata=None)
    log.flush_for_tests()
    assert coll.count_documents({}) == 0
