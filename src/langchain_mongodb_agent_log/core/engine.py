"""``AgentLog`` engine.

The engine projects agent state into a decoded JSON document and hands it
to the worker for persistence. All adapters funnel through ``record(...)``;
the engine knows nothing about middleware, callbacks, or graph nodes.

For v0.1 the persistence path is **synchronous in tests** by virtue of
``flush_for_tests()`` blocking on the worker queue. The hot path itself is
non-blocking because the worker drains in a background thread (T46).
"""
from __future__ import annotations

import atexit
import contextlib
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .._logging import get_logger
from .projection import (
    build_search_text,
    is_final_step,
    project_files,
    project_messages,
    project_todos,
)

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.embeddings import Embeddings
    from pymongo.collection import Collection


_log = get_logger()


class AgentLog:
    """Append-only agent activity log backed by a MongoDB collection.

    Args:
        collection: The pymongo collection to write log documents into.
        embeddings: Optional ``Embeddings`` for hybrid-search enrichment.
            When supplied, the engine adds ``agent_log_text`` and
            ``agent_log_embedding`` fields on the *final* super-step of
            each turn.
        fs_write_tools: Tool names whose calls indicate a filesystem
            mutation. Defaults to ``{"write_file", "edit_file"}``.
        max_content_bytes: Truncate per-message content above this size.
            Default 15 MiB (just under MongoDB's 16 MiB BSON limit).
        max_search_text_bytes: Cap the joint human+final-AI text fed to
            the embedder. Default 8 KiB.
        queue_maxsize: Worker queue capacity. Default 256.
    """

    def __init__(
        self,
        collection: Collection[Any],
        embeddings: Embeddings | None = None,
        *,
        fs_write_tools: frozenset[str] = frozenset({"write_file", "edit_file"}),
        max_content_bytes: int = 15 * 1024 * 1024,
        max_search_text_bytes: int = 8 * 1024,
        queue_maxsize: int = 256,
        flush_on_exit: bool = True,
        durable_step: bool = False,
        counter_collection: Collection[Any] | None = None,
    ) -> None:
        self._collection = collection
        self._embeddings = embeddings
        self.fs_write_tools = fs_write_tools
        self.max_content_bytes = max_content_bytes
        self.max_search_text_bytes = max_search_text_bytes
        self.queue_maxsize = queue_maxsize
        self.durable_step = durable_step

        self._step_counter: dict[str, int] = {}
        self._step_lock = threading.Lock()
        self._closed = False
        self._closed_warned = False
        # REQ-319: thread_ids already warned about an un-searchable final step.
        self._search_warned: set[str] = set()

        # REQ-306: when durable_step is on, ``step`` comes from a persisted
        # per-thread atomic counter assigned on the worker thread (off the
        # agent hot path). Counter collection defaults to ``<name>_counters``.
        self._counter_collection: Collection[Any] | None = None
        if durable_step:
            self._counter_collection = counter_collection or collection.database[
                f"{collection.name}_counters"
            ]

        from .worker import build_worker

        self._worker = build_worker(
            collection,
            queue_maxsize=queue_maxsize,
            counter_collection=self._counter_collection,
        )

        # REQ-303: best-effort drain on interpreter shutdown so a process
        # that forgets to call close() still flushes the worker queue.
        if flush_on_exit:
            atexit.register(self._atexit_flush)

    def record(
        self,
        *,
        thread_id: str,
        user_id: str,
        messages: Sequence[Any],
        todos: Sequence[Mapping[str, Any]] | None = None,
        agent_name: str | None = None,
        correlation_id: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        """Project state and enqueue one log document. Non-blocking.

        ``ts`` overrides the document timestamp (default ``now`` UTC); useful
        for deterministic seeding (REQ-318).
        """
        if self._closed:
            if not self._closed_warned:
                self._closed_warned = True
                _log.warning("agent_log record() called on a closed engine; ignoring")
            return
        if not thread_id or not user_id:
            return

        messages_proj = project_messages(messages, cap=self.max_content_bytes)
        todos_proj = project_todos(list(todos) if todos is not None else [])
        files_proj = project_files(messages, fs_write_tools=self.fs_write_tools)

        doc: dict[str, Any] = {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_name": agent_name or "main",
            "ts": ts if ts is not None else datetime.now(timezone.utc),
            "messages": messages_proj,
            "todos": todos_proj,
            "files_touched": files_proj,
            "correlation_id": correlation_id or "",
        }

        if self.durable_step:
            # REQ-306: the worker assigns ``step``/``parent_step`` from the
            # persisted counter, keeping the counter round-trip off this hot
            # path (NFR-300).
            doc["__assign_step"] = thread_id
        else:
            # REQ-307: guard the in-memory counter so a shared engine can't
            # duplicate or skip ``step`` under concurrent record() callers.
            with self._step_lock:
                step = self._step_counter.get(thread_id, 0)
                self._step_counter[thread_id] = step + 1
            doc["step"] = step
            doc["parent_step"] = step - 1 if step > 0 else None

        # Defer embedding to the worker so the hot path stays fast.
        if self._embeddings is not None and is_final_step(messages_proj):
            text = build_search_text(messages_proj, cap=self.max_search_text_bytes)
            if text:
                doc["__embedder"] = self._embeddings
                doc["__search_text"] = text
            elif thread_id not in self._search_warned:
                # REQ-319: a final step with no embeddable text (single-role
                # turn) is invisible to vector search. Warn once per thread.
                self._search_warned.add(thread_id)
                _log.warning(
                    "agent_log: final step for thread=%s has no searchable text "
                    "(needs both a human and an ai message); doc stored but not "
                    "vector-searchable",
                    thread_id,
                )

        self._worker.enqueue(doc)

    def flush(self, timeout: float = 5.0) -> bool:
        """Bounded drain of the worker queue. Does not stop the worker.

        Returns ``True`` if the queue drained within ``timeout``, else
        ``False``. Safe to call repeatedly (REQ-301).
        """
        return self._worker.drain(timeout)

    def close(self, timeout: float = 5.0) -> bool:
        """Drain the queue, stop the worker, and refuse further writes.

        Returns ``True`` if the queue drained and the worker stopped within
        ``timeout``. Idempotent (REQ-300/302).
        """
        self._closed = True
        return self._worker.close(timeout)

    def stats(self) -> dict[str, Any]:
        """Return queue + throughput counters with no database round-trip.

        Keys: ``queue_depth``, ``queue_capacity``, ``worker_alive``,
        ``enqueued``, ``written``, ``dropped``, ``embed_failures``,
        ``write_failures``, ``last_write_ts`` (REQ-304).
        """
        return self._worker.stats()

    def get_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict[str, Any]]:
        """Return a thread's log documents ordered by ``(ts, step)``.

        Non-semantic read backed by ``agent_log_thread_ts_idx``. WHEN
        ``user_id`` is supplied it further filters (defense in depth for
        multi-tenant reads, REQ-308). Returns ``[]`` on no match (REQ-310).
        """
        query: dict[str, Any] = {"thread_id": thread_id}
        if user_id is not None:
            query["user_id"] = user_id
        direction = 1 if ascending else -1
        return self._read(query, sort=[("ts", direction), ("step", direction)], limit=limit)

    def get_by_correlation_id(
        self, correlation_id: str, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return all log documents for a correlation id, ordered by ``ts`` (REQ-309)."""
        return self._read(
            {"correlation_id": correlation_id}, sort=[("ts", 1)], limit=limit
        )

    def _read(
        self,
        query: dict[str, Any],
        *,
        sort: list[tuple[str, int]],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        cursor = self._collection.find(query).sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        out: list[dict[str, Any]] = []
        for d in cursor:
            d = dict(d)
            if "_id" in d:
                d["_id"] = str(d["_id"])
            out.append(d)
        return out

    def flush_for_tests(self, timeout: float = 5.0) -> None:
        """Block until the worker queue drains. Test-only helper.

        Honors ``timeout`` (BUG-302): raises :class:`TimeoutError` if the
        queue has not drained within ``timeout`` seconds.
        """
        if not self._worker.drain(timeout):
            raise TimeoutError(
                f"agent_log queue did not drain within {timeout}s"
            )

    def _atexit_flush(self) -> None:
        """Best-effort drain on interpreter shutdown; never raises (REQ-303)."""
        with contextlib.suppress(Exception):  # shutdown is best-effort
            self.close(timeout=2.0)
