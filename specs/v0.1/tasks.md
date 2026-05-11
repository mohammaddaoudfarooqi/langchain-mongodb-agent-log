# Tasks — `langchain-mongodb-agent-log` v0.1

> Sequenced TDD task list. Companion to `requirements.md` and `design.md`.
> Each task lists its REQ mappings, RED tests to write first, GREEN
> implementation steps, and acceptance criteria.

## Traceability matrix

| Req ID | Test Case IDs | Task | Status |
|---|---|---|---|
| REQ-001 | TC-001 (one-doc-per-step) | T2 | Not started |
| REQ-002 | TC-002 (verbatim message fields) | T2 | Not started |
| REQ-003 | TC-003a (under cap), TC-003b (over cap with marker) | T2 | Not started |
| REQ-004 | TC-004 (todos copied) | T2 | Not started |
| REQ-005 | TC-005a (write+edit→single dedup, edit wins), TC-005b (read_file ignored), TC-005c (custom fs_write_tools) | T2 | Not started |
| REQ-006 | TC-006 (top-level fields present), TC-006b (step monotonic per thread, parent_step) | T2 | Not started |
| REQ-007 | TC-007a (default "main"), TC-007b (configurable agent_name) | T2 / T6 | Not started |
| REQ-008 | TC-008 (missing thread_id → no doc) | T2 | Not started |
| REQ-009 | TC-009 (Bedrock content list coerced to string) | T2 | Not started |
| REQ-010 | TC-010 (final-step embed) | T2 / T3 | Not started |
| REQ-011 | TC-011 (no embed when not final or no embedder) | T2 / T3 | Not started |
| REQ-012 | TC-012 (search text truncated at cap) | T2 | Not started |
| REQ-013 | TC-013 (embedder raises → doc still inserted, search fields absent) | T3 | Not started |
| REQ-014 | TC-014 (regular indexes created idempotently) | T4 | Not started |
| REQ-015 | TC-015 (search + vector indexes — Atlas integration) | T4 / T11 | Not started |
| REQ-016 | TC-016 (re-run no-op) | T4 | Not started |
| REQ-017 | TC-017 (mongomock → warn-and-skip) | T4 | Not started |
| REQ-018 | TC-018 (record returns < 5 ms with Atlas unreachable) | T3 | Not started |
| REQ-019 | TC-019 (FIFO order per thread under load) | T3 | Not started |
| REQ-020 | TC-020 (queue full → warn + drop) | T3 | Not started |
| REQ-021 | TC-021 (flush_for_tests blocks) | T3 | Not started |
| REQ-022 | TC-022 (PyMongoError swallowed) | T3 | Not started |
| REQ-023 | TC-023 (middleware subclasses AgentMiddleware) | T6 | Not started |
| REQ-024 | TC-024 (sync after_model writes one doc, returns None) | T6 | Not started |
| REQ-025 | TC-025 (async aafter_model writes one doc) | T6 | Not started |
| REQ-026 | TC-026 (configurable extracted via get_config and via runtime.config fallback) | T6 | Not started |
| REQ-027 | TC-027 (callback subclasses BaseCallbackHandler) | T7 | Not started |
| REQ-028 | TC-028 (top-level on_chain_end → 1 doc with agent_name=node) | T7 | Not started |
| REQ-029 | TC-029 (inner Runnable on_chain_end ignored — no doc) | T7 | Not started |
| REQ-030 | TC-030 (async callback variant fires) | T7 | Not started |
| REQ-031 | TC-031 (graph node writes doc, returns empty delta) | T8 | Not started |
| REQ-032 | TC-032 (retriever construction; uses Hybrid retriever class) | T9 | Not started |
| REQ-033 | TC-033 (per-user pre_filter applied) | T9 | Not started |
| REQ-034 | TC-034 (@tool returns JSON list with right fields) | T9 | Not started |
| REQ-035 | TC-035 (missing user_id → REFUSED string) | T9 | Not started |
| REQ-036 | TC-036 (retriever raises → "[]") | T9 | Not started |
| REQ-037 | TC-037 (fake embedder accepted) | T2 / T3 | Not started |
| REQ-038 | TC-038a (default_voyage returns embedder when key set), TC-038b (raises when missing) | T10 | Not started |
| REQ-039 | TC-039 (constructor defaults match spec) | T2 | Not started |
| REQ-040 | TC-040 (warning lines emitted with named logger) | T3 | Not started |
| INV-001 | TC-INV-001 (PyMongoError contained) | T3 | Not started |
| INV-002 | TC-INV-002 (embedder failure does not drop doc) | T3 | Not started |
| INV-003 | TC-INV-003 (record < 5 ms even when worker would fail) | T3 | Not started |
| INV-004 | TC-INV-004 (cross-user retrieval blocked) | T9 | Not started |
| INV-005 | TC-INV-005 (public-API import surface) | T11 | Not started |

