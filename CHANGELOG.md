# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-06-02

First stable release. The public API documented in
[`docs/reference/api.md`](docs/reference/api.md) is now covered by semantic
versioning, and the project has moved to its official home in the MongoDB
Partners organization. Apart from the raised Python floor, there are no
public API changes from 0.3.0.

### Changed

- **Python 3.11+ is now required** (was 3.10+). On CPython 3.10 the async
  agent path cannot propagate the runnable-config context into a middleware
  hook, so per-user attribution silently failed under `ainvoke`. Rather than
  ship that sharp edge, 3.10 is dropped; the supported matrix is now
  3.11 / 3.12 / 3.13.
- Promoted from alpha to production/stable.
- **`langchain-voyageai` is now a core dependency** (was the optional
  `[voyage]` extra). Voyage AI is the default embedder for hybrid recall, so
  a plain `pip install langchain-mongodb-agent-log` is batteries-included.
  The `[voyage]` extra is kept (empty) so existing install pins keep working.

### Fixed

- Async agents no longer risk dropping a super-step when the ambient
  runnable-config context is unreachable — `thread_id` is recovered from the
  node runtime as a fallback.

## [0.3.0] — 2026-06-02

Hardening + feature release. Spec: `specs/v0.3/`. All v0.1/v0.2 behavior is
preserved by default; new behavior is opt-in. 120 unit tests (was 80).

### Fixed

- **Queue backpressure now drops the *oldest* doc, not the newest** (BUG-301).
  REQ-020 documented "drop the oldest excess" but the worker discarded the
  incoming (newest) super-step — the one most likely to be recalled.
- **`flush_for_tests(timeout)` honors its timeout** (BUG-302): it raises
  `TimeoutError` on expiry instead of blocking forever on an unbounded
  `Queue.join()`.

### Added

- **Lifecycle:** `AgentLog.close(timeout)` (drain + stop the worker, idempotent),
  `AgentLog.flush(timeout)` (bounded drain), and an opt-out `flush_on_exit`
  atexit hook. Fixes data loss on shutdown for embedding consumers. (REQ-300/301/302/303)
- **Observability:** `AgentLog.stats()` returns `queue_depth`, `queue_capacity`,
  `worker_alive`, `enqueued`, `written`, `dropped`, `embed_failures`,
  `write_failures`, `last_write_ts` — no DB round-trip. (REQ-304/305)
- **Durable step counter (opt-in):** `AgentLog(..., durable_step=True)` assigns
  `step`/`parent_step` from a persisted per-thread atomic counter on the worker
  thread, so `step` is monotonic across restarts and processes. Default behavior
  (in-memory, non-blocking) is unchanged. (REQ-306/307)
- **Ordered read API:** `AgentLog.get_thread(thread_id, *, user_id, limit,
  ascending)` (ordered by `ts`, restart-robust) and
  `AgentLog.get_by_correlation_id(cid)`. (REQ-308/309/310)
- **Retrieval:** `AgentLogRetriever`/`build_tool` accept `search_index`/
  `vector_index` (so renamed Atlas indexes actually take effect), optional
  `thread_id`/`since` narrowing filters, and an optional best-effort
  `reranker` (falls back to RRF order on any reranker error). (REQ-311/312/313)
- **Search index** now maps `agent_name` so structured `$search` can scope by
  agent. (REQ-314)
- **Attribution:** `AgentLogMiddleware(log, agent_name="...")` — a constructor
  override (beats `configurable["agent_name"]`) giving deepagents subagents an
  attribution seam. (REQ-315)
- **Correlation ids** are auto-derived in the adapters when absent
  (`traceparent` → `x_request_id` → uuid4 string); the engine stays
  framework-agnostic. (REQ-316)
- **`set_ttl(collection, ttl_seconds)`** updates retention in place via
  `collMod` (no drop-and-recreate); `None` removes the TTL index. (REQ-317)
- **`AgentLog.record(..., ts=)`** for deterministic seeding. (REQ-318)
- A rate-limited warning when a final super-step has no embeddable text
  (single-role turn → invisible to vector search). (REQ-319)
- GitHub Actions CI (ruff + mypy --strict + pytest on 3.10/3.11/3.12).

### Changed

- `step` is documented as monotonic-per-restart only under `durable_step=True`;
  the default remains the lossy in-memory counter (now lock-guarded for
  thread-safe shared engines).

## [0.2.0] — 2026-05-12

### Added

- **`scoped_user(user_id)` context manager** and **`current_user_id()`
  reader** for per-task / per-thread `user_id` propagation. New module:
  `langchain_mongodb_agent_log.core.context`. Both symbols are
  re-exported from the package root via the lazy `__getattr__` map.
- **3-tier `user_id` resolution in `AgentLogCallbackHandler`**:
  per-call `metadata["user_id"]` > `current_user_id()` (ContextVar) >
  constructor default. Production multi-tenant servers should wrap
  `graph.invoke(...)` in `scoped_user(req.user_id)` and share a
  single handler instance across requests.
- New how-to:
  [`docs/how-to/per-user-scoping-with-contextvar.md`](docs/how-to/per-user-scoping-with-contextvar.md).
- API reference rows for the two new symbols.
- 13 new unit tests (8 for the ContextVar primitives, 4 for the
  3-tier resolver, 1 for the public-API import surface). Total
  test count: 67 → 80.

### Why

In v0.1, a single `AgentLogCallbackHandler` instance shared across
concurrent users would attribute every doc to whatever
`user_id=` was passed to the constructor — a quiet correctness bug
in multi-tenant async deployments. v0.2 closes that gap by mirroring
LangGraph's own pattern (`RunnableConfig` propagated via ContextVar)
without forcing one-handler-per-user.

### Unchanged (invariants preserved)

- `AgentLogMiddleware` behavior is identical — it reads `user_id`
  from `langgraph.config.get_config().configurable` (LangGraph's own
  ContextVar) and does not consult ours.
- `AgentLogCallbackHandler(log, user_id="alice")` still works as a
  fallback when neither `metadata["user_id"]` nor the ContextVar is
  set. Existing v0.1 tests pass without modification.
- Per-user `pre_filter` enforcement on the retriever is unchanged.
- The persisted document schema is unchanged.

### Migration from v0.1

No code changes are required. v0.2 is purely additive. To take
advantage of the new primitives in a multi-user server, wrap your
graph invocations:

```python
# Before (v0.1) — one handler per user
handler = AgentLogCallbackHandler(log, user_id=req.user_id)
graph.invoke(payload, config={"callbacks": [handler]})

# After (v0.2) — one handler per process, scope per request
handler = AgentLogCallbackHandler(log)   # constructed once
with scoped_user(req.user_id):
    graph.invoke(payload, config={"callbacks": [handler]})
```

## [0.1.0] — 2026-05-12

Initial release. See `specs/v0.1/` for the full spec.
