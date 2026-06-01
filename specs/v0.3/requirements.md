# Requirements — `langchain-mongodb-agent-log` v0.3

> Brownfield enhancement + bugfix release. Continues the existing namespace:
> v0.1 used `REQ-0xx` / `INV-00x`, v0.2 used `REQ-1xx` / `INV-10x`. v0.3 uses
> **`REQ-3xx`**, **`INV-3xx`**, **`NFR-3xx`**. Prior requirements remain in
> force except where a `Was/Now` note below explicitly modifies one.

## 1. Why v0.3

Two independent reviews converged on the same gaps:

1. **Agent-log analysis** (against the `mongodb-langchain-deep-agents`
   consumer): worker drop/flush semantics, in-memory step counter, dead
   index-name config, no ordered read API, no observability surface, no
   `agent_name` seam for deepagents subagents, no correlation-id
   auto-generation, no rerank, no `set_ttl`, no `ts` injection.
2. **Holistic code review** (`REVIEW.md`): #7 `/plans`+`/messages` go stale
   because `step` resets on restart; #9 the daemon worker is never flushed on
   shutdown → data loss; the "dead config" medium; the "subagent activity never
   logged" medium.

v0.3 also lands two **conformance bugs** where the shipped code contradicts its
own v0.1 spec, plus features the `usecases-agent-log` buy-in-tier-AB spec
showcases (Voyage rerank, operator observability).

## 2. Stakeholders

Unchanged from v0.1 (application / compliance / eval engineers, maintainer),
plus **P5 — Platform operator**: needs liveness/queue/throughput signal to
build health probes and dashboards on the write path.

## 3. Conformance bugfixes

These fix code that violates the **v0.1** spec. Three-part Current/Expected/
Unchanged form.

### BUG-301 — queue-full drops the newest, not the oldest

- **Current:** `_DaemonWorker.enqueue` calls `put_nowait`; on `queue.Full` it
  logs and **returns**, discarding the *incoming* (newest) doc
  (`core/worker.py:48-57`). This silently drops the most recent super-step —
  the one most likely to be recalled.
- **Expected (per REQ-020 "drop the oldest excess"):** WHEN the queue is full
  THE SYSTEM SHALL discard one document from the **head** of the queue and
  enqueue the new one, increment a `dropped` counter, and emit one warning.
- **Unchanged:** the enqueue path SHALL remain non-blocking and SHALL NOT raise
  (INV-003).

### BUG-302 — `flush_for_tests(timeout)` ignores its argument

- **Current:** `flush_for_tests` discards `timeout` and calls an unbounded
  `Queue.join()` (`core/worker.py:59-64`); a wedged worker hangs the caller
  forever.
- **Expected:** `flush_for_tests(timeout)` SHALL block at most `timeout`
  seconds and raise `TimeoutError` if the queue has not drained by then.
- **Unchanged:** when the queue drains within `timeout`, it SHALL return
  normally (REQ-021 "blocks until the queue drains").

## 4. Functional requirements (v0.3)

### 4.1 Worker lifecycle & durability

- **REQ-300.** THE SYSTEM SHALL expose a public `AgentLog.close(timeout:
  float = 5.0) -> bool` that emits the shutdown sentinel, joins the worker
  thread within `timeout`, and returns `True` if the queue fully drained,
  `False` on timeout. It SHALL be idempotent (second call returns `True`
  immediately).
- **REQ-301.** THE SYSTEM SHALL expose a public `AgentLog.flush(timeout:
  float = 5.0) -> bool` that performs a **bounded** drain *without* stopping
  the worker, returning `True` if drained within `timeout` else `False`.
- **REQ-302.** WHEN `close()` has completed THE SYSTEM SHALL ignore further
  `record()` calls (no new worker thread is spawned) and emit one warning the
  first time a closed engine is written to.
- **REQ-303.** THE SYSTEM SHALL register an optional `atexit` flush (opt-out
  via `AgentLog(..., flush_on_exit=False)`, default `True`) so a process that
  forgets to call `close()` still drains best-effort on normal interpreter
  shutdown.

### 4.2 Observability

