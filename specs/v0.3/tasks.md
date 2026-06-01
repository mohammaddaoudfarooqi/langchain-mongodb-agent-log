# Tasks — `langchain-mongodb-agent-log` v0.3

Strict TDD per task: write failing test(s) → confirm RED → minimal GREEN → run
full suite → refactor → demo. Sequenced most-self-contained first; the suite
stays green at every task boundary. `uv run pytest -q` is the runner.

## Traceability matrix

| Req | Test case IDs | Status |
|---|---|---|
| BUG-301 (drop oldest) | TC-301-drop-oldest | **Passing** |
| BUG-302 (bounded flush) | TC-302-flush-timeout, TC-302-flush-ok | **Passing** |
| REQ-300 (close) | TC-300-close-drains, TC-300-close-idempotent | **Passing** |
| REQ-301 (flush) | TC-301-flush-bounded | **Passing** |
| REQ-302 (closed guard) | TC-302-closed-noop | **Passing** |
| REQ-303 (atexit) | TC-303-atexit-registered, TC-303-opt-out | **Passing** |
| REQ-304/305 (stats) | TC-304-stats-shape, TC-305-counters-monotonic | **Passing** |
| REQ-306 (durable step) | TC-306-seq, TC-306-restart-sim, TC-INT-306 | Not started |
| REQ-307 (lock) | TC-307-concurrent-record | Not started |
| REQ-308 (get_thread) | TC-308-order, TC-308-user-filter, TC-308-empty | Not started |
| REQ-309 (get_by_correlation_id) | TC-309-order | Not started |
| REQ-310 (decoded dicts) | TC-310-id-str | Not started |
| REQ-311 (index names) | TC-311-names-forwarded | Not started |
| REQ-312 (retriever filters) | TC-312-prefilter-compound, TC-312-user-always | Not started |
| REQ-313 (rerank) | TC-313-rerank-applied, TC-313-rerank-fallback | Not started |
| REQ-314 (agent_name mapping) | TC-314-search-mapping | Not started |
| REQ-315 (agent_name override) | TC-315-ctor-override, TC-315-precedence | Not started |
| REQ-316 (correlation derive) | TC-316-traceparent, TC-316-xreqid, TC-316-uuid | Not started |
| REQ-317 (set_ttl) | TC-317-warn-skip, TC-INT-317 | Not started |
| REQ-318 (ts injection) | TC-318-explicit-ts, TC-318-default-now | Not started |
| REQ-319 (single-role warn) | TC-319-warn-once | Not started |
| REQ-320 (logging hygiene) | TC-320-no-placeholder (ruff/grep) | Not started |
| REQ-321/322/323 (packaging) | TC-321-version, TC-323-wheel-imports, CI green | Not started |
| INV-300 (public API) | TC-INV-300-public-api (extend existing) | Not started |
| INV-301 (user pre-filter) | TC-INV-301-user-scope | Not started |
| INV-302/NFR-300 (non-blocking) | TC-NFR-300-record-fast | Not started |
| INV-303 (swallow errors) | existing TC (worker) | Passing (baseline) |
| INV-304 (schema unchanged) | all 80 baseline tests | Passing (baseline) |

## Task 1 — Worker reliability: drop-oldest, bounded drain, close/flush, stats
- Req: BUG-301, BUG-302, REQ-300, REQ-301, REQ-304, REQ-305, NFR-300, INV-302/303/304
- Files: `core/worker.py`, `core/engine.py` (MODIFY); `tests/unit/test_worker.py`,
  `tests/unit/test_lifecycle.py`, `tests/unit/test_stats.py` (ADD/EXTEND)
- Tests first: full queue evicts head not new doc; `flush(0.001)` on a wedged
  fake worker returns False / `flush_for_tests` raises TimeoutError; `close()`
  drains then is idempotent; `stats()` shape + monotonic counters; `record()`
  returns < 5 ms with a blackholed collection.
- Acceptance: new tests green, all 80 prior green.
- **Demo:** `python -c` snippet recording N docs, printing `stats()` and
  `close()` result; paste output.

## Task 2 — Closed-engine guard + atexit
- Req: REQ-302, REQ-303
- Files: `core/engine.py` (MODIFY); `tests/unit/test_lifecycle.py` (EXTEND)
- Tests: post-`close()` `record()` is a no-op + warns once; `atexit` hook
  registered by default, absent when `flush_on_exit=False`.

