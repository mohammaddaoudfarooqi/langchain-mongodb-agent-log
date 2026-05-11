# Design — `langchain-mongodb-agent-log` v0.1

> Companion to `requirements.md`. This document covers package layout,
> the engine/adapter boundary, the persisted document shape, index DDL,
> the worker model, the dependency graph, and the public API surface.

## 1. Architectural overview

```
                 ┌────────────────────────────────────────────┐
                 │         User's LangChain agent code         │
                 │   (deepagents / create_agent / StateGraph) │
                 └─────────────┬──────────────────────────────┘
                               │ hook fires
                               ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                         ADAPTERS (thin)                        │
   │  AgentLogMiddleware  │ AgentLogCallbackHandler │ agent_log_node │
   └────────────────┬──────────────┬──────────────────┬───────────┘
                    │              │                  │
                    └──────────────┴──── log.record() ┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                       ENGINE (core)                            │
   │     AgentLog: project + truncate + enqueue (no I/O)            │
   └────────────────────────────────────┬──────────────────────────┘
                                        │ Queue.put_nowait
                                        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                  BACKGROUND WORKER (daemon)                    │
   │  drain queue → embed (final step + embedder) → insert_one      │
   └────────────────────────────────────┬──────────────────────────┘
                                        │
                       ┌────────────────┴────────────────┐
                       ▼                                  ▼
              ┌─────────────────┐              ┌──────────────────┐
              │  MongoDB Atlas  │              │  Atlas Search +  │
              │   collection    │   ◀─────────▶│  Vector indexes  │
              └─────────────────┘              └──────────────────┘
                       ▲
                       │ AgentLogRetriever
                       │ (RRF: $search ⊕ $vectorSearch)
                       │
                       └── search_past_conversations(@tool)
```

The cardinal rule: **adapters do nothing but call `log.record(...)`**. All
projection, truncation, queueing, and persistence lives in the engine. This
keeps the adapter-by-adapter test surface trivial and forces the engine to
stay framework-agnostic.

## 2. Package layout

```
langchain-mongodb-agent-log/
  pyproject.toml
  uv.lock
  README.md
  LICENSE                       # Apache-2.0
  CHANGELOG.md
  specs/v0.1/
    requirements.md
    design.md
    tasks.md
  docs/
    README.md                   # doc index
    tutorial/
      first-log.md              # 60-second quickstart
      hybrid-search.md
    how-to/
      deepagents.md
      create-agent.md
      multi-agent-supervisor.md
      bare-stategraph.md
      migrate-from-create-react-agent.md
      configure-ttl.md
      provide-custom-embeddings.md
    reference/
      api.md                    # generated-style API surface
      document-shape.md
      indexes.md
      configuration.md
    explanation/
      architecture.md
      why-not-checkpointer.md
      langsmith-comparison.md
  src/
    langchain_mongodb_agent_log/
      __init__.py               # public API re-exports
      _version.py               # 0.1.0
      core/
        __init__.py
        engine.py               # AgentLog
        projection.py           # message + todos + files projection
        worker.py               # daemon thread + queue
        indexes.py              # ensure_agent_log_indexes / ensure_search_indexes
        types.py                # TypedDicts for the doc shape
      adapters/
        __init__.py
        middleware.py           # AgentLogMiddleware (sync + async)
        callback.py             # AgentLogCallbackHandler (sync + async)
        node.py                 # agent_log_node factory
      retrieval/
        __init__.py
        retriever.py            # AgentLogRetriever
        tool.py                 # search_past_conversations @tool
      embeddings/
        __init__.py
        factory.py              # default_voyage()
      _logging.py               # named logger
  tests/
    conftest.py                 # autouse env hygiene, mongomock fixtures
    unit/
      test_engine.py
      test_projection.py
      test_worker.py
      test_indexes.py
      test_middleware.py
      test_callback.py
      test_node.py
      test_retriever.py
      test_tool.py
      test_voyage_factory.py
      test_public_api.py
    integration/
      test_atlas_indexes.py     # ATLAS_URI gated
      test_atlas_retrieval.py   # ATLAS_URI gated
      test_graph_shapes.py      # the four-shape matrix
      test_async_invocation.py
```

## 3. The persisted document

