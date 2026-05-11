# Requirements — `langchain-mongodb-agent-log` v0.1

> Greenfield package. All requirements in this document use prefix `REQ-001`
> through `REQ-NNN`. Invariants use `INV-NNN`. Glossary at the bottom.

## 1. Vision

A MongoDB-backed, hybrid-searchable, append-only log of agent activity that
plugs into modern LangChain agents (`create_agent`, deepagents, multi-agent
supervisors using `Send`/`Command`) via middleware, into bare LangGraph
`StateGraph`s via callbacks, and into any graph via an explicit node. The log
is decoded JSON (not opaque checkpointer state), per-user scoped, and exposes
hybrid (vector + lexical) retrieval over the user's history so the agent
itself can recall prior conversations.

## 2. Stakeholders & Personas

- **P1 — Application engineer.** Builds agent products on `create_agent` /
  deepagents / LangGraph. Wants observability, audit, and per-user recall
  without standing up new infrastructure.
- **P2 — Compliance engineer.** Needs decoded conversation data in the
  customer's own database (Atlas), not in a third-party SaaS. Needs
  per-user retention controls.
- **P3 — Eval engineer.** Wants to query agent behavior across runs (which
  tools, which files, what content) without deserializing checkpointer blobs.
- **P4 — Library maintainer.** Wants to add custom adapters or projection
  fields without forking.

## 3. Functional requirements (EARS)

### 3.1 Storage core

- **REQ-001.** THE SYSTEM SHALL persist one log document per agent
  super-step boundary into a configurable MongoDB collection.
- **REQ-002.** THE SYSTEM SHALL store messages verbatim. Message content,
  `tool_calls`, `tool_call_id`, `usage_metadata`, `model_id`, and
  `finish_reason` shall be present on each projected message when supplied
  by the upstream LangChain message.
- **REQ-003.** WHEN a message's content exceeds the configured byte cap
  THE SYSTEM SHALL truncate it and append a `[truncated, original_size=N
  bytes]` marker.
- **REQ-004.** THE SYSTEM SHALL project the agent's `todos` (deepagents-
  shaped: `{id, content, status}`) onto the document when present in state.
- **REQ-005.** THE SYSTEM SHALL derive a `files_touched` array from
  filesystem-modifying tool calls in the super-step's AI messages
  (default: `write_file`, `edit_file`). Read-only tools SHALL NOT
  contribute. The set of FS-write tool names SHALL be configurable on
  the engine.
- **REQ-006.** THE SYSTEM SHALL stamp every document with `thread_id`,
  `user_id`, `agent_name`, `step` (monotonic per `thread_id`),
  `parent_step` (one less, or `null` at step 0), `ts` (UTC datetime),
  `correlation_id` (string, empty when absent).
- **REQ-007.** THE SYSTEM SHALL leave `agent_name` as `"main"` when the
  caller does not supply one (single-agent case). WHEN
  `configurable["agent_name"]` is set THE SYSTEM SHALL record that value.
- **REQ-008.** WHEN `thread_id` or `user_id` is missing from the runtime
  configurable THE SYSTEM SHALL skip the write and return `None`.
- **REQ-009.** THE SYSTEM SHALL produce documents whose JSON shape is
  human-readable (no opaque BSON binary blobs). Non-string content
  blocks (Bedrock-style structured content lists) SHALL be coerced to
  strings on write.

### 3.2 Hybrid search enrichment

- **REQ-010.** WHEN the super-step is the *final* step of a user-visible
  turn (last AI message has no pending `tool_calls`) AND an `Embeddings`
  object was supplied to the engine THE SYSTEM SHALL compute and store
  `agent_log_text` (joint human prompt + final AI reply) and
  `agent_log_embedding` (the Voyage / configured embedder's vector for
  that text) on the document.
- **REQ-011.** WHEN the super-step is not the final step OR no embedder
  is supplied THE SYSTEM SHALL omit `agent_log_text` and
  `agent_log_embedding` from the document.
