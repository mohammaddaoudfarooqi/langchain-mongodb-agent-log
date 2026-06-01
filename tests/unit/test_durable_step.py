"""Durable step-counter tests — REQ-306, REQ-307, NFR-300."""
from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from pymongo.errors import PyMongoError


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


# REQ-306: durable_step assigns monotonic step from a persisted counter.
def test_TC_306_durable_step_sequence(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, durable_step=True, flush_on_exit=False)
    for i in range(3):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    log.flush_for_tests(timeout=5.0)
    steps = [d["step"] for d in coll.find({"thread_id": "t1"}).sort("step", 1)]
    assert steps == [0, 1, 2]
    parents = [d["parent_step"] for d in coll.find({"thread_id": "t1"}).sort("step", 1)]
    assert parents == [None, 0, 1]
    log.close(timeout=5.0)


# REQ-306: step survives a process "restart" — a fresh engine on the same
# collection continues the sequence rather than resetting to 0.
def test_TC_306_durable_step_survives_restart(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    a = AgentLog(collection=coll, durable_step=True, flush_on_exit=False)
    a.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="0")])
    a.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="1")])
    a.close(timeout=5.0)

    b = AgentLog(collection=coll, durable_step=True, flush_on_exit=False)
    b.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="2")])
    b.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="3")])
    b.close(timeout=5.0)

    steps = sorted(d["step"] for d in coll.find({"thread_id": "t1"}))
    assert steps == [0, 1, 2, 3], "step reset on restart — durable counter not honored"


# NFR-300: record() stays non-blocking even with durable_step on and the
# counter collection unreachable (the round-trip is on the worker thread).
def test_TC_306_durable_step_record_non_blocking(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    counters = coll.database[f"{coll.name}_counters"]
    with patch.object(counters, "find_one_and_update", side_effect=PyMongoError("down")):
        log = AgentLog(collection=coll, durable_step=True, flush_on_exit=False)
        t0 = time.monotonic()
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
        assert time.monotonic() - t0 < 0.2, "record() blocked on the durable counter round-trip"
        log.close(timeout=5.0)


# REQ-307: a single engine shared across threads never duplicates step
# (in-memory path, lock-guarded).
def test_TC_307_concurrent_record_unique_steps(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)

    def worker(i: int) -> None:
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.flush_for_tests(timeout=5.0)
    steps = sorted(d["step"] for d in coll.find({"thread_id": "t1"}))
    assert steps == list(range(10)), "concurrent record() duplicated or skipped a step"
    log.close(timeout=5.0)
