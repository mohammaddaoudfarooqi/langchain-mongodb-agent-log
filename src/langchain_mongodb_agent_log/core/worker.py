"""Background worker for agent-log persistence.

Spec REQ-018..022: the agent super-step must not block on the MongoDB write
or the embedding round-trip. The worker drains a bounded queue on a single
daemon thread, preserving FIFO order per ``thread_id``.

Why a single daemon thread:
- FIFO ordering per ``thread_id`` is preserved trivially with one consumer.
- Multiple workers would require per-``thread_id`` partitioning which adds
  state without a measurable throughput win at our default queue sizes.
- The daemon flag means the worker never blocks process shutdown; pending
  docs are lost on hard exit, which is acceptable for an audit-log surface
  (the agent turn already returned successfully to the user).
"""
from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any, Protocol

from pymongo.errors import PyMongoError

from .._logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from pymongo.collection import Collection


_log = get_logger()


class _Worker(Protocol):
    def enqueue(self, doc: dict[str, Any]) -> None: ...
    def flush_for_tests(self, timeout: float = 5.0) -> None: ...


class _DaemonWorker:
    """Drain a bounded queue on a daemon thread."""

    def __init__(self, collection: Collection[Any], *, queue_maxsize: int = 256) -> None:
        self._coll = collection
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=queue_maxsize
        )
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def enqueue(self, doc: dict[str, Any]) -> None:
        self._ensure_started()
        try:
            self._queue.put_nowait(doc)
        except queue.Full:
            _log.warning(
                "agent_log queue full; dropping doc thread=%s step=%s",
                doc.get("thread_id"),
                doc.get("step"),
            )

    def flush_for_tests(self, timeout: float = 5.0) -> None:
        # ``Queue.join`` returns when every item put has had ``task_done``
        # called. The ``timeout`` arg is accepted for API parity with a
        # future bounded-wait variant.
        _ = timeout
        self._queue.join()

    def _ensure_started(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            t = threading.Thread(
                target=self._loop,
                name="agent-log-worker",
                daemon=True,
            )
            t.start()
            self._thread = t

    def _loop(self) -> None:
        while True:
            doc = self._queue.get()
            try:
                if doc is None:
                    return  # shutdown sentinel; not currently emitted
                self._embed_then_insert(doc)
            except Exception as exc:  # pragma: no cover - last-resort guard
                _log.warning("agent_log worker unexpected: %s", exc)
            finally:
                self._queue.task_done()

    def _embed_then_insert(self, doc: dict[str, Any]) -> None:
        embedder = doc.pop("__embedder", None)
        search_text = doc.pop("__search_text", None)
        if embedder is not None and search_text:
            try:
                doc["agent_log_embedding"] = embedder.embed_query(search_text)
                doc["agent_log_text"] = search_text
            except Exception as exc:
                _log.warning("agent_log embedding failed: %s", exc)
        try:
            self._coll.insert_one(doc)
        except PyMongoError as exc:
            _log.warning("agent_log insert failed: %s", exc)


def build_worker(collection: Collection[Any], *, queue_maxsize: int = 256) -> _Worker:
    return _DaemonWorker(collection, queue_maxsize=queue_maxsize)


__all__ = ["build_worker"]