- **REQ-012.** WHEN computing `agent_log_text` THE SYSTEM SHALL truncate
  to a configurable byte cap (default 8 KiB) before embedding to bound
  the embedder payload.
- **REQ-013.** IF the embedder raises THEN THE SYSTEM SHALL log a warning
  and persist the document without the search fields rather than
  dropping the document.

### 3.3 Index management

- **REQ-014.** THE SYSTEM SHALL provide an idempotent
  `ensure_agent_log_indexes(collection, *, embeddings_dim, ttl_seconds)`
  helper that creates regular indexes:
  - `(thread_id, step)`
  - `(thread_id, ts DESC)`
  - `(user_id, ts DESC)`
  - `(ts ASC)` with `expireAfterSeconds=ttl_seconds` when `ttl_seconds`
    is supplied (TTL index optional).
- **REQ-015.** THE SYSTEM SHALL provide a separate idempotent
  `ensure_search_indexes(collection, *, embeddings_dim)` helper that
  creates the Atlas Search index `agent_log_search_idx` on
  `agent_log_text` and the Atlas Vector Search index
  `agent_log_vector_idx` on `agent_log_embedding` with `cosine`
  similarity and the supplied dimension.
- **REQ-016.** Both index helpers SHALL no-op cleanly if the indexes
  already exist (re-running them does not raise).
- **REQ-017.** IF the MongoDB deployment does not support
  `createSearchIndex` (older server, mongomock, etc.) THEN
  `ensure_search_indexes` SHALL log a warning and skip index creation
  rather than raise.

### 3.4 Hot-path performance

- **REQ-018.** THE SYSTEM SHALL NOT block the agent super-step on the
  MongoDB write or the embedding round-trip. Persistence work SHALL run
  on a process-lifetime daemon worker thread.
- **REQ-019.** THE SYSTEM SHALL preserve insert order per `thread_id`
  (FIFO) by using a single worker thread.
- **REQ-020.** WHEN the worker queue is full (default capacity 256) THE
  SYSTEM SHALL drop the oldest excess by emitting a warning log line
  and skipping the enqueue rather than blocking the agent step or
  raising.
- **REQ-021.** THE SYSTEM SHALL expose a test-only
  `flush_for_tests(timeout_seconds)` helper that blocks until the queue
  drains so unit tests can assert on persisted documents.
- **REQ-022.** IF the persistence write raises a `PyMongoError` THEN
  THE SYSTEM SHALL log a warning and continue. The agent turn SHALL NOT
  see the failure.

### 3.5 Adapters

#### 3.5.1 Middleware (primary surface)

- **REQ-023.** THE SYSTEM SHALL expose
  `AgentLogMiddleware(log: AgentLog)` that subclasses
  `langchain.agents.middleware.AgentMiddleware`.
- **REQ-024.** `AgentLogMiddleware.after_model(state, runtime)` SHALL
  enqueue one log document per invocation. The method SHALL return
  `None` (no state mutation).
- **REQ-025.** THE SYSTEM SHALL also expose an async
  `aafter_model(state, runtime)` with identical semantics for async
  agent invocations (`graph.ainvoke`).
- **REQ-026.** `AgentLogMiddleware` SHALL extract `thread_id`,
  `user_id`, `correlation_id`, and `agent_name` from
  `RunnableConfig.configurable` via `langgraph.config.get_config()` when
  available, falling back to `runtime.config["configurable"]`.

#### 3.5.2 Callback (bare StateGraph / mixed graphs)

- **REQ-027.** THE SYSTEM SHALL expose
  `AgentLogCallbackHandler(log: AgentLog)` that subclasses
  `langchain_core.callbacks.BaseCallbackHandler`.
- **REQ-028.** WHEN `on_chain_end` fires for a top-level LangGraph node
  (identifiable via `metadata["langgraph_node"]`) THE SYSTEM SHALL
  enqueue one log document, attributing `agent_name = metadata["langgraph_node"]`.