```jsonc
{
  "_id": ObjectId,
  "thread_id": "string",
  "user_id": "string",
  "agent_name": "string",         // default "main"
  "step": 0,                       // monotonic per thread_id
  "parent_step": null,             // step - 1, or null
  "ts": ISODate,                   // UTC datetime
  "correlation_id": "string",      // empty string when absent

  "messages": [
    {
      "type": "human" | "ai" | "tool" | "system",
      "content": "string",         // Bedrock content lists coerced
      "tool_calls": [ ... ],       // raw, verbatim
      "tool_call_id": "string|null",
      "usage": { ... } | null,
      "model_id": "string|null",
      "finish_reason": "string|null"
    },
    ...
  ],

  "todos": [
    { "id": "string", "content": "string", "status": "pending|in_progress|completed" },
    ...
  ],

  "files_touched": [
    { "path": "string", "size": 0, "content_hash": null,
      "op": "write" | "edit" }
  ],

  // Present only on the FINAL super-step of a turn AND when an embedder
  // is configured.
  "agent_log_text": "string",      // joint human + final-AI; capped
  "agent_log_embedding": [float]   // 1024-dim by default (voyage-3)
}
```

### Field rationale

- `step` is **per-thread monotonic**, not the LangGraph internal step id.
  Lossy on purpose — the engine doesn't see LangGraph's step counter, only
  what fires through the hook. Use `correlation_id` to reconcile across
  systems if needed.
- `agent_name` defaults to `"main"` so single-agent users never have to think
  about it. Multi-agent users inject it via `configurable["agent_name"]`
  (middleware) or it's auto-derived from `metadata["langgraph_node"]`
  (callback).
- `files_touched` is **derived from tool_calls**, not from any VFS. Under
  spec-503-style composite backends `state["files"]` is empty, so reading
  state isn't sufficient. The default FS-write tool set is configurable.
- `agent_log_text` and `agent_log_embedding` are **omitted** (not `null`) on
  non-final steps so Atlas Search / Vector Search don't index empty
  documents.

## 4. The engine

```python
class AgentLog:
    def __init__(
        self,
        collection: Collection,
        embeddings: Embeddings | None = None,
        *,
        fs_write_tools: frozenset[str] = frozenset({"write_file", "edit_file"}),
        max_content_bytes: int = 15 * 1024 * 1024,
        max_search_text_bytes: int = 8 * 1024,
        queue_maxsize: int = 256,
    ) -> None: ...

    def record(
        self,
        *,
        thread_id: str,
        user_id: str,
        messages: Sequence[BaseMessage],
        todos: Sequence[Mapping[str, Any]] | None = None,
        agent_name: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """The single write path. Adapters call this. No I/O on hot path."""
```

Internal state:

```python
self._step_counter: dict[str, int]   # per thread_id, in-process
self._worker: _MirrorWorker          # owns the queue + daemon
```

Hot-path pseudocode for `record(...)`:

```python
def record(self, ...):
    if not thread_id or not user_id:
        return
    step = self._step_counter.get(thread_id, 0)
    self._step_counter[thread_id] = step + 1

    messages_proj = project_messages(messages, cap=self.max_content_bytes)
    todos_proj    = project_todos(todos)
    files_proj    = project_files(messages, fs_write_tools=self.fs_write_tools)

    doc = {
        "thread_id": thread_id, "user_id": user_id,
        "agent_name": agent_name or "main",
        "step": step, "parent_step": step - 1 if step > 0 else None,
        "ts": datetime.now(UTC),
        "correlation_id": correlation_id or "",
        "messages": messages_proj,
        "todos": todos_proj,
        "files_touched": files_proj,
    }

    if self.embeddings and is_final_step(messages_proj):
        text = build_search_text(messages_proj, cap=self.max_search_text_bytes)
        if text:
            doc["__embedder"] = self.embeddings    # consumed in worker
            doc["__search_text"] = text

    self._worker.enqueue(doc)   # Queue.put_nowait, drops on full
```

Note: the adapter is responsible for extracting `thread_id` / `user_id` /
`agent_name` / `correlation_id` from the runtime config — the engine never
touches `RunnableConfig` directly. This keeps the engine fully framework-
agnostic and test-able with plain kwargs.

## 5. The worker

