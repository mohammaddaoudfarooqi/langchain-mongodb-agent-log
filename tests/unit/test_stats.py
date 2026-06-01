"""Observability tests — REQ-304, REQ-305, BUG-301 (drop-oldest counter)."""
from __future__ import annotations

import threading
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


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


# REQ-304: stats() returns the documented shape, O(1), no DB round-trip.
def test_TC_304_stats_shape(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    s = log.stats()
    for key in (
        "queue_depth",
        "queue_capacity",
        "worker_alive",
        "enqueued",
        "written",
        "dropped",
        "embed_failures",
        "write_failures",
        "last_write_ts",
    ):
        assert key in s, f"stats() missing {key!r}"
    assert s["queue_capacity"] == 256
    assert s["enqueued"] == 0
    assert s["written"] == 0
    assert s["dropped"] == 0
    assert s["last_write_ts"] is None
    log.close(timeout=5.0)


# REQ-305: counters advance as work flows through.
def test_TC_305_counters_advance(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    for i in range(5):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    log.flush_for_tests(timeout=5.0)
    s = log.stats()
    assert s["enqueued"] == 5
    assert s["written"] == 5
    assert s["dropped"] == 0
    assert s["last_write_ts"] is not None
    log.close(timeout=5.0)


# BUG-301 / REQ-305: a full queue drops the OLDEST, keeps the NEWEST,
# and increments the dropped counter. Under the old (buggy) behavior the
# newest doc would be dropped, so asserting the newest survives is the
# discriminating check.
def test_TC_301_drop_oldest_keeps_newest(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    release = threading.Event()
    real_insert = coll.insert_one

    def blocking_insert(doc: Any, *a: Any, **k: Any) -> Any:
        release.wait(5.0)
        return real_insert(doc, *a, **k)

    with patch.object(coll, "insert_one", side_effect=blocking_insert):
        log = AgentLog(collection=coll, queue_maxsize=2, flush_on_exit=False)
        for i in range(6):
            log.record(
                thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))]
            )
        release.set()
        log.flush_for_tests(timeout=5.0)

    contents = {d["messages"][0]["content"] for d in coll.find({})}
    assert "5" in contents, "newest doc must survive (drop-oldest, not drop-newest)"
    s = log.stats()
    assert s["dropped"] > 0, "dropped counter should record the evictions"
    assert coll.count_documents({}) == 6 - s["dropped"]
    log.close(timeout=5.0)
