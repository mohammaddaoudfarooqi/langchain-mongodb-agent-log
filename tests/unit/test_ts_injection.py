"""Timestamp injection + single-role warning — REQ-318, REQ-319."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest


class _FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 8


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


# REQ-318: explicit ts is stored verbatim.
def test_TC_318_explicit_ts_stored(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    fixed = datetime(2020, 5, 17, 12, 0, 0, tzinfo=UTC)
    log = AgentLog(collection=coll, flush_on_exit=False)
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")], ts=fixed)
    log.flush_for_tests(timeout=5.0)
    doc = coll.find_one({})
    # BSON datetimes round-trip as naive UTC at millisecond precision (true on
    # real Atlas too), so normalize tz before comparing.
    stored = doc["ts"]
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert stored == fixed
    log.close(timeout=5.0)


# REQ-318: default ts is recent UTC.
def test_TC_318_default_ts_is_now(coll: Any) -> None:
    from langchain_mongodb_agent_log import AgentLog

    before = datetime.now(UTC)
    log = AgentLog(collection=coll, flush_on_exit=False)
    log.record(thread_id="t1", user_id="u1", messages=[_msg(type="human", content="x")])
    log.flush_for_tests(timeout=5.0)
    doc = coll.find_one({})
    after = datetime.now(UTC)
    ts = doc["ts"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    # BSON truncates to milliseconds; allow a 1s window to absorb that + CI noise.
    assert before - timedelta(seconds=1) <= ts <= after + timedelta(seconds=1)
    log.close(timeout=5.0)


# REQ-319: a final step with no human message (single-role) warns once per thread.
def test_TC_319_single_role_warns_once(coll: Any, caplog: pytest.LogCaptureFixture) -> None:
    from langchain_mongodb_agent_log import AgentLog

    log = AgentLog(collection=coll, embeddings=_FakeEmbedder(), flush_on_exit=False)
    with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
        # AI-only final turn (no human) twice on the same thread.
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="ai", content="A1")])
        log.record(thread_id="t1", user_id="u1", messages=[_msg(type="ai", content="A2")])
        log.flush_for_tests(timeout=5.0)
    warns = [r for r in caplog.records if "not searchable" in r.getMessage().lower()
             or "no searchable text" in r.getMessage().lower()]
    assert len(warns) == 1, f"expected exactly one single-role warning, got {len(warns)}"
    # The docs are still written (INV-002 preserved).
    assert coll.count_documents({}) == 2
    log.close(timeout=5.0)