## Task list

> Inner-loop convention: **Each task starts with RED tests, then GREEN
> implementation, then refactor.** Run only the new + adjacent tests during
> the inner loop; run the full suite at the task boundary.

### T1 — Bootstrap project + tooling

**Status:** [ ] Not started
**Maps to:** none (infrastructure)

Subtasks:
1. Initialize `pyproject.toml` with `uv init --package` (or hand-write
   matching layout). Apache-2.0. Python `>=3.10`. Project name
   `langchain-mongodb-agent-log`.
2. Add deps: `pymongo>=4.6`, `langchain-core>=0.3`, `langchain>=0.3.27`,
   `langgraph>=0.3`, `langchain-mongodb>=0.11`.
3. Add dev deps: `pytest`, `pytest-asyncio`, `mongomock`, `ruff`, `mypy`.
4. Add optional extras: `[voyage] = ["langchain-voyageai>=0.1.6"]`.
5. Configure `[tool.pytest.ini_options]` with `markers = ["integration"]`
   and `asyncio_mode = "auto"`.
6. Configure `[tool.ruff]` for `src` and `tests`. Configure `[tool.mypy]`
   with `strict = true` for `src`.
7. Create directory skeleton from §2 of `design.md`. Populate `__init__.py`
   files (empty for now; the public API re-exports come in T11).
8. Write a smoke test under `tests/unit/test_bootstrap.py`:
   ```python
   def test_package_metadata():
       import langchain_mongodb_agent_log as p
       assert p.__name__ == "langchain_mongodb_agent_log"
   ```
9. Run `uv sync --all-extras && uv run pytest`. Must pass.

**Acceptance:** `uv sync` works, `uv run pytest` is green, `uv run ruff
check src tests` is clean, `uv run mypy --strict src` is clean.

### T2 — Engine: projection + record (no I/O)

**Status:** [ ] Not started
**Maps to:** REQ-001..009, REQ-039, REQ-007a (default agent_name), REQ-037

Subtasks:
1. RED tests in `tests/unit/test_projection.py`:
   - TC-001..009 from the matrix above.
   - Use `unittest.mock.MagicMock` for messages; supply `type`, `content`,
     `tool_calls`, `tool_call_id`, `usage_metadata`, `additional_kwargs`.
2. RED tests in `tests/unit/test_engine.py`:
   - TC-006b (step monotonic per `thread_id`, parent_step correct)
   - TC-008 (missing thread_id → no enqueue)
   - TC-039 (constructor defaults)
3. GREEN: implement `core/projection.py`:
   - `project_messages(raw, *, cap)`
   - `project_todos(raw)`
   - `project_files(messages, *, fs_write_tools)`
   - `coerce_content(message)` (string or list-of-blocks → string)
   - `truncate(text, cap)`
   - `is_final_step(messages_proj)`
   - `build_search_text(messages_proj, cap)`
4. GREEN: implement `core/engine.py`:
   - `AgentLog.__init__` accepts the constructor signature from §4 of
     `design.md`. Worker is created lazily on first `record()`.
   - `AgentLog.record(...)` builds the doc and enqueues. **No real
     pymongo write yet** — for T2 the worker is a stub that just stores
     the doc on a list, exposed for tests to read.
5. Verify all T2 tests green; existing T1 tests still pass.

**Acceptance:** projection tests + engine doc-shape tests pass.

### T3 — Worker: queue + daemon + flush + error swallow

**Status:** [ ] Not started
**Maps to:** REQ-010, REQ-011, REQ-013, REQ-018..022, REQ-040, INV-001..003

