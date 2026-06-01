# Design Delta — `langchain-mongodb-agent-log` v0.3

References v0.1 `design.md` and v0.2 `design-delta.md`. Documents only what
changes. Architecture (engine + worker + projection + adapters + retrieval +
embeddings, framework-agnostic engine boundary) is unchanged.

## Modified components

### `core/worker.py` — `_DaemonWorker`
- **Drop-oldest (BUG-301).** On `queue.Full`, pop one item from the head
  (`get_nowait` + `task_done`), increment `dropped`, then `put_nowait` the new
  doc. Keep it non-blocking.
- **Bounded drain (BUG-302, REQ-300/301).** Add `drain(timeout) -> bool` that
  waits on a `threading.Condition` signalled when `unfinished_tasks` hits 0,
  bounded by `timeout`. `close(timeout)` enqueues the `None` sentinel (already
  handled at `_loop`), joins the thread within `timeout`, returns drained-ness.
- **Counters (REQ-304/305).** Add `enqueued/written/dropped/embed_failures/
  write_failures/last_write_ts`, mutated under the existing `_lock`. Expose
  `stats()` and `qsize()`/`alive()` accessors.
- **Durable step (REQ-306).** New optional `counter_collection`; when present,
  `_finalize_and_insert` assigns `doc["step"]`/`doc["parent_step"]` from
  `find_one_and_update({_id: thread_id}, {$inc:{seq:1}}, upsert=True,
  return_document=AFTER)` **before** insert. Embedding still happens here.

### `core/engine.py` — `AgentLog`
- New ctor args: `durable_step=False`, `flush_on_exit=True`,
  `counter_collection=None` (defaults to `<collection.name>_counters`).
- `record(..., ts=None)` (REQ-318). When `durable_step` is on, `record()` no
  longer stamps `step`/`parent_step` — it tags the doc `__assign_step=thread_id`
  and the worker assigns them (keeps the hot path off the counter round-trip,
  NFR-300). When off, keep current in-memory assignment but guard with a lock
  (REQ-307).
- New public methods: `close(timeout)`, `flush(timeout)`, `stats()`,
  `get_thread(...)`, `get_by_correlation_id(...)`. `flush_for_tests(timeout)`
  becomes a thin wrapper that raises `TimeoutError` on expiry.
- Closed-engine guard (REQ-302) + optional `atexit.register(self._atexit_flush)`
  (REQ-303). Single-role embed warning, rate-limited per `thread_id` (REQ-319).

### `core/indexes.py`
- `ensure_search_indexes(collection, *, embeddings_dim, vector_index=
  VECTOR_INDEX_NAME, search_index=SEARCH_INDEX_NAME)` (REQ-311) — names
  overridable; add `agent_name` to the search mapping (REQ-314).
- New `set_ttl(collection, ttl_seconds)` via `collMod`, warn-and-skip when the
  command is unsupported (REQ-317).

### `adapters/middleware.py`
- `__init__(self, log, *, agent_name=None)` (REQ-315); `agent_name` override
  beats `configurable["agent_name"]`.
- Correlation derivation helper (REQ-316) shared with callback/node.

### `adapters/callback.py`, `adapters/node.py`
- Use the shared correlation-id derivation (REQ-316). Callback/node behavior
  otherwise unchanged.

### `retrieval/retriever.py`, `retrieval/tool.py`
- `AgentLogRetriever(..., search_index=..., vector_index=..., reranker=None,
  fetch_multiplier=3)`; `invoke(query, *, user_id, thread_id=None, since=None)`
  builds the compound `pre_filter` (REQ-312) and applies best-effort rerank
  (REQ-313).
- `build_tool(..., search_index=..., vector_index=..., reranker=None)` forwards
  to the retriever (REQ-311). Remove `_ = logging` placeholder (REQ-320). Fix
  the docstring's phantom `k` param.