```python
class _MirrorWorker:
    def __init__(self, collection: Collection, *, queue_maxsize: int = 256):
        self._coll = collection
        self._queue: Queue[dict | None] = Queue(maxsize=queue_maxsize)
        self._thread: Thread | None = None
        self._lock = threading.Lock()

    def enqueue(self, doc: dict) -> None:
        self._ensure_started()
        try:
            self._queue.put_nowait(doc)
        except queue.Full:
            log.warning("agent_log queue full; dropping doc thread=%s step=%s",
                        doc.get("thread_id"), doc.get("step"))

    def _ensure_started(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = Thread(target=self._loop, daemon=True,
                                  name="agent-log-worker")
            self._thread.start()

    def _loop(self) -> None:
        while True:
            doc = self._queue.get()
            try:
                self._embed_if_needed(doc)
                self._coll.insert_one(doc)
            except PyMongoError as exc:
                log.warning("agent_log insert failed: %s", exc)
            except Exception as exc:
                log.warning("agent_log worker unexpected: %s", exc)
            finally:
                self._queue.task_done()

    def flush_for_tests(self, timeout: float = 5.0) -> None:
        self._queue.join()
```

Why a single daemon thread: ordering preservation per `thread_id` is FIFO.
Multiple workers would require per-`thread_id` partitioning to keep ordering;
not worth the complexity for v0.1.

## 6. Adapters

### 6.1 Middleware

```python
from langchain.agents.middleware import AgentMiddleware

class AgentLogMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(self, log: AgentLog) -> None:
        super().__init__()
        self.tools = []
        self._log = log

    def after_model(self, state, runtime):
        cfg = _configurable(runtime)
        self._log.record(
            thread_id=str(cfg.get("thread_id") or ""),
            user_id=str(cfg.get("user_id") or ""),
            messages=state.get("messages", []) if isinstance(state, dict) else [],
            todos=state.get("todos") if isinstance(state, dict) else None,
            agent_name=cfg.get("agent_name"),
            correlation_id=cfg.get("correlation_id"),
        )
        return None

    async def aafter_model(self, state, runtime):
        # Identical projection — engine.record is sync but trivially fast.
        # We do NOT spawn a thread here; the heavy lifting is on the engine
        # worker thread regardless. await is just for protocol compliance.
        self.after_model(state, runtime)
```

`_configurable(runtime)` tries `langgraph.config.get_config()` first, then
falls back to `runtime.config["configurable"]` for unit tests that supply a
plain mock.

### 6.2 Callback handler

```python
from langchain_core.callbacks import BaseCallbackHandler

class AgentLogCallbackHandler(BaseCallbackHandler):
    def __init__(self, log: AgentLog) -> None:
        self._log = log

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None,
                     tags=None, metadata=None, **kwargs):
        node = (metadata or {}).get("langgraph_node")
        if not node:
            return  # Not a top-level graph node; ignore.
        cfg = (metadata or {}).get("langgraph_checkpoint_ns")  # informational
        self._log.record(
            thread_id=str((metadata or {}).get("thread_id") or ""),
            user_id=str((metadata or {}).get("user_id") or ""),
            messages=self._extract_messages(outputs),
            todos=self._extract_todos(outputs),
            agent_name=node,
            correlation_id=(metadata or {}).get("correlation_id"),
        )

    async def on_chain_end_async(self, outputs, **kwargs):
        return self.on_chain_end(outputs, **kwargs)
```

The filter `if not node: return` is the load-bearing piece — without it,
every inner Runnable would write a doc.

### 6.3 Explicit graph node

```python
def agent_log_node(log: AgentLog):
    def _node(state, config):
        cfg = (config or {}).get("configurable", {})
        log.record(
            thread_id=str(cfg.get("thread_id") or ""),
            user_id=str(cfg.get("user_id") or ""),
            messages=(state or {}).get("messages", []) if isinstance(state, dict) else [],
            todos=(state or {}).get("todos") if isinstance(state, dict) else None,
            agent_name=cfg.get("agent_name") or "main",
            correlation_id=cfg.get("correlation_id"),
        )
        return {}
    return _node
```

## 7. Retrieval