Subtasks:
1. RED tests in `tests/unit/test_worker.py`:
   - TC-018: record returns in < 5 ms even when `insert_one` blocks
     (use `time.sleep(0.5)` in a patched insert).
   - TC-019: enqueue 50 docs across 2 thread_ids, flush, assert
     per-thread step ordering preserved.
   - TC-020: enqueue 300 docs with `queue_maxsize=10`; assert at most 10
     docs reach the collection and a warning is logged.
   - TC-021: `flush_for_tests` blocks until `task_done` count reaches
     enqueued count.
   - TC-022 / TC-INV-001: `insert_one` raises `PyMongoError`; assert
     no propagation, warning logged.
   - TC-013 / TC-INV-002: embedder.embed_query raises; assert doc still
     inserted, no `agent_log_text` / `agent_log_embedding` fields.
   - TC-010: final super-step → embedder called once, both fields set.
   - TC-011a: non-final super-step → no embedder call.
   - TC-011b: no embedder configured → no embedder fields.
   - TC-040: warnings use logger name `langchain_mongodb_agent_log`.
2. GREEN: replace the T2 stub worker with the real `_MirrorWorker` from
   §5 of `design.md`. Keep `flush_for_tests` accessible from the engine.
3. Verify the previous T2 tests still pass (no regressions).

**Acceptance:** all worker tests green; `caplog` confirms named-logger
warning lines.

### T4 — Indexes: regular + Atlas DDL helpers

**Status:** [ ] Not started
**Maps to:** REQ-014..017

Subtasks:
1. RED tests in `tests/unit/test_indexes.py`:
   - TC-014: call `ensure_agent_log_indexes(coll)`, assert all four
     regular indexes appear in `coll.list_indexes()`. Use mongomock.
   - TC-016: re-run; no exception, no extra indexes.
   - TC-017: call `ensure_search_indexes(coll, embeddings_dim=1024)` on
     mongomock; assert it doesn't raise (warns and returns).
2. RED test in `tests/unit/test_indexes.py`:
   - TC-014b: TTL index is created when `ttl_seconds` supplied.
3. GREEN: implement `core/indexes.py` per §8 of design.md.
4. Atlas-gated integration (deferred to T11) covers TC-015.

**Acceptance:** unit index tests green; `ensure_search_indexes` warns
politely on mongomock and returns.

### T5 — Bedrock content coercion + correlation_id polish

**Status:** [ ] Not started
**Maps to:** REQ-009 (full coverage), REQ-006 (correlation_id)

Subtasks:
1. RED tests:
   - TC-009: a message whose `content` is `[{"type":"text","text":"hi"},
     {"type":"text","text":" world"}]` projects to `"hi world"`.
   - TC-009b: non-text blocks are dropped silently (Bedrock tool_use
     blocks).
   - TC-006b: correlation_id explicitly empty when absent; explicitly
     copied when present.
2. GREEN: tighten `coerce_content` and engine projection.

**Acceptance:** content-coercion edge cases all green.

### T6 — Middleware adapter (sync + async)

**Status:** [ ] Not started
**Maps to:** REQ-023..026, REQ-007b

Subtasks:
1. RED tests in `tests/unit/test_middleware.py`:
   - TC-023: `AgentLogMiddleware` is a subclass of
     `langchain.agents.middleware.AgentMiddleware`.
   - TC-024: calling sync `after_model` enqueues exactly one doc and
     returns None.
   - TC-025: calling `aafter_model` (await) enqueues exactly one doc.
   - TC-026a: when `langgraph.config.get_config()` is monkeypatched to
     return a config with `configurable`, the adapter uses it.
   - TC-026b: when `get_config()` raises, the adapter falls back to
     `runtime.config["configurable"]`.
   - TC-007b: `configurable["agent_name"]="researcher"` lands on the doc.
2. GREEN: implement `adapters/middleware.py` per §6.1 of design.md.
3. Add `pytest-asyncio` markers / `asyncio_mode = "auto"` if not yet on.

**Acceptance:** sync + async middleware tests pass; config-extraction
fallback verified.

### T7 — Callback handler adapter (sync + async)

**Status:** [ ] Not started
**Maps to:** REQ-027..030

Subtasks:
1. RED tests in `tests/unit/test_callback.py`:
   - TC-027: subclass of `BaseCallbackHandler`.
   - TC-028: calling `on_chain_end` with `metadata={"langgraph_node":
     "supervisor","thread_id":"t","user_id":"u"}` enqueues 1 doc with
     `agent_name="supervisor"`.
   - TC-029: calling with `metadata={}` (no `langgraph_node`) enqueues 0
     docs.
   - TC-030: `on_chain_end_async` produces the same outcome.
