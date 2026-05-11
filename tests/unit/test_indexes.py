"""Index helper tests — REQ-014..017."""
from __future__ import annotations

import logging
from typing import Any

import mongomock
import pytest


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


# REQ-014: regular indexes are created
def test_TC_014_regular_indexes_created(coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes

    ensure_agent_log_indexes(coll)
    names = {idx["name"] for idx in coll.list_indexes()}
    expected = {
        "_id_",
        "agent_log_thread_step_idx",
        "agent_log_thread_ts_idx",
        "agent_log_user_ts_idx",
    }
    assert expected.issubset(names)


# REQ-014b: TTL index added when ttl_seconds supplied
def test_TC_014b_ttl_index_when_configured(coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes

    ensure_agent_log_indexes(coll, ttl_seconds=3600)
    ttl_idx = next(
        (i for i in coll.list_indexes() if i["name"] == "agent_log_ts_ttl_idx"),
        None,
    )
    assert ttl_idx is not None
    assert ttl_idx.get("expireAfterSeconds") == 3600


# REQ-014: no TTL index when ttl_seconds is None
def test_TC_014c_no_ttl_when_unset(coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes

    ensure_agent_log_indexes(coll)
    names = {i["name"] for i in coll.list_indexes()}
    assert "agent_log_ts_ttl_idx" not in names


# REQ-016: re-running is a no-op (no exception)
def test_TC_016_idempotent(coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes

    ensure_agent_log_indexes(coll, ttl_seconds=3600)
    ensure_agent_log_indexes(coll, ttl_seconds=3600)  # second call must not raise
    names = {i["name"] for i in coll.list_indexes()}
    assert "agent_log_thread_step_idx" in names


# REQ-017: ensure_search_indexes warns and returns on mongomock (no Atlas DDL support)
def test_TC_017_search_indexes_skip_on_mongomock(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log import ensure_search_indexes

    with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
        ensure_search_indexes(coll, embeddings_dim=1024)

    # Either a "skipped" warning or a graceful no-op.
    assert any(
        "search index" in r.getMessage().lower() for r in caplog.records
    ), "expected a skipped/warning log line for unsupported deployment"
