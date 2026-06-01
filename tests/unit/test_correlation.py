"""Correlation-id derivation + agent_name override — REQ-315, REQ-316."""
from __future__ import annotations

import uuid
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


def _runtime(thread_id: str, user_id: str, **extra: Any) -> Any:
    rt = MagicMock()
    rt.config = {"configurable": {"thread_id": thread_id, "user_id": user_id, **extra}}
    return rt


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


@pytest.fixture
def log(coll: Any) -> Any:
    from langchain_mongodb_agent_log import AgentLog

    return AgentLog(collection=coll, flush_on_exit=False)


# REQ-316: precedence — explicit correlation_id wins.
def test_TC_316_explicit_correlation_id_wins() -> None:
    from langchain_mongodb_agent_log.adapters._correlation import derive_correlation_id

    cfg = {"correlation_id": "explicit-1", "traceparent": "00-abc-def-01", "x_request_id": "rq"}
    assert derive_correlation_id(cfg) == "explicit-1"


# REQ-316: W3C traceparent trace-id is used when no explicit id.
def test_TC_316_traceparent_trace_id() -> None:
    from langchain_mongodb_agent_log.adapters._correlation import derive_correlation_id

    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert derive_correlation_id({"traceparent": tp}) == "4bf92f3577b34da6a3ce929d0e0e4736"


# REQ-316: x_request_id is next.
def test_TC_316_x_request_id() -> None:
    from langchain_mongodb_agent_log.adapters._correlation import derive_correlation_id

    assert derive_correlation_id({"x_request_id": "req-42"}) == "req-42"


# REQ-316: absent everything → a fresh uuid4 string.
def test_TC_316_generates_uuid_when_absent() -> None:
    from langchain_mongodb_agent_log.adapters._correlation import derive_correlation_id

    cid = derive_correlation_id({})
    # Parses as a UUID (matches the server-minted format).
    assert uuid.UUID(cid)


# REQ-316: the middleware stamps a derived correlation id onto the doc.
def test_TC_316_middleware_stamps_correlation(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log)
    mw.after_model({"messages": [_msg(type="human", content="hi")]}, _runtime("t1", "u1"))
    log.flush_for_tests(timeout=5.0)
    doc = coll.find_one({})
    assert doc["correlation_id"]  # non-empty
    assert uuid.UUID(doc["correlation_id"])  # generated uuid
    log.close(timeout=5.0)


# REQ-315: constructor agent_name overrides configurable.
def test_TC_315_ctor_agent_name_overrides(log: Any, coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    mw = AgentLogMiddleware(log, agent_name="researcher")
    # configurable says "main" but the ctor override must win.
    mw.after_model(
        {"messages": [_msg(type="human", content="hi")]},
        _runtime("t1", "u1", agent_name="main"),
    )
    log.flush_for_tests(timeout=5.0)
    assert coll.find_one({})["agent_name"] == "researcher"
    log.close(timeout=5.0)