- **REQ-029.** WHEN `on_chain_end` fires for inner Runnables that are
  not LangGraph supersteps (no `langgraph_node` in metadata) THE
  SYSTEM SHALL ignore them — no doc is written.
- **REQ-030.** THE SYSTEM SHALL also implement `on_chain_end_async` to
  cover async invocations.

#### 3.5.3 Explicit graph node

- **REQ-031.** THE SYSTEM SHALL expose
  `agent_log_node(log: AgentLog) -> Callable[[State, RunnableConfig], dict]`
  that, when wired into a `StateGraph`, enqueues one document per
  invocation and returns an empty state delta.

### 3.6 Retrieval

- **REQ-032.** THE SYSTEM SHALL expose
  `AgentLogRetriever(collection, embeddings, *, search_index, vector_index, top_k)`
  built on `langchain_mongodb.retrievers.MongoDBAtlasHybridSearchRetriever`
  (RRF fusion of `$search` + `$vectorSearch`).
- **REQ-033.** `AgentLogRetriever.invoke(query, *, user_id)` SHALL
  apply `pre_filter={"user_id": {"$eq": user_id}}` so a user's
  retrieval results never include another user's threads.
- **REQ-034.** THE SYSTEM SHALL expose a prebuilt LangChain `@tool`
  named `search_past_conversations(query, k=5)` that reads `user_id`
  from the active `RunnableConfig.configurable` and returns a JSON
  string of `[{thread_id, step, ts, snippet, agent_name, model_id}, ...]`.
- **REQ-035.** IF `RunnableConfig.configurable.user_id` is missing
  THEN `search_past_conversations` SHALL return
  `"REFUSED: missing user_id in config"`.
- **REQ-036.** IF the retriever raises (Atlas unreachable, invalid
  index, etc.) THEN `search_past_conversations` SHALL log a warning
  and return `"[]"` rather than propagate.

### 3.7 Embeddings

- **REQ-037.** `AgentLog.__init__` SHALL accept any
  `langchain_core.embeddings.Embeddings` instance; the package SHALL
  NOT hard-depend on a specific provider.
- **REQ-038.** THE SYSTEM SHALL expose a
  `embeddings.default_voyage()` factory that returns a configured
  `langchain_voyageai.VoyageAIEmbeddings` when `VOYAGE_API_KEY` is
  set in the environment, raising a `RuntimeError` with a clear
  message otherwise. The Voyage extra SHALL be optional
  (`pip install langchain-mongodb-agent-log[voyage]`).

### 3.8 Configuration

- **REQ-039.** `AgentLog` SHALL accept the following named arguments
  with stated defaults:
  - `collection` (required) — `pymongo.collection.Collection`
  - `embeddings` (default `None`)
  - `fs_write_tools` (default `frozenset({"write_file", "edit_file"})`)
  - `max_content_bytes` (default `15 * 1024 * 1024`)
  - `max_search_text_bytes` (default `8 * 1024`)
  - `queue_maxsize` (default `256`)

### 3.9 Observability

- **REQ-040.** THE SYSTEM SHALL emit a single warning-level log line
  per swallowed `PyMongoError`, embedder failure, or queue-full event
  using a Python logger named `langchain_mongodb_agent_log`.

## 4. Non-functional requirements

- **NFR-001.** Hot-path latency overhead per super-step < 5 ms p99 in
  the absence of queue backpressure (single `Queue.put_nowait` plus
  projection cost only).
- **NFR-002.** Worker memory bound: queue capacity × largest doc size.
  At default 256 × 16 MiB max doc this is theoretically 4 GiB; in
  practice docs are < 1 MiB so the working set stays under ~256 MiB
  even under max backpressure.
- **NFR-003.** Test suite — unit tier — completes in under 10 seconds
  on a developer laptop.
