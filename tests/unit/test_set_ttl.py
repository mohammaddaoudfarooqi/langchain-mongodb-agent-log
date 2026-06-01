"""TTL admin + search-index configurability — REQ-311, REQ-314, REQ-317."""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest


@pytest.fixture
def coll() -> Any:
    return mongomock.MongoClient()["t"]["agent_log"]


# REQ-311: ensure_search_indexes forwards overridden index names to the DDL.
def test_TC_311_search_index_names_forwarded() -> None:
    from langchain_mongodb_agent_log import ensure_search_indexes

    mock = MagicMock()
    ensure_search_indexes(mock, embeddings_dim=8, vector_index="vx", search_index="sx")
    names = {c.args[0]["name"] for c in mock.create_search_index.call_args_list}
    assert names == {"vx", "sx"}


# REQ-314: the lexical $search mapping includes agent_name.
def test_TC_314_search_mapping_includes_agent_name() -> None:
    from langchain_mongodb_agent_log import ensure_search_indexes

    mock = MagicMock()
    ensure_search_indexes(mock, embeddings_dim=8)
    search_call = next(
        c for c in mock.create_search_index.call_args_list if c.args[0]["type"] == "search"
    )
    fields = search_call.args[0]["definition"]["mappings"]["fields"]
    assert "agent_name" in fields
    assert "agent_log_text" in fields  # original field preserved


# REQ-317: set_ttl is part of the public API.
def test_TC_317_set_ttl_public_api() -> None:
    import langchain_mongodb_agent_log as m

    assert "set_ttl" in m.__all__
    assert callable(m.set_ttl)


# REQ-317: set_ttl warns-and-falls-back on a deployment without collMod.
def test_TC_317_set_ttl_warn_skip_on_mongomock(
    coll: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from langchain_mongodb_agent_log import set_ttl

    with caplog.at_level(logging.WARNING, logger="langchain_mongodb_agent_log"):
        set_ttl(coll, 3600)  # must not raise
    assert any("collmod" in r.getMessage().lower() for r in caplog.records)


# REQ-317: set_ttl(None) removes the TTL index.
def test_TC_317_set_ttl_none_drops(coll: Any) -> None:
    from langchain_mongodb_agent_log import ensure_agent_log_indexes, set_ttl

    ensure_agent_log_indexes(coll, ttl_seconds=3600)
    assert "agent_log_ts_ttl_idx" in {i["name"] for i in coll.list_indexes()}
    set_ttl(coll, None)
    assert "agent_log_ts_ttl_idx" not in {i["name"] for i in coll.list_indexes()}
