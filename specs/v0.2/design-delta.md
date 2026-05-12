# Design Delta — v0.2

> Companion to v0.1 design. Documents only what changes.

## What's new

```
src/langchain_mongodb_agent_log/
  core/
    context.py                 ← NEW: ContextVar + scoped_user + current_user_id
  adapters/
    callback.py                ← MODIFIED: 3-tier user_id resolution
  __init__.py                  ← MODIFIED: re-export the two new names lazily
```

## Module: `core/context.py`

Single primitive plus a thin context manager.

```python
"""Per-task / per-thread ``user_id`` propagation for the callback adapter.

LangGraph's per-node callback metadata elevates ``thread_id`` but not
``user_id``. Constructor-based fallbacks on ``AgentLogCallbackHandler``
are race-prone in multi-tenant async deployments where one handler
instance serves many concurrent users. ``ContextVar`` solves this the
same way LangGraph itself solves ``RunnableConfig`` propagation —
implicit, per-task, isolated.

Typical usage at a request boundary::

    from langchain_mongodb_agent_log import scoped_user

    async def handle_chat(req):
        with scoped_user(req.user_id):
            await graph.ainvoke(req.payload, config={"callbacks": [handler]})
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_user_id_var: ContextVar[str | None] = ContextVar(
    "langchain_mongodb_agent_log_user_id", default=None
)


def current_user_id() -> str | None:
    """Return the active scoped ``user_id`` or ``None`` if unset.

    Reads the package-private :class:`ContextVar`. Each ``asyncio.Task``
    and each thread sees its own value; a value set in one task does
    not leak into another.
    """
    return _user_id_var.get()


@contextmanager
def scoped_user(user_id: str) -> Iterator[None]:
    """Set the scoped ``user_id`` for the duration of the ``with`` block.

    Restores the previous value on exit, even if the block raises.
    Safe to nest — exit pops the latest set, not the original.

    Args:
        user_id: The user id to make visible to the callback adapter
            (and any other code that reads :func:`current_user_id`).

    Example::

        with scoped_user("alice"):
            graph.invoke(payload, config={"callbacks": [handler]})
    """
    token = _user_id_var.set(user_id)
    try:
        yield
    finally:
        _user_id_var.reset(token)
```

That's the entire module. ~30 LOC including docstrings.

## Modified: `adapters/callback.py`

Only `on_chain_start` changes. Replace the line that reads `user_id`
with a 3-tier resolver.

**Before** (v0.1):

```python
self._pending[run_id] = {
    "agent_name": str(node),
    "thread_id": str(meta.get("thread_id") or ""),
    "user_id": str(meta.get("user_id") or self._default_user_id or ""),
    "correlation_id": meta.get("correlation_id"),
}
```

**After** (v0.2):

```python
from ..core.context import current_user_id

# Resolution order: per-call metadata > ContextVar > constructor default.
resolved_user_id = (
    str(meta.get("user_id") or "")
    or (current_user_id() or "")
    or (self._default_user_id or "")
)

self._pending[run_id] = {
    "agent_name": str(node),
    "thread_id": str(meta.get("thread_id") or ""),
    "user_id": resolved_user_id,
    "correlation_id": meta.get("correlation_id"),
}
```

Why per-call metadata wins over the ContextVar: explicit beats
implicit. A test that monkey-patches a single call's metadata
shouldn't be defeated by leftover scope state.

Why ContextVar wins over constructor default: in production the
ContextVar is set per-request; the constructor default is a fallback
for "I forgot to scope it" — unsuitable as the primary signal in a
multi-user server.

## Modified: `__init__.py`

Add to `_LAZY_IMPORTS` (the lazy `__getattr__` map) and `__all__`:

```python
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
    "scoped_user",                # NEW
    "current_user_id",            # NEW
    "__version__",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # ...existing...
    "scoped_user":      (".core.context", "scoped_user"),
    "current_user_id":  (".core.context", "current_user_id"),
}
```

Why lazy imports for these too: they don't need it (no expensive
deps) but adding them to the lazy map keeps `__getattr__` consistent
and lets us swap to a `core.context` symbol that has heavier deps in
the future without touching consumers.

## Tests: new file `tests/unit/test_context.py`

Covers REQ-101..108 + INV-104. ~150 LOC. Sections:

1. Default value is `None`.
2. `scoped_user("alice")` makes `current_user_id()` return `"alice"`.
3. Nested scopes pop correctly (LIFO).
4. Exception inside `with` still restores prior value.
5. Per-`asyncio.Task` isolation (REQ-104).
6. Per-`threading.Thread` isolation (REQ-105).
7. Public API import: `from langchain_mongodb_agent_log import scoped_user, current_user_id`
   succeeds (REQ-107).

## Tests: extend `tests/unit/test_callback.py`

Add 2-3 new tests:
1. ContextVar value picked up when metadata empty AND no constructor default.
2. ContextVar value overridden by metadata `user_id`.
3. ContextVar value used when both ContextVar AND constructor default
   are set (ContextVar wins).

Existing 5 callback tests must keep passing unchanged (INV-102).

## Test infrastructure

No changes — pytest-asyncio is already configured. The thread test
uses stdlib `threading` only.

## Versioning

Bump `_version.py` to `0.2.0`. Additive change; no breakage.