- **REQ-304.** THE SYSTEM SHALL expose `AgentLog.stats() -> dict[str, Any]`
  returning at minimum: `queue_depth`, `queue_capacity`, `worker_alive`,
  `enqueued`, `written`, `dropped`, `embed_failures`, `write_failures`,
  `last_write_ts` (ISO-8601 or `None`). The call SHALL be O(1) and SHALL NOT
  issue a database round-trip.
- **REQ-305.** All counters in REQ-304 SHALL be monotonically non-decreasing
  for the lifetime of the engine and SHALL be updated under the worker lock so
  concurrent `record()` callers observe consistent values.

### 4.3 Durable step ordering (opt-in)

- **REQ-306.** THE SYSTEM SHALL accept `AgentLog(..., durable_step: bool =
  False)`. WHEN `durable_step` is `True` THE SYSTEM SHALL assign `step` from a
  durable per-`thread_id` atomic counter (a `find_one_and_update($inc)` upsert
  on a sibling counter collection, default `<collection>_counters`) so `step`
  is monotonic across process restarts and across multiple processes writing
  the same `thread_id`. The counter increment SHALL run on the **worker
  thread**, never on the `record()` hot path.
  - *Was (REQ-006):* `step` is an in-memory per-process counter, reset on
    restart ("lossy on purpose", v0.1 `design.md`).
  - *Now:* default behavior is unchanged (in-memory, non-blocking); opting in
    yields cross-process-correct `step`.
- **REQ-307.** WHILE `durable_step` is `False` THE SYSTEM SHALL guard the
  in-memory `_step_counter` mutation with a lock so a single `AgentLog`
  instance shared across threads cannot duplicate or skip `step`.

### 4.4 Non-semantic ordered read API

- **REQ-308.** THE SYSTEM SHALL expose `AgentLog.get_thread(thread_id, *,
  user_id: str | None = None, limit: int | None = None, ascending: bool =
  True) -> list[dict]` returning that thread's log documents ordered by
  `(ts, step)`, backed by `agent_log_thread_ts_idx`. WHEN `user_id` is supplied
  THE SYSTEM SHALL additionally filter on it (defense in depth for multi-tenant
  reads).
- **REQ-309.** THE SYSTEM SHALL expose `AgentLog.get_by_correlation_id(
  correlation_id, *, limit: int | None = None) -> list[dict]` ordered by `ts`.
- **REQ-310.** Both read helpers SHALL return plain decoded dicts with `_id`
  coerced to `str`, and SHALL never raise on an empty result (return `[]`).

### 4.5 Retrieval configurability & quality

