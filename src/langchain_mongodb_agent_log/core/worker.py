"""Background worker for agent-log persistence.

Spec REQ-018..022: the agent super-step must not block on the MongoDB write
or the embedding round-trip. The worker drains a bounded queue on a single
daemon thread, preserving FIFO order per ``thread_id``.

Why a single daemon thread:
- FIFO ordering per ``thread_id`` is preserved trivially with one consumer.
- Multiple workers would require per-``thread_id`` partitioning which adds
  state without a measurable throughput win at our default queue sizes.
- The daemon flag means the worker never blocks process shutdown; pending
  docs are lost on hard exit unless :meth:`close` is called first (v0.3).

v0.3 additions:
- **Drop-oldest backpressure (BUG-301):** a full queue evicts the head, not
  the incoming doc, matching REQ-020's documented "drop the oldest" semantics.
- **Bounded drain / close (REQ-300/301, BUG-302):** :meth:`drain` waits at
  most ``timeout`` seconds; :meth:`close` drains then stops the worker.
- **Counters (REQ-304/305):** ``stats()`` exposes queue + throughput signal
  for operator health probes, with no database round-trip.
"""
from __future__ import annotations

import contextlib
import queue
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from pymongo.errors import PyMongoError

from .._logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from pymongo.collection import Collection


_log = get_logger()


class _Worker(Protocol):
    def enqueue(self, doc: dict[str, Any]) -> None: ...
    def drain(self, timeout: float = 5.0) -> bool: ...
    def close(self, timeout: float = 5.0) -> bool: ...
    def stats(self) -> dict[str, Any]: ...


