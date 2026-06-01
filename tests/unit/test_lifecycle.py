"""Worker lifecycle tests — BUG-302, REQ-300, REQ-301, REQ-302, REQ-303.

Covers the bounded-drain / close / flush surface added in v0.3.
"""
from __future__ import annotations

import logging
import threading
import time
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


# REQ-300: close() drains the queue and stops the worker, idempotently.
def test_TC_300_close_drains_and_stops(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    for i in range(10):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content=str(i))])
    drained = log.close(timeout=5.0)
    assert drained is True
    assert coll.count_documents({}) == 10
    # Worker is no longer alive after a successful close.
    assert log.stats()["worker_alive"] is False


def test_TC_300_close_idempotent(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
    assert log.close(timeout=5.0) is True
    # Second close must not raise and must report drained.
    assert log.close(timeout=5.0) is True


# REQ-301: flush(timeout) is a bounded drain that does NOT stop the worker.
def test_TC_301_flush_bounded_then_drains(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    release = threading.Event()
    real_insert = coll.insert_one

    def blocking_insert(doc: Any, *a: Any, **k: Any) -> Any:
        release.wait(5.0)
        return real_insert(doc, *a, **k)

    with patch.object(coll, "insert_one", side_effect=blocking_insert):
        log = AgentLog(collection=coll, flush_on_exit=False)
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
        # Worker is wedged in insert -> bounded flush times out and returns False.
        assert log.flush(timeout=0.1) is False
        release.set()
        # Now it drains within the bound.
        assert log.flush(timeout=5.0) is True
    # Worker still alive after a plain flush (flush != close).
    assert log.stats()["worker_alive"] is True
    log.close(timeout=5.0)


# BUG-302: flush_for_tests honors its timeout and raises on expiry.
def test_TC_302_flush_for_tests_raises_on_timeout(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    release = threading.Event()
    real_insert = coll.insert_one

    def blocking_insert(doc: Any, *a: Any, **k: Any) -> Any:
        release.wait(5.0)
        return real_insert(doc, *a, **k)

    with patch.object(coll, "insert_one", side_effect=blocking_insert):
        log = AgentLog(collection=coll, flush_on_exit=False)
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            log.flush_for_tests(timeout=0.1)
        assert time.monotonic() - t0 < 2.0, "flush_for_tests did not honor the timeout bound"
        release.set()
        log.flush_for_tests(timeout=5.0)  # now returns normally


def test_TC_302_flush_for_tests_returns_when_drained(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
    assert log.flush_for_tests(timeout=5.0) is None
    assert coll.count_documents({}) == 1


# REQ-302: writes after close() are ignored and warn once.
def test_TC_302_record_after_close_noops(coll: Any, caplog: pytest.LogCaptureFixture) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, flush_on_exit=False)
    log.close(timeout=5.0)
    with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="y")])
    # No new worker spawned, nothing written.
    assert coll.count_documents({}) == 0
    assert log.stats()["worker_alive"] is False
    closed_warnings = [r for r in caplog.records if "closed" in r.getMessage().lower()]
    assert len(closed_warnings) == 1, "expected exactly one closed-engine warning"


# REQ-303: atexit flush is registered by default, opt-out honored.
def test_TC_303_atexit_registered_by_default(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    with patch("atexit.register") as reg:
        AgentLog(collection=coll)
        assert reg.called, "atexit flush should register by default"


def test_TC_303_atexit_opt_out(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    with patch("atexit.register") as reg:
        AgentLog(collection=coll, flush_on_exit=False)
        assert not reg.called, "flush_on_exit=False must not register atexit"