```python
class AgentLogRetriever:
    def __init__(
        self,
        collection: Collection,
        embeddings: Embeddings,
        *,
        search_index: str = "agent_log_search_idx",
        vector_index: str = "agent_log_vector_idx",
        top_k: int = 5,
    ) -> None: ...

    def invoke(self, query: str, *, user_id: str) -> list[Document]:
        # Build MongoDBAtlasVectorSearch on this collection
        # with text_key="agent_log_text", embedding_key="agent_log_embedding".
        # Wrap in MongoDBAtlasHybridSearchRetriever with
        # pre_filter={"user_id": {"$eq": user_id}}.
```

```python
@tool
def search_past_conversations(
    query: str,
    k: int = 5,
    config: RunnableConfig | None = None,
) -> str:
    """Search the calling user's past conversations."""
```

Construction uses module-level `lru_cache(maxsize=1)` for the
`MongoDBAtlasVectorSearch` handle, but the retriever itself is rebuilt per
call so the per-user `pre_filter` doesn't leak across users.

## 8. Indexes

```python
def ensure_agent_log_indexes(
    collection: Collection,
    *,
    ttl_seconds: int | None = None,
) -> None:
    collection.create_index([("thread_id", 1), ("step", 1)],
                            name="agent_log_thread_step_idx")
    collection.create_index([("thread_id", 1), ("ts", -1)],
                            name="agent_log_thread_ts_idx")
    collection.create_index([("user_id", 1), ("ts", -1)],
                            name="agent_log_user_ts_idx")
    if ttl_seconds is not None:
        collection.create_index([("ts", 1)],
                                name="agent_log_ts_ttl_idx",
                                expireAfterSeconds=ttl_seconds)
```

```python
def ensure_search_indexes(
    collection: Collection,
    *,
    embeddings_dim: int,
) -> None:
    # Atlas Vector Search index
    vector_def = {
        "fields": [
            {"type": "vector", "path": "agent_log_embedding",
             "numDimensions": embeddings_dim, "similarity": "cosine"},
            {"type": "filter", "path": "user_id"},
        ]
    }
    # Atlas Search index (lexical)
    search_def = {
        "mappings": {
            "dynamic": False,
            "fields": {
                "agent_log_text": {"type": "string"},
                "user_id":        {"type": "string"},
            },
        }
    }
    _safe_create_search_index(collection, "agent_log_vector_idx",
                              vector_def, type_="vectorSearch")
    _safe_create_search_index(collection, "agent_log_search_idx",
                              search_def, type_="search")
```

`_safe_create_search_index` swallows `OperationFailure` with codes that mean
"already exists" and warns-and-skips when the deployment doesn't support
search-index DDL (e.g., mongomock — REQ-017).

## 9. Public API

```python
# langchain_mongodb_agent_log/__init__.py
from .core.engine import AgentLog
from .core.indexes import ensure_agent_log_indexes, ensure_search_indexes
from .adapters.middleware import AgentLogMiddleware
from .adapters.callback import AgentLogCallbackHandler
from .adapters.node import agent_log_node
from .retrieval.retriever import AgentLogRetriever
from .retrieval.tool import search_past_conversations
from .embeddings.factory import default_voyage

__all__ = [
    "AgentLog",
    "AgentLogMiddleware",
    "AgentLogCallbackHandler",
    "agent_log_node",
    "AgentLogRetriever",
    "search_past_conversations",
    "ensure_agent_log_indexes",
    "ensure_search_indexes",
    "default_voyage",
]
```

This list is locked by `INV-005` (a public-API import test).

## 10. Dependency graph

| Dep | Required | Optional | Why |
|---|---|---|---|
| `pymongo` | ✅ | | Storage |
| `langchain-core` | ✅ | | `Embeddings` ABC, `BaseCallbackHandler`, `Document`, `BaseMessage`, `RunnableConfig`, `@tool` |
| `langchain-mongodb` | ✅ | | `MongoDBAtlasVectorSearch`, `MongoDBAtlasHybridSearchRetriever` |
| `langgraph` | ✅ | | `langgraph.config.get_config` for the middleware adapter |
| `langchain` | ✅ | | `AgentMiddleware` base class for the middleware adapter |
| `langchain-voyageai` | | `[voyage]` | Default embedder factory |
| `pytest`, `pytest-asyncio`, `mongomock`, `ruff`, `mypy` | | dev | Test + lint |

