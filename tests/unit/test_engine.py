"""Engine doc-shape + step-counter tests — REQ-001, REQ-006..009, REQ-039."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest


def _msg(*, type: str, content: Any, **extra: Any) -> Any:
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

    instance = AgentLog(collection=coll)
    yield instance
    instance.flush_for_tests()


# REQ-039: constructor defaults match spec
def test_TC_039_constructor_defaults(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    instance = AgentLog(collection=coll)
    assert instance.fs_write_tools == frozenset({"write_file", "edit_file"})
    assert instance.max_content_bytes == 15 * 1024 * 1024
    assert instance.max_search_text_bytes == 8 * 1024
    assert instance.queue_maxsize == 256


# REQ-001: one doc per record() invocation
def test_TC_001_one_doc_per_record(log: Any, coll: Any) -> None:
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="hi")])
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="hi")])
    log.flush_for_tests()
    assert coll.count_documents({}) == 2


# REQ-006: required top-level fields
def test_TC_006_top_level_fields_present(log: Any, coll: Any) -> None:
    from datetime import datetime

    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="hi")])
    log.flush_for_tests()
    doc = coll.find_one({})
    assert doc is not None
    for key in (
        "thread_id",
        "user_id",
        "agent_name",
        "step",
        "ts",
        "parent_step",
        "messages",
        "todos",
        "files_touched",
        "correlation_id",
    ):
        assert key in doc, f"missing field: {key}"
    assert doc["step"] == 0
    assert doc["parent_step"] is None
    assert isinstance(doc["ts"], datetime)


# REQ-006b: step monotonic per thread; parent_step == step-1 for step > 0
def test_TC_006b_step_monotonic_per_thread(log: Any, coll: Any) -> None:
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="a")])
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="b")])
    log.record(thread_id="t2", user_id="u1", messages=[_msg(type="human", content="c")])
    log.flush_for_tests()

    docs_t1 = list(coll.find({"thread_id": "t1"}).sort("step", 1))
    docs_t2 = list(coll.find({"thread_id": "t2"}).sort("step", 1))
    assert [d["step"] for d in docs_t1] == [0, 1]
    assert [d["parent_step"] for d in docs_t1] == [None, 0]
    assert [d["step"] for d in docs_t2] == [0]


# REQ-007a: agent_name defaults to "main"
def test_TC_007a_agent_name_defaults_main(log: Any, coll: Any) -> None:
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="hi")])
    log.flush_for_tests()
    assert coll.find_one({})["agent_name"] == "main"


# REQ-007b: explicit agent_name lands on doc
def test_TC_007b_agent_name_explicit(log: Any, coll: Any) -> None:
    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[_msg(type="human", content="hi")],
        agent_name="researcher",
    )
    log.flush_for_tests()
    assert coll.find_one({})["agent_name"] == "researcher"


# REQ-008: missing thread_id → no write
def test_TC_008_missing_thread_id_no_write(log: Any, coll: Any) -> None:
    log.record(thread_id="", user_id="u1", messages=[_msg(type="human", content="hi")])
    log.record(thread_id="t1", user_id="", messages=[_msg(type="human", content="hi")])
    log.flush_for_tests()
    assert coll.count_documents({}) == 0


# REQ-006: correlation_id explicit + default
def test_TC_006_correlation_id_persisted(log: Any, coll: Any) -> None:
    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[_msg(type="human", content="hi")],
        correlation_id="abc-123",
    )
    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[_msg(type="human", content="hi2")],
    )
    log.flush_for_tests()
    docs = list(coll.find({}).sort("step", 1))
    assert docs[0]["correlation_id"] == "abc-123"
    assert docs[1]["correlation_id"] == ""


# REQ-002: messages array preserves order
def test_TC_002_messages_preserve_order(log: Any, coll: Any) -> None:
    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[
            _msg(type="human", content="A"),
            _msg(type="ai", content="B"),
            _msg(type="tool", content="C"),
        ],
    )
    log.flush_for_tests()
    doc = coll.find_one({})
    assert [m["content"] for m in doc["messages"]] == ["A", "B", "C"]
