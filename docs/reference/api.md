# API reference

Every name re-exported from `langchain_mongodb_agent_log`.

## `AgentLog`

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
    ) -> None
```

The engine. Holds the MongoDB collection, the optional embedder, and a
background daemon worker. Construct one per process (or per
collection — multiple `AgentLog` instances are safe but not necessary).

### Methods

#### `record(*, thread_id, user_id, messages, todos=None, agent_name=None, correlation_id=None) -> None`

Project state and enqueue one log document. Non-blocking. Adapters
funnel into this; user code typically doesn't call it directly.

#### `flush_for_tests(timeout: float = 5.0) -> None`

Block until the worker queue drains. Test-only.

## `AgentLogMiddleware`

```python
class AgentLogMiddleware(AgentMiddleware):
    def __init__(self, log: AgentLog) -> None
```

Subclass of `langchain.agents.middleware.AgentMiddleware`. Hook points:

- `after_model(state, runtime) -> None`
- `aafter_model(state, runtime) -> None` (async)

Reads `RunnableConfig.configurable` (via `langgraph.config.get_config()`
when available, else `runtime.config["configurable"]`). Required keys:
`thread_id`, `user_id`. Optional keys: `agent_name`, `correlation_id`.

## `AgentLogCallbackHandler`

```python
class AgentLogCallbackHandler(BaseCallbackHandler):
    def __init__(self, log: AgentLog, *, user_id: str | None = None) -> None
```

Subclass of `langchain_core.callbacks.BaseCallbackHandler`. Pairs
`on_chain_start` (where LangGraph stamps `langgraph_node`) with
`on_chain_end` keyed by `run_id`.

The `user_id=` constructor arg is a fallback because LangGraph elevates
`thread_id` (but not `user_id`) into per-node metadata. Pass it here or
override per invocation via `config["metadata"]["user_id"]`.

Async equivalents:

- `on_chain_start_async`
- `on_chain_end_async`

## `agent_log_node(log: AgentLog) -> Callable[[State, RunnableConfig], dict]`

Factory returning a graph node that records one log document and
returns `{}` (no state delta). Wire it before `END` or as a sibling to
any node where you want a deterministic write.

## `AgentLogRetriever`

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
    ) -> None
```

Wraps `MongoDBAtlasHybridSearchRetriever` with a per-user `pre_filter`.

#### `invoke(query: str, *, user_id: str) -> list[Document]`

Returns up to `top_k` log documents ranked by RRF fusion. Per-user
filter is mandatory.

## `search_past_conversations` (placeholder) and `build_tool(...)`

```python
from langchain_mongodb_agent_log.retrieval.tool import build_tool

tool = build_tool(collection, embeddings, *, top_k: int = 5)
```

Builds a LangChain `@tool` bound to a specific collection + embedder.
Tool input schema: `{"query": str}`. `user_id` is read from the
ambient `RunnableConfig.configurable` (the agent cannot pass it as a
parameter — that would let the agent spoof another user).

The `search_past_conversations` symbol exported at package root is a
placeholder that raises an informative `RuntimeError` when called
directly. Always use `build_tool(...)` to construct a real tool.

## `ensure_agent_log_indexes(collection, *, ttl_seconds=None) -> None`

Create the regular B-tree indexes. Idempotent.

## `ensure_search_indexes(collection, *, embeddings_dim) -> None`

Create the Atlas Search and Vector Search indexes. Idempotent.
Warns-and-skips on deployments without `createSearchIndex`.

## `default_voyage(*, model="voyage-3", dimensions=1024) -> Embeddings`

Optional Voyage embedder factory. Reads `VOYAGE_API_KEY` from the
environment. Raises `RuntimeError` if the key is missing or
`langchain-voyageai` is not installed.

Install with:

```bash
pip install langchain-mongodb-agent-log[voyage]
```

## Constants

- `__version__` — package version string (e.g. `"0.1.0"`).

## See also

- [Configuration](configuration.md) — defaults and tuning knobs.
- [Document shape](document-shape.md) — what `record()` writes.
- [Indexes](indexes.md) — what the index helpers create.

## `scoped_user(user_id: str) -> ContextManager[None]`  *(v0.2+)*

```python
from langchain_mongodb_agent_log import scoped_user
```

Context manager that sets the package-private `user_id` ContextVar
for the duration of the `with` block. Used by the callback adapter
when neither `metadata["user_id"]` nor a constructor default is set.

Per-`asyncio.Task` and per-thread isolated. Restores the previous
value on `__exit__`, including when the block raises.

```python
with scoped_user("alice"):
    graph.invoke(payload, config={"callbacks": [handler]})
```

See [`docs/how-to/per-user-scoping-with-contextvar.md`](../how-to/per-user-scoping-with-contextvar.md)
for the full pattern.

## `current_user_id() -> str | None`  *(v0.2+)*

```python
from langchain_mongodb_agent_log import current_user_id
```

Read the active scoped `user_id`. Returns the value set by the
innermost active `scoped_user(...)` block in the current task /
thread, or `None` if no scope is active.

O(1). No I/O.

The callback adapter calls this internally when the per-call
`metadata["user_id"]` is empty. Application code rarely needs to
call it directly.
