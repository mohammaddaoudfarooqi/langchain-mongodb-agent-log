# Tasks — v0.2

## Traceability matrix

| Req ID | Test Case IDs | Task | Status |
|---|---|---|---|
| REQ-101 (private ContextVar) | TC-101 (default None) | T1 | Not started |
| REQ-102 (`current_user_id`) | TC-102a/b | T1 | Not started |
| REQ-103 (`scoped_user` context manager) | TC-103a (set), TC-103b (restore), TC-103c (nest) | T1 | Not started |
| REQ-104 (asyncio isolation) | TC-104 | T1 | Not started |
| REQ-105 (threading isolation) | TC-105 | T1 | Not started |
| REQ-106 (callback resolves 3-tier) | TC-106a (metadata wins), TC-106b (CV middle), TC-106c (constructor floor) | T2 | Not started |
| REQ-107 (re-export at root) | TC-107 (public import) | T3 | Not started |
| REQ-108 (exception-safe restore) | TC-108 | T1 | Not started |
| INV-101 (middleware unchanged) | existing test_middleware.py | — | passes baseline |
| INV-102 (constructor fallback unchanged) | existing test_callback.py | — | passes baseline |
| INV-103 (per-user pre_filter) | existing test_retriever.py / test_tool.py | — | passes baseline |
| INV-104 (public API resolves) | TC-107 | T3 | Not started |

## T1 — Implement `core/context.py` + tests

- Status: [ ] Not started
- Maps to: REQ-101..105, REQ-108
- Subtasks:
  1. RED: write `tests/unit/test_context.py` with TC-101..108 + isolation tests.
  2. GREEN: write `src/.../core/context.py` with `_user_id_var`,
     `current_user_id`, `scoped_user`.
  3. Confirm new tests green; no existing tests touched.
- Acceptance: 8+ new tests pass; `current_user_id`+`scoped_user`
  importable from `core.context`.

## T2 — Wire 3-tier resolution into `AgentLogCallbackHandler`

- Status: [ ] Not started
- Maps to: REQ-106
- Subtasks:
  1. RED: extend `tests/unit/test_callback.py` with TC-106a/b/c.
  2. GREEN: update `on_chain_start` to apply the 3-tier resolver.
     Use `from ..core.context import current_user_id` (relative
     import keeps the import surface tidy).
  3. Confirm new + existing tests green (existing 5 must still
     pass — INV-102).
- Acceptance: 8 callback tests pass (5 existing + 3 new).

## T3 — Re-export from package root + public API import test

- Status: [ ] Not started
- Maps to: REQ-107, INV-104
- Subtasks:
  1. RED: write TC-107 in either `test_public_api.py` (if exists) or
     append to `test_callback.py` — assert
     `from langchain_mongodb_agent_log import scoped_user, current_user_id`
     resolves to callables.
  2. GREEN: update `__init__.py` `__all__` and `_LAZY_IMPORTS`.
  3. Bump `_version.py` to `0.2.0`.
- Acceptance: import test passes; `__version__ == "0.2.0"`.

## T4 — Documentation

- Status: [ ] Not started
- Maps to: acceptance criteria items 5-6
- Subtasks:
  1. Add `scoped_user` and `current_user_id` rows to
     `docs/reference/api.md`.
  2. Create `docs/how-to/per-user-scoping-with-contextvar.md` with a
     concrete FastAPI-ish multi-user example showing how to wrap the
     graph invocation in `scoped_user(req.user_id)`.
  3. Append a v0.2 row to `docs/explanation/architecture.md` (the
     callback adapter's user_id resolution paragraph).
- Acceptance: links resolve; example is copy-pasteable.

## T5 — Final verify

- Status: [ ] Not started
- Maps to: acceptance criteria items 1-4
- Subtasks:
  1. `uv run pytest -v` — confirm all green, count went up by ≥ 8.
  2. `uv run mypy --strict src` — clean.
  3. `uv run ruff check src tests` — clean.
  4. `uv build` — wheel + sdist produced.
  5. Update `CHANGELOG.md` with the v0.2 entry.
- Acceptance: every box on the acceptance list ticked.
