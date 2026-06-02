"""Non-semantic ordered read API — REQ-308, REQ-309, REQ-310, INV-301."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


def _seed(coll: Any) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Insert out of ts order to prove sorting, not insertion order.
    coll.insert_many(
        [
            {"thread_id": "t1", "user_id": "u1", "step": 2, "ts": base + timedelta(minutes=2),
             "correlation_id": "c-1", "messages": []},
            {"thread_id": "t1", "user_id": "u1", "step": 0, "ts": base,
             "correlation_id": "c-1", "messages": []},
            {"thread_id": "t1", "user_id": "u1", "step": 1, "ts": base + timedelta(minutes=1),
             "correlation_id": "c-2", "messages": []},
            {"thread_id": "t1", "user_id": "u2", "step": 0, "ts": base + timedelta(minutes=3),
             "correlation_id": "c-3", "messages": []},
            {"thread_id": "t2", "user_id": "u1", "step": 0, "ts": base + timedelta(minutes=4),
             "correlation_id": "c-1", "messages": []},
        ]
    )


# REQ-308: get_thread returns a thread ordered by (ts, step).
def test_TC_308_get_thread_orders_by_ts(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    _seed(coll)
    log = AgentLog(collection=coll, flush_on_exit=False)
    docs = log.get_thread("t1")
    assert [d["step"] for d in docs] == [2, 0, 1, 0] or [d["step"] for d in docs] == [0, 1, 2, 0]
    # Ascending by ts: the base-ts doc (step 0, u1) comes before step 2.
    assert [d["user_id"] for d in docs][0] == "u1"
    ts_values = [d["ts"] for d in docs]
    assert ts_values == sorted(ts_values), "get_thread not ordered ascending by ts"


def test_TC_308_get_thread_descending(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    _seed(coll)
    log = AgentLog(collection=coll, flush_on_exit=False)
    docs = log.get_thread("t1", ascending=False, limit=2)
    assert len(docs) == 2
    ts_values = [d["ts"] for d in docs]
    assert ts_values == sorted(ts_values, reverse=True)


# REQ-308: user_id filter narrows results (defense in depth).
def test_TC_308_get_thread_user_filter(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    _seed(coll)
    log = AgentLog(collection=coll, flush_on_exit=False)
    docs = log.get_thread("t1", user_id="u2")
    assert len(docs) == 1
    assert docs[0]["user_id"] == "u2"


# REQ-310: empty result returns [] (never raises).
def test_TC_308_get_thread_empty(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    assert log.get_thread("nope") == []


# REQ-309: get_by_correlation_id orders by ts across threads.
def test_TC_309_get_by_correlation_id(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    _seed(coll)
    log = AgentLog(collection=coll, flush_on_exit=False)
    docs = log.get_by_correlation_id("c-1")
    # c-1 spans t1(step2), t1(step0), t2(step0) -> 3 docs, ts ascending.
    assert len(docs) == 3
    ts_values = [d["ts"] for d in docs]
    assert ts_values == sorted(ts_values)


# REQ-310: _id is coerced to str on read.
def test_TC_310_id_coerced_to_str(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    _seed(coll)
    log = AgentLog(collection=coll, flush_on_exit=False)
    docs = log.get_thread("t1")
    assert all(isinstance(d["_id"], str) for d in docs)