## Task 3 — Durable step counter (opt-in) + in-memory lock
- Req: REQ-306, REQ-307, NFR-300
- Files: `core/engine.py`, `core/worker.py` (MODIFY); `tests/unit/test_engine.py`,
  `tests/integration/test_durable_step.py` (ADD)
- Tests: with `durable_step=True` on mongomock, two sequential "process"
  instances continue `step` (restart sim); concurrent `record()` under a shared
  engine never duplicates `step`; `record()` stays non-blocking.

## Task 4 — Ordered read API
- Req: REQ-308, REQ-309, REQ-310, INV-301
- Files: `core/engine.py` (MODIFY); `tests/unit/test_read_api.py` (ADD)
- Tests: `get_thread` ordered by (ts, step) asc/desc, user filter, `[]` on
  empty; `get_by_correlation_id` ordered by ts; `_id` coerced to str.

## Task 5 — Index name params, agent_name mapping, set_ttl
- Req: REQ-311, REQ-314, REQ-317
- Files: `core/indexes.py`, `__init__.py` (MODIFY); `tests/unit/test_indexes.py`,
  `tests/unit/test_set_ttl.py` (ADD/EXTEND)
- Tests: `ensure_search_indexes(..., vector_index='x', search_index='y')` uses
  the passed names; search mapping includes `agent_name`; `set_ttl` warn-skips
  on mongomock; `set_ttl` in `__all__`.

## Task 6 — Retriever filters + best-effort rerank
- Req: REQ-312, REQ-313, INV-301
- Files: `retrieval/retriever.py`, `retrieval/tool.py` (MODIFY);
  `tests/unit/test_retriever.py`, `tests/unit/test_rerank.py` (ADD/EXTEND)
- Tests (fake vector store + fake reranker): compound pre-filter includes
  user_id always + thread_id/since when given; rerank applied on success;
  rerank exception falls back to RRF order without raising; index names
  forwarded by `build_tool`.

## Task 7 — Attribution + correlation derivation
- Req: REQ-315, REQ-316
- Files: `adapters/middleware.py`, `adapters/callback.py`, `adapters/node.py`,
  a shared `adapters/_correlation.py` (ADD); `tests/unit/test_middleware.py`,
  `tests/unit/test_correlation.py` (ADD/EXTEND)
- Tests: ctor `agent_name` beats configurable; correlation precedence
  traceparent→x_request_id→uuid4-string; generated id parses as UUID.

## Task 8 — ts injection, single-role warning, logging hygiene
- Req: REQ-318, REQ-319, REQ-320
- Files: `core/engine.py`, `retrieval/tool.py` (MODIFY); `tests/unit/test_engine.py`,
  `tests/unit/test_tool.py` (EXTEND)
- Tests: explicit `ts=` stored verbatim, default is now-UTC; single-role final
  step warns once per thread; no `_ = logging` placeholder remains.

## Task 9 — Packaging, version, CHANGELOG, CI, docs
- Req: REQ-321, REQ-322, REQ-323, INV-300
- Files: `_version.py`, `pyproject.toml`, `CHANGELOG.md`, `README.md`,
  `docs/reference/api.md`, `docs/reference/document-shape.md`,
  `docs/how-to/configure-ttl.md`, `docs/how-to/observability.md` (NEW),
  `docs/how-to/attribute-subagents.md` (NEW), `.github/workflows/ci.yml` (NEW)
- Tests: version == 0.3.0; `uv build` wheel re-imports full public API; public
  API regression test extended with `set_ttl`.
- **Demo:** `uv build` output + a fresh-venv `pip install dist/*.whl` import.

## Task 10 — Integration tier + publish
- Req: REQ-306/312/317 live, REQ-323
- Files: `tests/integration/*` (ADD)
- Run `-m integration` no-op without `ATLAS_URI`; with `ATLAS_URI`, exercise
  durable step across two engines, `get_thread` order, `set_ttl` via collMod,
  rerank fallback.
- **Publish (final, with explicit user go-ahead):** tag `v0.3.0`, push to
  `github.com/mohammaddaoudfarooqi/langchain-mongodb-agent-log` (public), verify
  `pip install git+https://...@v0.3.0`.
