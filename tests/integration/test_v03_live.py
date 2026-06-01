"""Atlas-gated live tests for the v0.3 surface — REQ-306/308/317, mock parity.

Each test skips cleanly when ``ATLAS_URI`` is unset so
``uv run pytest -m integration`` is a no-op without live infra. These exist to
prove the mongomock fakes match real MongoDB for the methods v0.3 relies on:
``find_one_and_update(return_document=AFTER)`` (durable step) and ``collMod``
(set_ttl).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pymongo import MongoClient

pytestmark = pytest.mark.integration


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
def live_coll(atlas_uri: str) -> Any:
    client: MongoClient[Any] = MongoClient(atlas_uri)
    db = client["agent_log_it"]
    name = "v03_live"
    db[name].drop()
    db[f"{name}_counters"].drop()
    yield db[name]
    db[name].drop()
    db[f"{name}_counters"].drop()
    client.close()


# TC-INT-306 / TC-PARITY-306: durable step survives a "restart" against real Atlas.
def test_TC_INT_306_durable_step_live(live_coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    a = AgentLog(collection=live_coll, durable_step=True, flush_on_exit=False)
    a.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="0")])
    a.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="1")])
    assert a.close(timeout=10.0)

    b = AgentLog(collection=live_coll, durable_step=True, flush_on_exit=False)
    b.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="2")])
    assert b.close(timeout=10.0)

    steps = sorted(d["step"] for d in b.get_thread("t1"))
    assert steps == [0, 1, 2]


# TC-INT-308: get_thread ordered by ts against real Atlas.
def test_TC_INT_308_get_thread_order_live(live_coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=live_coll, flush_on_exit=False)
    for i in range(5):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    assert log.flush(timeout=10.0)
    docs = log.get_thread("t1")
    ts_values = [d["ts"] for d in docs]
    assert ts_values == sorted(ts_values)
    assert all(isinstance(d["_id"], str) for d in docs)
    log.close(timeout=10.0)


# TC-INT-317 / TC-PARITY-317: set_ttl actually mutates expireAfterSeconds via collMod.
def test_TC_INT_317_set_ttl_live(live_coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes, set_ttl

    ensure_agent_log_indexes(live_coll, ttl_seconds=3600)
    set_ttl(live_coll, 7200)
    ttl_idx = next(
        (i for i in live_coll.list_indexes() if i["name"] == "agent_log_ts_ttl_idx"),
        None,
    )
    assert ttl_idx is not None
    assert ttl_idx.get("expireAfterSeconds") == 7200
    set_ttl(live_coll, None)
    assert "agent_log_ts_ttl_idx" not in {i["name"] for i in live_coll.list_indexes()}
