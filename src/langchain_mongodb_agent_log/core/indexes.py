"""Idempotent index helpers for the agent-log collection.

Two entry points:

- :func:`ensure_agent_log_indexes` — regular B-tree indexes (and an
  optional TTL index). Safe on every MongoDB deployment, including
  mongomock.
- :func:`ensure_search_indexes` — Atlas Search + Atlas Vector Search
  index DDL. Skips with a warning on deployments that don't support
  ``createSearchIndex`` (e.g., mongomock).

Both helpers no-op cleanly on re-run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from pymongo.collection import Collection


_log = get_logger()


_INDEX_NAME_THREAD_STEP = "agent_log_thread_step_idx"
_INDEX_NAME_THREAD_TS = "agent_log_thread_ts_idx"
_INDEX_NAME_USER_TS = "agent_log_user_ts_idx"
_INDEX_NAME_TTL = "agent_log_ts_ttl_idx"

SEARCH_INDEX_NAME = "agent_log_search_idx"
VECTOR_INDEX_NAME = "agent_log_vector_idx"


def ensure_agent_log_indexes(
    collection: Collection[Any],
    *,
    ttl_seconds: int | None = None,
) -> None:
    """Create the regular indexes used by the log collection.

    Args:
        collection: The agent-log collection.
        ttl_seconds: When supplied, also creates a TTL index on ``ts``
            so docs older than ``ttl_seconds`` are removed by the
            MongoDB background reaper. Set to ``None`` (default) to
            skip the TTL index.
    """
    collection.create_index(
        [("thread_id", 1), ("step", 1)],
        name=_INDEX_NAME_THREAD_STEP,
    )
    collection.create_index(
        [("thread_id", 1), ("ts", -1)],
        name=_INDEX_NAME_THREAD_TS,
    )
    collection.create_index(
        [("user_id", 1), ("ts", -1)],
        name=_INDEX_NAME_USER_TS,
    )
    if ttl_seconds is not None:
        collection.create_index(
            [("ts", 1)],
            name=_INDEX_NAME_TTL,
            expireAfterSeconds=ttl_seconds,
        )


def ensure_search_indexes(
    collection: Collection[Any],
    *,
    embeddings_dim: int,
) -> None:
    """Create Atlas Search + Atlas Vector Search indexes idempotently.

    On deployments that don't support ``createSearchIndex`` (mongomock,
    older MongoDB community without search), this function emits a
    single warning per missing index and returns. It does not raise.

    Args:
        collection: The agent-log collection.
        embeddings_dim: Dimension of the embedding vector. Must match
            the vectors actually stored on the documents.
    """
    vector_def = {
        "fields": [
            {
                "type": "vector",
                "path": "agent_log_embedding",
                "numDimensions": embeddings_dim,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "user_id"},
        ]
    }
    search_def = {
        "mappings": {
            "dynamic": False,
            "fields": {
                "agent_log_text": {"type": "string"},
                "user_id": {"type": "string"},
            },
        }
    }
    _safe_create_search_index(
        collection, name=VECTOR_INDEX_NAME, definition=vector_def, type_="vectorSearch"
    )
    _safe_create_search_index(
        collection, name=SEARCH_INDEX_NAME, definition=search_def, type_="search"
    )


def _safe_create_search_index(
    collection: Collection[Any],
    *,
    name: str,
    definition: dict[str, Any],
    type_: str,
) -> None:
    """Call ``create_search_index`` if available; warn-and-skip otherwise."""
    fn = getattr(collection, "create_search_index", None)
    if not callable(fn):
        _log.warning(
            "search index %s skipped: deployment does not support createSearchIndex",
            name,
        )
        return
    try:
        fn({"name": name, "type": type_, "definition": definition})
    except Exception as exc:  # noqa: BLE001 — Atlas can raise pymongo.errors.OperationFailure
        if _is_already_exists(exc):
            return
        _log.warning("search index %s creation skipped: %s", name, exc)


def _is_already_exists(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "already exists" in msg or "duplicate" in msg:
        return True
    code = getattr(exc, "code", None)
    return code in (68, 86)  # IndexAlreadyExists, IndexKeySpecsConflict-ish
