"""``AgentLog`` engine.

The engine projects agent state into a decoded JSON document and hands it
to the worker for persistence. All adapters funnel through ``record(...)``;
the engine knows nothing about middleware, callbacks, or graph nodes.

For v0.1 the persistence path is **synchronous in tests** by virtue of
``flush_for_tests()`` blocking on the worker queue. The hot path itself is
non-blocking because the worker drains in a background thread (T46).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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
    ) -> None:
        self._collection = collection
        self._embeddings = embeddings
        self.fs_write_tools = fs_write_tools
        self.max_content_bytes = max_content_bytes
        self.max_search_text_bytes = max_search_text_bytes
        self.queue_maxsize = queue_maxsize

        self._step_counter: dict[str, int] = {}

        # The real worker is wired in T46. For T45 we use a stub that
        # writes synchronously so doc-shape tests can read the collection.
        from .worker import build_worker

        self._worker = build_worker(collection, queue_maxsize=queue_maxsize)

    def record(
        self,
        *,
        thread_id: str,
        user_id: str,
        messages: Sequence[Any],
        todos: Sequence[Mapping[str, Any]] | None = None,
        agent_name: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Project state and enqueue one log document. Non-blocking."""
        if not thread_id or not user_id:
            return

        step = self._step_counter.get(thread_id, 0)
        self._step_counter[thread_id] = step + 1

        messages_proj = project_messages(messages, cap=self.max_content_bytes)
        todos_proj = project_todos(list(todos) if todos is not None else [])
        files_proj = project_files(messages, fs_write_tools=self.fs_write_tools)

        doc: dict[str, Any] = {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_name": agent_name or "main",
            "step": step,
            "ts": datetime.now(timezone.utc),
            "parent_step": step - 1 if step > 0 else None,
            "messages": messages_proj,
            "todos": todos_proj,
            "files_touched": files_proj,
            "correlation_id": correlation_id or "",
        }

        # Defer embedding to the worker so the hot path stays fast.
        if self._embeddings is not None and is_final_step(messages_proj):
            text = build_search_text(messages_proj, cap=self.max_search_text_bytes)
            if text:
                doc["__embedder"] = self._embeddings
                doc["__search_text"] = text

        self._worker.enqueue(doc)

    def flush_for_tests(self, timeout: float = 5.0) -> None:
        """Block until the worker queue drains. Test-only helper."""
        self._worker.flush_for_tests(timeout)
