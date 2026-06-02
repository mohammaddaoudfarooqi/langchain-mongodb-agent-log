"""Middleware adapter tests — REQ-023..026, REQ-007b."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

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


def _runtime(thread_id: str, user_id: str, **extra: Any) -> Any:
    rt = MagicMock()
    rt.config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id, **extra}
    }
    return rt


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


@pytest.fixture
def log(coll: Any) -> Any:
    from langchain_mongodb_agent_log import AgentLog

    return AgentLog(collection=coll)


# REQ-023: AgentLogMiddleware subclasses AgentMiddleware
def test_TC_023_middleware_subclasses_AgentMiddleware() -> None:
    from langchain.agents.middleware import AgentMiddleware

    from langchain_mongodb_agent_log import AgentLogMiddleware

    assert issubclass(AgentLogMiddleware, AgentMiddleware)


# REQ-024: sync after_model writes one doc and returns None
def test_TC_024_sync_after_model_writes_and_returns_None(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    rt = _runtime("t1", "u1")
    state = {"messages": [_msg(type="human", content="hi"), _msg(type="ai", content="ok")]}
    result = mw.after_model(state, rt)
    log.flush_for_tests()
    assert result is None
    assert coll.count_documents({}) == 1


# REQ-025: async aafter_model writes one doc
async def test_TC_025_async_aafter_model_writes(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    rt = _runtime("t1", "u1")
    state = {"messages": [_msg(type="human", content="hi"), _msg(type="ai", content="ok")]}
    result = await mw.aafter_model(state, rt)
    log.flush_for_tests()
    assert result is None
    assert coll.count_documents({}) == 1


# REQ-026a: get_config() consulted first
def test_TC_026a_get_config_used_when_available(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    fake_runtime = MagicMock()
    fake_runtime.config = {}  # empty fallback

    fake_cfg = {"configurable": {"thread_id": "t99", "user_id": "u99"}}
    with patch("langgraph.config.get_config", return_value=fake_cfg):
        mw.after_model(
            {"messages": [_msg(type="human", content="hi")]}, fake_runtime
        )
    log.flush_for_tests()
    doc = coll.find_one({})
    assert doc is not None
    assert doc["thread_id"] == "t99"
    assert doc["user_id"] == "u99"


# REQ-026b: get_config() raises → falls back to runtime.config
def test_TC_026b_runtime_config_fallback(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    rt = _runtime("t-fb", "u-fb")
    with patch("langgraph.config.get_config", side_effect=RuntimeError("no context")):
        mw.after_model({"messages": [_msg(type="human", content="hi")]}, rt)
    log.flush_for_tests()
    doc = coll.find_one({})
    assert doc is not None
    assert doc["thread_id"] == "t-fb"


# REQ-007b: configurable["agent_name"] lands on the doc
def test_TC_007b_agent_name_via_middleware(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    rt = _runtime("t1", "u1", agent_name="researcher")
    mw.after_model({"messages": [_msg(type="human", content="hi")]}, rt)
    log.flush_for_tests()
    assert coll.find_one({})["agent_name"] == "researcher"


# Bonus: missing thread_id silently skips
def test_missing_thread_id_skips(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    rt = MagicMock()
    rt.config = {"configurable": {}}
    mw.after_model({"messages": [_msg(type="human", content="hi")]}, rt)
    log.flush_for_tests()
    assert coll.count_documents({}) == 0


# get_config() unavailable and no runtime.config → recover thread_id from the
# Runtime's execution_info. This is the only identity LangGraph propagates into
# an async node, so without this fallback the engine would silently drop the
# super-step whenever the ambient runnable-config context is unreachable.
def test_execution_info_thread_id_fallback() -> None:
    from langchain_mongodb_agent_log.adapters.middleware import (
        _configurable_from_runtime,
    )

    class _ExecInfo:
        thread_id = "ta"

    class _Runtime:
        # No ``config`` attribute, mirroring a real LangGraph Runtime.
        execution_info = _ExecInfo()

    with patch(
        "langgraph.config.get_config", side_effect=RuntimeError("no context")
    ):
        cfg = _configurable_from_runtime(_Runtime())
    assert cfg == {"thread_id": "ta"}
