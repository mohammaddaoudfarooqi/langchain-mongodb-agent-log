"""Worker tests — REQ-010, REQ-011, REQ-013, REQ-018..022, REQ-040, INV-001..003."""
from __future__ import annotations

import logging
import time
from typing import Any
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from pymongo.errors import PyMongoError


class _FakeEmbedder:
    """Returns a deterministic 8-d vector. Records calls."""

    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.raise_on_call = raise_on_call
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.raise_on_call:
            raise RuntimeError("embedder boom")
        return [float(i) for i in range(8)]


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


# REQ-018 / INV-003: record() returns < 50 ms even when insert_one blocks
def test_TC_018_record_does_not_block_on_slow_insert(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    slow_calls: list[float] = []

    real_insert = coll.insert_one

    def slow_insert(doc: Any, *args: Any, **kwargs: Any) -> Any:
        slow_calls.append(time.monotonic())
        time.sleep(0.5)
        return real_insert(doc, *args, **kwargs)

    with patch.object(coll, "insert_one", side_effect=slow_insert):
        log = AgentLog(collection=coll)
        t0 = time.monotonic()
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="hi")])
        elapsed = time.monotonic() - t0
        # If the worker is async, record() should not have waited for the
        # 0.5s insert — generous bound to absorb CI noise.
        assert elapsed < 0.2, f"record() blocked for {elapsed:.3f}s"
        log.flush_for_tests()


# REQ-019: FIFO order per thread under load
def test_TC_019_fifo_order_per_thread(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll)
    for i in range(20):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    log.flush_for_tests()
    docs = list(coll.find({"thread_id": "t1"}).sort("step", 1))
    assert [d["step"] for d in docs] == list(range(20))


# REQ-020: queue full → warn + drop, no raise, no block
def test_TC_020_queue_full_drops_with_warning(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log import AgentLog

    # tiny queue so we hit the drop
    log = AgentLog(collection=coll, queue_maxsize=2)

    # Block the worker while we shove docs in
    real_insert = coll.insert_one
    block = True

    def maybe_block(doc: Any, *args: Any, **kwargs: Any) -> Any:
        while block:
            time.sleep(0.005)
        return real_insert(doc, *args, **kwargs)

    with patch.object(coll, "insert_one", side_effect=maybe_block):
        with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
            for i in range(50):
                log.record(
                    thread_id="t1",
                    user_id="u1",
                    messages=[_msg(type="human", content=str(i))],
                )
        # release the worker
        block = False
        log.flush_for_tests(timeout=5.0)

    # Some "queue full" warning was logged
    full_msgs = [r for r in caplog.records if "queue full" in r.getMessage()]
    assert full_msgs, "expected at least one 'queue full' warning"


# REQ-021: flush_for_tests blocks until queue drains
def test_TC_021_flush_blocks_until_drain(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll)
    for i in range(10):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    log.flush_for_tests()
    assert coll.count_documents({}) == 10


# REQ-022 / INV-001: PyMongoError swallowed
def test_TC_022_pymongo_error_swallowed(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log import AgentLog

    with patch.object(coll, "insert_one", side_effect=PyMongoError("down")):
        log = AgentLog(collection=coll)
        with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
            # record() must not raise
            log.record(
                thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")]
            )
            log.flush_for_tests()

    assert any("insert failed" in r.getMessage() for r in caplog.records)


# REQ-013 / INV-002: embedder failure does not drop the doc
def test_TC_013_embedder_failure_keeps_doc(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, embeddings=_FakeEmbedder(raise_on_call=True))

    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[
            _msg(type="human", content="Q"),
            _msg(type="ai", content="A"),
        ],
    )
    log.flush_for_tests()
    doc = coll.find_one({})
    assert doc is not None
    assert "agent_log_embedding" not in doc
    assert "agent_log_text" not in doc


# REQ-010: final super-step → embedder fires once, both fields populated
def test_TC_010_final_step_embed(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    fake = _FakeEmbedder()
    log = AgentLog(collection=coll, embeddings=fake)

    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[
            _msg(type="human", content="Q"),
            _msg(type="ai", content="A"),  # no tool_calls -> final
        ],
    )
    log.flush_for_tests()
    doc = coll.find_one({})
    assert "Q" in fake.calls[0]
    assert "A" in fake.calls[0]
    assert doc["agent_log_text"]
    assert isinstance(doc["agent_log_embedding"], list)
    assert len(doc["agent_log_embedding"]) == 8


# REQ-011a: not-final step → no embedder call
def test_TC_011a_non_final_step_no_embed(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    fake = _FakeEmbedder()
    log = AgentLog(collection=coll, embeddings=fake)

    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[
            _msg(type="human", content="Q"),
            _msg(type="ai", content="", tool_calls=[{"name": "x", "args": {}}]),
        ],
    )
    log.flush_for_tests()
    assert fake.calls == []
    doc = coll.find_one({})
    assert "agent_log_embedding" not in doc


# REQ-011b: no embedder configured → no fields added
def test_TC_011b_no_embedder_configured(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll)  # no embeddings
    log.record(
        thread_id="t1",
        user_id="u1",
        messages=[
            _msg(type="human", content="Q"),
            _msg(type="ai", content="A"),
        ],
    )
    log.flush_for_tests()
    doc = coll.find_one({})
    assert "agent_log_embedding" not in doc
    assert "agent_log_text" not in doc


# REQ-040: warning lines use the named logger
def test_TC_040_named_logger_used(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log import AgentLog

    with patch.object(coll, "insert_one", side_effect=PyMongoError("x")):
        log = AgentLog(collection=coll)
        with caplog.at_level(logging.WARNING):
            log.record(
                thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")]
            )
            log.flush_for_tests()

    assert any(
        r.name == "langchain_mongodb_agent_log" for r in caplog.records
    ), "warning was not logged under the named logger"