- **NFR-004.** Python ≥ 3.10. `langchain-core` ≥ 0.3, `langchain` ≥
  0.3.27 (for `create_agent`), `langgraph` ≥ 0.3,
  `langchain-mongodb` ≥ 0.11, `pymongo` ≥ 4.6.
- **NFR-005.** `ruff` and `mypy --strict` MUST be clean against
  `src/`.
- **NFR-006.** Apache-2.0 licensed. PyPI-publishable build artifact.
  Not actually published in v0.1.

## 5. Invariants (regression guards)

(Stated as if for a hypothetical future v0.2; v0.1 has no prior code,
so these are forward-looking commitments enforced by tests.)

- **INV-001.** A `PyMongoError` during persistence SHALL never propagate
  to the agent runtime.
- **INV-002.** An embedder failure SHALL never drop the storage write
  for that document.
- **INV-003.** `AgentLog.record(...)` SHALL never block on a network
  call (assertion: time-to-return < 5 ms even with Atlas unreachable).
- **INV-004.** `search_past_conversations` SHALL never return another
  user's results; the per-user pre-filter is mandatory.
- **INV-005.** The package public API SHALL be importable as
  `from langchain_mongodb_agent_log import AgentLog,
  AgentLogMiddleware, AgentLogCallbackHandler, agent_log_node,
  AgentLogRetriever, search_past_conversations,
  ensure_agent_log_indexes, ensure_search_indexes`.

## 6. Out of scope (v0.1)

- Replay / time-travel from agent log docs (use `MongoDBSaver` for that).
- Reading or replaying LangGraph `pending_writes` (saver's job).
- Multi-process worker coordination (one worker per process).
- A web UI / dashboard.
- Encryption at rest for the log collection (caller's responsibility
  via Atlas client-side field-level encryption).
- Automatic migration from `mongodb-langchain-deep-agents`'s
  `checkpoint_mirror` collection (separate concern; documented as a
  how-to, not bundled).
- LangSmith bridge / dual-write.
- Cross-user retrieval (deliberate — the per-user pre-filter is an
  invariant).

## 7. Glossary

- **Agent log** — one append-only document per super-step. Decoded JSON,
  human-readable, queryable.
- **Super-step** — a single LangGraph node-completion / `after_model`
  hook firing.
- **Engine** — `AgentLog` instance. Owns the worker, projection, and
  write path. Framework-agnostic.
- **Adapter** — thin shim that converts a hook (middleware, callback,
  graph node) into a single `engine.record(...)` call.
- **Final step** — a super-step whose last AI message has no pending
  `tool_calls`. The user-visible reply for a turn. Embedding fires
  exactly once here per turn.
- **`agent_name`** — string attribution. Defaults to `"main"`. Set to
  the LangGraph node name (callback adapter) or the
  `configurable["agent_name"]` value (middleware adapter) in
  multi-agent setups.

## 8. Acceptance criteria (for v0.1 release)

The release is complete when ALL of these hold:

- [ ] All `REQ-*` requirements have ≥ 1 passing test.
- [ ] All `INV-*` invariants have ≥ 1 regression test.
- [ ] `uv run pytest` (unit) is green; takes < 10 s on a laptop.
- [ ] `uv run pytest -m integration` is a clean no-op when
      `ATLAS_URI` is unset.
- [ ] `uv run ruff check src tests` is clean.
- [ ] `uv run mypy --strict src` is clean.
- [ ] All four graph shapes from the test plan integrate cleanly
      (deepagents, `create_agent` single, `create_agent` multi-agent
      via `Send`, bare `StateGraph`, mixed).
- [ ] Async `ainvoke` smoke test passes.
- [ ] `pyproject.toml` builds via `uv build`; the resulting wheel
      installs and re-imports the public symbols.
- [ ] Documentation set complete per Diataxis quadrants (tutorial,
      how-to, reference, explanation), README has a 60-second
      quickstart, and an upstream-multi-agent-ai migration how-to
      shows the callback path against the older `create_react_agent`
      shape.