class _DaemonWorker:
    """Drain a bounded queue on a daemon thread."""

    def __init__(
        self,
        collection: Collection[Any],
        *,
        queue_maxsize: int = 256,
        counter_collection: Collection[Any] | None = None,
    ) -> None:
        self._coll = collection
        self._counter_coll = counter_collection
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=queue_maxsize
        )
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # ``_cond`` shares ``_lock``; signalled whenever ``_inflight`` drops so
        # ``drain`` can wake without polling. ``_inflight`` counts real docs
        # enqueued-but-not-yet-processed (the shutdown sentinel is excluded).
        self._cond = threading.Condition(self._lock)
        self._inflight = 0
        self._closed = False
        # Observability counters (REQ-304/305). Mutated under ``_lock``.
        self._enqueued = 0
        self._written = 0
        self._dropped = 0
        self._embed_failures = 0
        self._write_failures = 0
        self._last_write_ts: datetime | None = None

    # -- enqueue -----------------------------------------------------------

    def enqueue(self, doc: dict[str, Any]) -> None:
        if self._closed:
            return
        self._ensure_started()
        try:
            self._queue.put_nowait(doc)
        except queue.Full:
            self._evict_oldest(doc)
            try:
                self._queue.put_nowait(doc)
            except queue.Full:  # pragma: no cover - worker fell further behind
                with self._cond:
                    self._dropped += 1
                _log.warning("agent_log queue full; dropped incoming doc")
                return
        with self._cond:
            self._inflight += 1
            self._enqueued += 1

    def _evict_oldest(self, incoming: dict[str, Any]) -> None:
        """Discard one doc from the head so the newest can be enqueued."""
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:  # pragma: no cover - drained out from under us
            return
        with self._cond:
            if self._inflight > 0:
                self._inflight -= 1
            self._dropped += 1
            self._cond.notify_all()
        _log.warning(
            "agent_log queue full; dropped oldest doc to enqueue thread=%s step=%s",
            incoming.get("thread_id"),
            incoming.get("step"),
        )

    # -- lifecycle ---------------------------------------------------------

    def drain(self, timeout: float = 5.0) -> bool:
        """Block until all in-flight docs are processed, bounded by ``timeout``.

        Returns ``True`` if the queue drained within ``timeout``, ``False``
        otherwise. Does not stop the worker.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._inflight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def close(self, timeout: float = 5.0) -> bool:
        """Drain, signal shutdown, and join the worker within ``timeout``.

        Idempotent: a second call returns ``True`` immediately. Returns
        ``True`` only if the queue drained and the thread stopped in time.
        """
        with self._cond:
            self._closed = True
        t = self._thread
        if t is None or not t.is_alive():
            return True
        deadline = time.monotonic() + timeout
        drained = self.drain(max(0.0, deadline - time.monotonic()))
        try:
            self._queue.put_nowait(None)  # shutdown sentinel (not counted)
        except queue.Full:
            self._evict_oldest({"thread_id": None, "step": None})
            with contextlib.suppress(queue.Full):  # pragma: no cover
                self._queue.put_nowait(None)
        t.join(max(0.0, deadline - time.monotonic()))
        return drained and not t.is_alive()

    # -- introspection -----------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            last = self._last_write_ts
            return {
                "queue_depth": self._queue.qsize(),
                "queue_capacity": self._queue.maxsize,
                "worker_alive": bool(alive),
                "enqueued": self._enqueued,
                "written": self._written,
                "dropped": self._dropped,
                "embed_failures": self._embed_failures,
                "write_failures": self._write_failures,
                "last_write_ts": last.isoformat() if last is not None else None,
            }

    # -- internals ---------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._closed:
            return
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
            if doc is None:
                self._queue.task_done()  # shutdown sentinel
                return
            try:
                self._embed_then_insert(doc)
            except Exception as exc:  # pragma: no cover - last-resort guard
                _log.warning("agent_log worker unexpected: %s", exc)
            finally:
                self._queue.task_done()
                with self._cond:
                    if self._inflight > 0:
                        self._inflight -= 1
                    self._cond.notify_all()

    def _assign_durable_step(self, doc: dict[str, Any]) -> None:
        """REQ-306: assign monotonic ``step`` from the persisted counter.

        Runs on the worker thread (never the agent hot path). On any counter
        failure the doc is still inserted with ``step=None`` rather than
        dropped (INV-002 spirit: a logged turn beats a lost one).
        """
        thread_id = doc.pop("__assign_step", None)
        if thread_id is None or self._counter_coll is None:
            return
        from pymongo import ReturnDocument

        try:
            res = self._counter_coll.find_one_and_update(
                {"_id": thread_id},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            if res is None:  # pragma: no cover - upsert+AFTER always returns a doc
                doc.setdefault("step", None)
                doc.setdefault("parent_step", None)
                return
            step = int(res["seq"]) - 1
            doc["step"] = step
            doc["parent_step"] = step - 1 if step > 0 else None
        except PyMongoError as exc:
            doc.setdefault("step", None)
            doc.setdefault("parent_step", None)
            _log.warning("agent_log durable step assignment failed: %s", exc)

    def _embed_then_insert(self, doc: dict[str, Any]) -> None:
        if "__assign_step" in doc:
            self._assign_durable_step(doc)
        embedder = doc.pop("__embedder", None)
        search_text = doc.pop("__search_text", None)
        if embedder is not None and search_text:
            try:
                doc["agent_log_embedding"] = embedder.embed_query(search_text)
                doc["agent_log_text"] = search_text
            except Exception as exc:
                with self._cond:
                    self._embed_failures += 1
                _log.warning("agent_log embedding failed: %s", exc)
        try:
            self._coll.insert_one(doc)
        except PyMongoError as exc:
            with self._cond:
                self._write_failures += 1
            _log.warning("agent_log insert failed: %s", exc)
        else:
            with self._cond:
                self._written += 1
                ts = doc.get("ts")
                self._last_write_ts = (
                    ts if isinstance(ts, datetime) else datetime.now(timezone.utc)
                )


def build_worker(
    collection: Collection[Any],
    *,
    queue_maxsize: int = 256,
    counter_collection: Collection[Any] | None = None,
) -> _Worker:
    return _DaemonWorker(
        collection, queue_maxsize=queue_maxsize, counter_collection=counter_collection
    )


__all__ = ["build_worker"]