2. GREEN: implement `adapters/callback.py` per §6.2 of design.md.

**Acceptance:** callback filter test green; inner-Runnable noise
correctly ignored.

### T8 — Explicit graph-node adapter

**Status:** [ ] Not started
**Maps to:** REQ-031

Subtasks:
1. RED test in `tests/unit/test_node.py`:
   - TC-031: `agent_log_node(log)` returns a callable. Invoking it with
     a mock state + config enqueues 1 doc and returns `{}`.
2. GREEN: implement `adapters/node.py` per §6.3.

**Acceptance:** TC-031 green.

### T9 — Retriever + `search_past_conversations` tool

**Status:** [ ] Not started
**Maps to:** REQ-032..036, INV-004

Subtasks:
1. RED tests in `tests/unit/test_retriever.py`:
   - TC-032: `AgentLogRetriever` constructs a
     `MongoDBAtlasHybridSearchRetriever` (assert via patched
     constructor).
   - TC-033: per-user `pre_filter={"user_id": {"$eq": user_id}}` is
     passed to the underlying retriever.
   - TC-INV-004: a doc with `user_id="alice"` is filtered out when
     querying as `bob` (assert at the pre_filter level since we mock
     the retriever's downstream).
2. RED tests in `tests/unit/test_tool.py`:
   - TC-034: `.invoke(query, config={"configurable":{"user_id":"u1"}})`
     returns valid JSON list with the spec-required fields.
   - TC-035: missing `user_id` → exact string `"REFUSED: missing
     user_id in config"`.
   - TC-036: simulated retriever exception → returns `"[]"` and logs.
3. GREEN: implement `retrieval/retriever.py` + `retrieval/tool.py` per
   §7 of design.md. Use `lru_cache(maxsize=1)` on the
   `MongoDBAtlasVectorSearch` handle factory.

**Acceptance:** retriever + tool unit tests green; pre-filter assertion
verifies INV-004.

### T10 — Voyage default factory

**Status:** [ ] Not started
**Maps to:** REQ-038

Subtasks:
1. RED tests in `tests/unit/test_voyage_factory.py`:
   - TC-038a: with `VOYAGE_API_KEY=test` and `langchain_voyageai`
     importable, `default_voyage()` returns a `VoyageAIEmbeddings`
     instance. (If `langchain_voyageai` isn't installed in the dev
     env, skip with reason.)
   - TC-038b: with the env var unset, raises `RuntimeError` whose
     message contains `"VOYAGE_API_KEY"`.
2. GREEN: implement `embeddings/factory.py`. Make import lazy so the
   package doesn't hard-require `langchain-voyageai`.

**Acceptance:** factory tests green under both conditions.

### T11 — Multi-graph integration tests + public API surface

**Status:** [ ] Not started
**Maps to:** REQ-015 (Atlas-gated), INV-005, end-to-end coverage

Subtasks:
1. Public API surface — RED test in `tests/unit/test_public_api.py`:
   - TC-INV-005: assert every name in §9 of design.md is importable
     from `langchain_mongodb_agent_log`.
2. GREEN: re-export per §9 in `__init__.py`. Use `__getattr__` for
   adapter classes to avoid eager `langchain.agents` import on
   `import langchain_mongodb_agent_log`.
3. Graph-shape integration (uses `FakeMessagesListChatModel` from
   `langchain_core.language_models.fake_chat_models`):
   - **Shape A — `create_agent` single.** Build an agent with
     `MirrorMiddleware`. Invoke with a planted prompt. Flush. Assert one
     doc with `agent_name="main"`.
   - **Shape B — `create_agent` multi-agent supervisor.** Build a
     supervisor that uses `Send` to dispatch to two workers. Each agent
     has its own middleware instance pointing at the same engine. Each
     agent's `configurable["agent_name"]` is set per dispatch. After the
     turn, assert there's at least one doc per `agent_name in
     {"supervisor", "researcher", "writer"}`.
   - **Shape C — bare `StateGraph`.** Hand-rolled supervisor + 2
     specialist nodes calling `llm.invoke` directly. Use the callback
     adapter at `graph.invoke(..., config={"callbacks":[h]})`. Assert
     one doc per super-step, attributed by node name.
   - **Shape D — mixed.** Supervisor as raw node + workers as
     `create_agent` instances. Middleware on each worker, callback at
     graph root. Assert no double-write per step (the callback's
     `langgraph_node` filter and the middleware's per-agent firing
     don't overlap on the same step).
4. Async smoke test in `tests/integration/test_async_invocation.py`:
   - Build a single `create_agent` with the middleware. Call
     `await graph.ainvoke(...)`. Flush. Assert exactly one doc with
     `agent_log_embedding` populated (final step).
5. Atlas-gated tests in `tests/integration/test_atlas_*.py`:
   - Skip when `ATLAS_URI` env unset. Otherwise: provision indexes,
     wait until `queryable=True`, plant 5 docs, run RRF query, assert
     the planted match ranks #1.

**Acceptance:** all four graph shapes green on unit tier (no Atlas
required); async smoke green; integration tier passes when `ATLAS_URI`
set, no-ops cleanly when unset.

### T12 — Documentation

**Status:** [ ] Not started
**Maps to:** Acceptance §8 last bullet

Per Diataxis, deliver:

- **README.md** at repo root — value prop, 60-second quickstart,
  pointers into `docs/`.
- **Tutorial** (`docs/tutorial/first-log.md`) — a learner walks from
  empty repo to "I can see my first agent turn in MongoDB" in <10 min.
  Tutorials are *learning-oriented*; this one assumes nothing.
- **Tutorial** (`docs/tutorial/hybrid-search.md`) — adds the search
  tool, builds an agent that recalls itself.
- **How-to guides** (`docs/how-to/`) — *task-oriented*. One file per
  use case:
  - `deepagents.md`
  - `create-agent.md` (single agent)
  - `multi-agent-supervisor.md` (Send + agent_name)
  - `bare-stategraph.md` (callback adapter)
  - `migrate-from-create-react-agent.md` (specifically for the
    `mongodb-langchain-agentic-ai` repo shape)
  - `configure-ttl.md`
  - `provide-custom-embeddings.md`
- **Reference** (`docs/reference/`) — *information-oriented*.
  - `api.md`: every name in `__all__` with signature + behavior.
  - `document-shape.md`: the persisted JSON schema, field-by-field.
  - `indexes.md`: index DDL, Atlas Search / Vector Search definitions.
  - `configuration.md`: constructor args + defaults.
- **Explanation** (`docs/explanation/`) — *understanding-oriented*.
  - `architecture.md`: engine/adapter boundary, the worker, why FIFO.
  - `why-not-checkpointer.md`: differentiation from `MongoDBSaver`.
  - `langsmith-comparison.md`: where this fits next to LangSmith.
- `docs/README.md` is a one-page index linking all four quadrants.

**Acceptance:** every link in the index resolves; quickstart works
copy-pasted from a fresh shell.

### T13 — Final verification

**Status:** [ ] Not started
**Maps to:** Acceptance §8

Subtasks:
1. `uv run pytest -x` — full unit tier green.
2. `uv run pytest -m integration` — clean no-op when `ATLAS_URI`
   unset.
3. `uv run ruff check src tests` — clean.
4. `uv run mypy --strict src` — clean.
5. `uv build` — wheel + sdist produced.
6. `uv run python -c "import langchain_mongodb_agent_log as p; print([n for n in dir(p) if not n.startswith('_')])"` —
   all `__all__` names resolve.
7. Walk every requirement in the traceability matrix; mark Status
   column to `Passing` or fail.

**Acceptance:** every box in `requirements.md §8` is checked.

## Critical-path dependency graph

```
T1 ─┬─ T2 ─┬─ T3 ─┬─ T4
    │      │      ├─ T5
    │      │      ├─ T6 ─┬─ T11
    │      │      ├─ T7 ─┤
    │      │      └─ T8 ─┤
    │      │             │
    │      └────── T9 ───┤
    │                    │
    └────────── T10 ─────┘
                         │
                       T12 (parallel with T11; depends on T2..T10 for accuracy)
                         │
                       T13
```

T6, T7, T8, T9, T10 can be parallelized once T3 lands, but for a
single-pass execution we go in order to keep RED→GREEN focused.
