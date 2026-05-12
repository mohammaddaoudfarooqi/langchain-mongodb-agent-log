# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