- **REQ-311.** `build_tool(collection, embeddings, *, top_k=5,
  search_index=..., vector_index=...)` SHALL forward the index names to
  `AgentLogRetriever`, and `ensure_search_indexes(collection, *,
  embeddings_dim, vector_index=SEARCH_DEFAULT, search_index=...)` SHALL accept
  overridable index names. The DDL path and the query path SHALL use the same
  names so a renamed index never produces silent query/DDL drift.
  - *Fixes:* the consumer's `AGENT_LOG_VECTOR_INDEX` / `AGENT_LOG_SEARCH_INDEX`
    settings being dead config (REVIEW medium; analysis gap #2).
- **REQ-312.** `AgentLogRetriever.invoke(query, *, user_id, thread_id: str |
  None = None, since: datetime | None = None)` SHALL accept optional
  narrowing filters. The `user_id` pre-filter SHALL ALWAYS be applied (INV-004
  preserved); `thread_id`/`since` only further restrict.
- **REQ-313.** WHEN an optional `reranker` (a `langchain_core` document
  compressor / reranker) is supplied to `AgentLogRetriever` or `build_tool`,
  THE SYSTEM SHALL over-fetch (`top_k * fetch_multiplier`, default 3) and
  rerank to `top_k`. IF the reranker raises THEN THE SYSTEM SHALL log a warning
  and fall back to the RRF order (best-effort; never propagates). [usecases
  buy-in Group 8]
- **REQ-314.** `ensure_search_indexes` SHALL additionally map `agent_name`
  (string/token) in the Atlas Search index so structured `$search` can scope
  by agent, not only by the synthesized `agent_log_text`. [analysis addition]

### 4.6 Attribution & correlation

- **REQ-315.** `AgentLogMiddleware(log, *, agent_name: str | None = None)`
  SHALL accept a constructor `agent_name`. WHEN set, it takes precedence over
  `configurable["agent_name"]`. This gives a deepagents subagent an attribution
  seam: attach `AgentLogMiddleware(log, agent_name="researcher")` to that
  subagent's `middleware=[...]`.
  - *Fixes:* "subagent activity never logged / `agent_name` always `main`"
    (REVIEW medium; analysis gap #1, package half).
- **REQ-316.** WHEN `correlation_id` is absent from `configurable` THE adapter
  layer (middleware/callback/node) SHALL derive one with precedence: the
  trace-id parsed from `configurable["traceparent"]` (W3C) → `configurable[
  "x_request_id"]` → a fresh `uuid4` **string**. The `record()` engine SHALL
  remain framework-agnostic and SHALL NOT itself generate ids.

### 4.7 TTL & seeding ergonomics

- **REQ-317.** THE SYSTEM SHALL expose `set_ttl(collection, ttl_seconds: int |
  None)` that creates or updates the TTL `expireAfterSeconds` on
  `agent_log_ts_ttl_idx` via `collMod` (no drop-and-recreate). `ttl_seconds=
  None` SHALL remove the TTL index. On deployments lacking `collMod` it SHALL
  warn-and-skip (mongomock parity with `ensure_search_indexes`). [usecases §10.3]
- **REQ-318.** `AgentLog.record(..., ts: datetime | None = None)` SHALL accept
  an explicit timestamp; `None` defaults to `datetime.now(timezone.utc)`. This
  lets deterministic seeders stop monkey-patching the private
  `core.engine.datetime` symbol. [analysis gap #12]

### 4.8 Defensive depth & logging hygiene

- **REQ-319.** WHEN a super-step `is_final_step` is `True` but
  `build_search_text` returns empty (single-role turn) AND an embedder is
  configured, THE SYSTEM SHALL emit a **rate-limited** (once per `thread_id`)
  warning so operators can detect turns that will be invisible to vector
  search. The document SHALL still be written (INV-002 preserved).
- **REQ-320.** THE SYSTEM SHALL remove the dead `_ = logging` placeholder in
  `retrieval/tool.py` and route all swallowed-error logging through the named
  `langchain_mongodb_agent_log` logger (REQ-040 reaffirmed).

### 4.9 Packaging & publication

- **REQ-321.** Version SHALL be `0.3.0`; `CHANGELOG.md` SHALL gain a `[0.3.0]`
  entry; `pyproject.toml` `[project.urls]` SHALL point to the actual published
  repository (`github.com/mohammaddaoudfarooqi/langchain-mongodb-agent-log`).
- **REQ-322.** THE repository SHALL ship a GitHub Actions CI workflow running
  `ruff check`, `mypy --strict src`, and `pytest` (unit tier) on Python
  3.10/3.11/3.12.
- **REQ-323.** THE built wheel/sdist SHALL install cleanly and re-import the
  full public API; the package SHALL be installable via
  `pip install "git+https://github.com/mohammaddaoudfarooqi/langchain-mongodb-agent-log@v0.3.0"`
  and (with the extra) `...#egg=langchain-mongodb-agent-log[voyage]`.

## 5. Non-functional requirements (v0.3)

- **NFR-300.** `record()` SHALL remain non-blocking (< 5 ms p99, NFR-001) in
  the default configuration. WHEN `durable_step=True` the counter round-trip
  runs on the worker thread, so `record()` latency is unaffected; a parity test
  SHALL assert `record()` return time stays bounded with `durable_step` on and
  Atlas unreachable.
- **NFR-301.** New public symbols SHALL keep `mypy --strict` and `ruff` clean.
- **NFR-302.** Unit tier SHALL stay under ~10 s (NFR-003); new lifecycle tests
  SHALL use small bounded timeouts (≤ 0.5 s) and a deliberately-wedged fake
  worker, never real sleeps > 1 s.
- **NFR-303.** No new mandatory runtime dependency. Rerank (REQ-313) accepts an
  injected reranker; the Voyage reranker stays under the existing `[voyage]`
  extra.

## 6. Premortem

| # | Failure mode | Mitigation (EARS) |
|---|---|---|
| 1 | `durable_step` adds a synchronous Mongo round-trip to the agent hot path, regressing NFR-001. | THE SYSTEM SHALL assign the durable `step` on the worker thread, never in `record()`; a parity test asserts `record()` returns < 5 ms with `durable_step=True` and Atlas unreachable (NFR-300). |
| 2 | `close()`/`atexit` double-joins or deadlocks when the worker is already dead or never started. | `close()` SHALL be idempotent and SHALL guard on `thread.is_alive()`; a test calls `close()` twice and on a never-started engine. |
| 3 | Adding `agent_name` to the Atlas Search mapping silently breaks an existing deployment's index (drift). | REQ-314 mapping change SHALL be additive and `ensure_search_indexes` SHALL stay idempotent (REQ-016); a how-to documents the one-time recreate. An integration test asserts re-running the helper does not raise. |
| 4 | Auto-generated `correlation_id` format diverges from the consumer's server-generated UUID-v4 string, breaking cross-turn joins. | REQ-316 SHALL emit a `uuid4` **string** (matching the consumer's `app.py` format); a unit test asserts the generated id parses as a UUID. |
| 5 | New public symbols break the locked public-API regression test (INV-005) or shadow lazy imports. | INV-005's test SHALL be updated deliberately to include the new symbols; a test asserts every name in `__all__` imports via the lazy `__getattr__` map. |

## 7. Unchanged behavior (invariants)

- **INV-300.** All v0.1/v0.2 public symbols SHALL remain importable; v0.3 only
  **adds** symbols (`set_ttl`, and methods on `AgentLog`). (extends INV-005)
- **INV-301.** `AgentLogRetriever`/`search_past_conversations` SHALL CONTINUE
  TO enforce the mandatory `user_id` pre-filter; new `thread_id`/`since`/rerank
  options SHALL only narrow, never widen, results. (preserves INV-004)
- **INV-302.** `record()` SHALL CONTINUE TO be non-blocking in the default
  configuration. (preserves INV-003/NFR-001)
- **INV-303.** `PyMongoError` and embedder failures SHALL CONTINUE TO be
  swallowed and never reach the agent runtime. (preserves INV-001/INV-002)
- **INV-304.** With no new opt-in flags set, the persisted document schema and
  default `agent_name="main"` / final-step-only embedding behavior SHALL be
  byte-for-byte unchanged; all 80 existing tests SHALL CONTINUE TO pass.
- **INV-305.** The middleware SHALL CONTINUE TO read `thread_id`/`user_id` from
  `langgraph.config.get_config()` with the `runtime.config` fallback (REQ-026).

## 8. Out of scope (v0.3)

- A web UI / dashboard (operators build their own on `stats()` + `get_thread`).
- Multi-process worker coordination beyond the durable `step` counter.
- A bundled `checkpoint_mirror → agent_log` migration tool (stays a consumer
  concern; the consumer ships its own script).
- PyPI publication (v0.3 publishes via Git tag; PyPI is a later release).
- Encryption at rest (caller's Atlas CSFLE responsibility, unchanged).

## 9. Acceptance criteria

- [ ] Every `REQ-3xx` and both `BUG-30x` have ≥ 1 passing test.
- [ ] Every `INV-3xx` has ≥ 1 regression test; all 80 prior tests still pass.
- [ ] Each premortem row has a corresponding test.
- [ ] `ruff check` and `mypy --strict src` clean; unit tier < ~10 s.
- [ ] `uv build` produces a wheel that re-imports the full public API.
- [ ] CI workflow green on 3.10/3.11/3.12.
- [ ] Docs (`reference/api.md`, `document-shape.md`, `how-to/configure-ttl.md`,
      a new `how-to/observability.md` and `how-to/attribute-subagents.md`)
      updated; `CHANGELOG.md` `[0.3.0]` written.
- [ ] Integration tier (`-m integration`, `ATLAS_URI`-gated) covers the durable
      step counter, `get_thread` ordering, `set_ttl` via `collMod`, and rerank
      fallback; clean no-op when `ATLAS_URI` is unset.