### `__init__.py`
- Add `set_ttl` to `__all__` + lazy map. (`get_thread`/`close`/`stats` are
  `AgentLog` methods, already reachable.)

## New components

- **`<collection>_counters`** collection (only when `durable_step=True`): one
  doc per `thread_id`, `{_id: thread_id, seq: int}`. Provisioned lazily by the
  worker's `find_one_and_update(upsert=True)`; no DDL helper needed.
- **`docs/how-to/observability.md`**, **`docs/how-to/attribute-subagents.md`**.

## Boundary Inventory

| # | Boundary | From → To | Acceptance test |
|---|---|---|---|
| 1 | enqueue → background worker | `record()` (caller thread) → daemon thread | TC-300x (FIFO + drop-oldest), TC-NFR-300 (timing) |
| 2 | worker → MongoDB write | daemon thread → `Collection.insert_one` | TC-301x (mongomock), TC-INT-301 (`ATLAS_URI`) |
| 3 | durable step counter | worker → `find_one_and_update` | TC-306 (mongomock seq), TC-INT-306 (two engines, restart-sim) |
| 4 | ordered read | `get_thread` → `find().sort` | TC-308 (ts/step order on mongomock) |
| 5 | retrieval | retriever → Atlas `$search`/`$vectorSearch` (+ optional rerank) | TC-313 (rerank fallback, fake reranker), TC-INT-312 (`ATLAS_URI`) |
| 6 | TTL admin | `set_ttl` → `collMod` | TC-317 (warn-skip on mongomock), TC-INT-317 (`ATLAS_URI`) |
| 7 | adapter → langgraph config | middleware/callback → `get_config()` | TC-315 (agent_name override), TC-316 (correlation derivation) |

No browser/HTTP/SSE boundary — this is a library. Boundaries 2/3/5/6 have both
a mongomock fast test and an `ATLAS_URI`-gated integration test (mock-parity).

## Mock-parity contracts

- **mongomock vs Atlas for `find_one_and_update` upsert returning the new doc**
  (REQ-306): mongomock supports `return_document=ReturnDocument.AFTER`; an
  integration test asserts the real Atlas driver returns the same incremented
  `seq` shape. (TC-PARITY-306)
- **`collMod` is NOT supported by mongomock** (REQ-317): the unit test asserts
  `set_ttl` warns-and-skips on mongomock; the integration test asserts it
  actually mutates `expireAfterSeconds` on Atlas. (TC-PARITY-317)

## Test infrastructure

Already exists (pytest + pytest-asyncio + mongomock; `integration` marker
gated by `ATLAS_URI`; `filterwarnings=error`). No bootstrap needed. New tests
follow the existing `tests/unit/test_<module>.py` layout and
`test_TC_*`/`test_*` naming. Integration tests go in `tests/integration/`,
each `@pytest.mark.integration` and `pytest.skip` when `ATLAS_URI` is unset.

## Files to modify vs create

**Modify:** `core/worker.py`, `core/engine.py`, `core/indexes.py`,
`adapters/middleware.py`, `adapters/callback.py`, `adapters/node.py`,
`retrieval/retriever.py`, `retrieval/tool.py`, `__init__.py`, `_version.py`,
`pyproject.toml`, `CHANGELOG.md`, `README.md`, `docs/reference/api.md`,
`docs/reference/document-shape.md`, `docs/how-to/configure-ttl.md`,
`tests/unit/test_*` (extend), `tests/integration/*`.

**Create:** `.github/workflows/ci.yml`, `docs/how-to/observability.md`,
`docs/how-to/attribute-subagents.md`, `tests/unit/test_lifecycle.py`,
`tests/unit/test_stats.py`, `tests/unit/test_read_api.py`,
`tests/unit/test_set_ttl.py`, `tests/unit/test_correlation.py`,
`tests/unit/test_rerank.py`, `tests/integration/test_durable_step.py`,
`tests/integration/test_set_ttl_live.py`.