A future v0.2 may split the middleware adapter behind a `[middleware]` extra
to drop the `langchain` dep when only callback or node adapters are used.
For v0.1 we ship middleware as part of the default install since it's the
primary surface.

## 11. Configuration & environment variables

Configuration is constructor-injected. The package reads exactly **one**
environment variable, and only inside the optional Voyage factory:

| Variable | Read by | Effect |
|---|---|---|
| `VOYAGE_API_KEY` | `default_voyage()` | Required for Voyage embedder; raises if missing |

There is intentionally **no** package-wide `Settings` object. Everything else
is a constructor argument. This keeps the package usable in any environment
without env-var setup and avoids polluting the user's process env.

## 12. Logging

A single logger named `langchain_mongodb_agent_log`. All warning lines use
this logger:

- queue full → drop
- PyMongoError on insert
- embedder failure (storage continues)
- search-index DDL skipped (REQ-017)
- `search_past_conversations` retriever failure

No `logging.getLogger().setLevel` calls anywhere — the user's logging
configuration is respected.

## 13. Versioning & stability commitments

- **v0.x** — public API (in `__all__`) is stable but not frozen. Breaking
  changes will be flagged in `CHANGELOG.md` with migration notes.
- **v1.0** — public API frozen. New fields on the doc shape are additive.
  Renaming a field in `__all__` will be a major bump.

## 14. Test strategy

Unit tier (default; runs on every push):
- `mongomock` for the collection
- `_FakeEmbedder` returning deterministic 8-dim vectors
- `flush_for_tests()` after every adapter call so assertions can read back
- Real `pymongo.errors.PyMongoError` exception object passed through a
  patched `insert_one` to validate REQ-022 / INV-001
- Real `langchain.agents.create_agent` with a fake chat model from
  `langchain_core.language_models.fake.FakeMessagesListChatModel` to
  exercise the middleware end-to-end without a real LLM

Integration tier (`pytest -m integration`; opt-in):
- `ATLAS_URI` gated. Each integration test `pytest.skip`s if its env is
  missing.
- Provisions search + vector indexes in a temp DB, polls until queryable,
  runs an actual RRF query, asserts ranking includes the planted doc.

Graph-shape matrix (tier in unit; uses fakes):
- `create_agent` single (middleware)
- `create_agent` supervisor + 2 workers via `Send` (middleware × 3)
- bare `StateGraph` with hand-rolled nodes (callback)
- mixed: supervisor as raw node + workers as `create_agent` (callback at
  graph + middleware on each worker; assert no double-write per step)
- async: `graph.ainvoke` end-to-end; assert worker drains and embedder
  fires on the final step

## 15. Risks & open questions

- **Risk: middleware import cost.** `from langchain.agents.middleware import
  AgentMiddleware` pulls in the full agents package on import. v0.2 may
  guard the import behind a try/except so users on `langchain-core`-only
  installs can still use callback + node adapters.
  Mitigation: `__init__.py` lazily imports adapter classes via
  `__getattr__` so only adapters actually used pay their import cost.
- **Risk: mongomock divergence.** mongomock doesn't fully implement
  `createSearchIndex` or `$vectorSearch`. Search-related tests use either
  mocks or the integration tier; we never assert search behavior against
  mongomock.
- **Open: callback adapter `metadata` shape.** LangGraph stamps
  `metadata["langgraph_node"]`, `metadata["langgraph_step"]`,
  `metadata["thread_id"]` automatically on subgraph runs. We rely on this.
  If a future LangGraph release renames the keys, the callback adapter
  needs updating. Tests pin the contract via fixtures so the breakage
  surfaces immediately.
- **Open: name collision with future `langchain-mongodb` upstream.** We
  ship `agent_log_*` index names. If `langchain-mongodb` later takes over
  this package, we'll keep the names for backwards compat.

## 16. Build, lint, type-check pipeline

```bash
uv sync --all-extras              # dev install
uv run pytest                     # unit tier
uv run pytest -m integration      # opt-in integration
uv run ruff check src tests
uv run mypy --strict src
uv build                          # produces sdist + wheel under dist/
```

CI (deferred to v0.2): GitHub Actions matrix on Python 3.10 / 3.11 / 3.12,
ruff + mypy + unit tests on every PR; integration tier on a nightly
workflow with secrets-injected `ATLAS_URI`.
