# Requirements — v0.2: ContextVar-based `user_id` propagation

> Enhancement spec. References v0.1 (`../v0.1/requirements.md`,
> `../v0.1/design.md`). Adds REQ-101..108 + INV-101..104.

## 1. Vision

Per-user attribution in the callback adapter is currently a sharp edge:
the constructor accepts a default `user_id`, but a single
`AgentLogCallbackHandler` instance shared across concurrent users will
attribute every doc to that one default. In a multi-tenant async
deployment that's a quiet correctness bug: cross-user attribution leak
into the agent log.

This release adds a `ContextVar`-based scoping primitive so a single
handler instance can serve concurrent users correctly, mirroring how
LangGraph itself propagates `RunnableConfig` via context vars.

## 2. Functional requirements

- **REQ-101.** THE SYSTEM SHALL expose a module-level
  `contextvars.ContextVar[str | None]` named `_user_id_var` (private)
  in a new `core/context.py` module. Default: `None`.

- **REQ-102.** THE SYSTEM SHALL expose a public function
  `current_user_id() -> str | None` that returns the active value of
  `_user_id_var` (or `None` if unset).

- **REQ-103.** THE SYSTEM SHALL expose a public context manager
  `scoped_user(user_id: str)` that:
  - on `__enter__`: calls `_user_id_var.set(user_id)` and stores the
    resulting `Token`.
  - on `__exit__`: calls `_user_id_var.reset(token)` to restore the
    previous value (including across nested scopes).

- **REQ-104.** WHEN `scoped_user("alice")` is active in one
  `asyncio.Task` THE SYSTEM SHALL NOT leak that value into a
  concurrently-running `asyncio.Task` that has not entered the
  context manager.

- **REQ-105.** WHEN `scoped_user("alice")` is active in one
  `threading.Thread` THE SYSTEM SHALL NOT leak that value into a
  concurrently-running `threading.Thread` that has not entered the
  context manager.

- **REQ-106.** `AgentLogCallbackHandler.on_chain_start` SHALL resolve
  `user_id` with the following precedence:
  1. `metadata["user_id"]` if non-empty (per-call override)
  2. `current_user_id()` if non-empty (ContextVar — set by
     `scoped_user(...)` at the request boundary)
  3. `self._default_user_id` (constructor default)
  4. `""` (skip the write)

- **REQ-107.** THE SYSTEM SHALL re-export `scoped_user` and
  `current_user_id` at the package root via the lazy
  `__getattr__` mechanism. The public API list (`__all__` in
  `__init__.py`) SHALL include both names.

- **REQ-108.** WHEN `scoped_user(...)` exits — including via an
  exception inside the `with` block — THE SYSTEM SHALL restore the
  previous `_user_id_var` value (i.e. `__exit__` MUST run `reset(token)`
  even on exception).

## 3. Non-functional requirements

- **NFR-101.** Calling `current_user_id()` SHALL be O(1) and must not
  perform I/O or acquire locks beyond what `ContextVar.get()`
  inherently does.
- **NFR-102.** The new symbols SHALL be importable as
  `from langchain_mongodb_agent_log import scoped_user, current_user_id`
  without triggering the lazy import of any adapter that requires
  `langchain.agents` (i.e. importing the ContextVar primitives must
  not pull in the middleware adapter).

## 4. Unchanged behavior (invariants)

- **INV-101.** `AgentLogMiddleware` behavior SHALL CONTINUE TO be
  unchanged — it reads `user_id` from
  `langgraph.config.get_config().configurable` (LangGraph's own
  ContextVar) and does not need this primitive. The existing 7 tests
  in `test_middleware.py` must continue to pass.
- **INV-102.** Existing constructor argument
  `AgentLogCallbackHandler(log, user_id="alice")` SHALL CONTINUE TO
  work as a fallback when neither `metadata["user_id"]` nor the
  ContextVar is set. The existing 5 tests in `test_callback.py` must
  continue to pass without modification.
- **INV-103.** The retriever's per-user `pre_filter` invariant
  (INV-004 from v0.1) SHALL CONTINUE TO be enforced regardless of
  where `user_id` was sourced.
- **INV-104.** Existing public API (REQ-V1-INV-005's import surface)
  SHALL CONTINUE TO resolve. The new symbols are additive only.

## 5. Out of scope (v0.2)

- Auto-population of the ContextVar from LangGraph's config
  (a future v0.3 may add a wrapper that reads
  `RunnableConfig.configurable["user_id"]` and calls
  `scoped_user(...)` automatically — but that requires careful
  thinking about RunnableConfig propagation order and is deferred).
- A `scoped_thread_id` / `scoped_correlation_id` equivalent — the
  current shape only needs `user_id`.
- Async context manager (`async with scoped_user(...)`) — the sync
  context manager works correctly inside `async def` functions
  because `ContextVar` is async-aware.

## 6. Acceptance criteria

- [ ] All `REQ-101..108` have ≥ 1 passing test.
- [ ] All `INV-101..104` have ≥ 1 regression test (existing tests
      satisfy these — no new regression tests needed).
- [ ] `uv run pytest` is green; total test count goes up by ≥ 8.
- [ ] `uv run ruff check src tests` clean.
- [ ] `uv run mypy --strict src` clean.
- [ ] Reference doc `docs/reference/api.md` lists `scoped_user` and
      `current_user_id`.
- [ ] How-to guide `docs/how-to/per-user-scoping-with-contextvar.md`
      exists with a concrete multi-user-server example.
