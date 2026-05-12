"""Per-task / per-thread ``user_id`` propagation for the callback adapter.

Why this exists:

LangGraph's per-node callback metadata elevates ``thread_id`` but not
``user_id``. A single :class:`AgentLogCallbackHandler` instance shared
across concurrent users — common in multi-tenant async servers —
cannot tell which user a given callback fires for. Constructor-based
fallbacks force one-handler-per-user, which is fragile.

This module ships a :class:`contextvars.ContextVar`-backed scoping
primitive so a request-boundary call to :func:`scoped_user` makes the
user id visible to every callback fired inside the surrounding
runnable invocation, with proper per-asyncio-task and per-thread
isolation.

Mirrors the same pattern LangGraph itself uses to propagate
:class:`RunnableConfig` (``langgraph.config.get_config()`` reads a
ContextVar set at graph-invoke time).

Example::

    from langchain_mongodb_agent_log import scoped_user, AgentLogCallbackHandler

    handler = AgentLogCallbackHandler(log)  # constructed once

    async def handle_chat(req):
        with scoped_user(req.user_id):
            await graph.ainvoke(
                req.payload,
                config={
                    "configurable": {"thread_id": req.thread_id, "user_id": req.user_id},
                    "callbacks": [handler],
                },
            )

The handler now resolves ``user_id`` for each fired callback in this
order: per-call ``metadata["user_id"]`` > the ContextVar set by
:func:`scoped_user` > the constructor fallback. Concurrent requests
each see their own scoped value.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Module-private. Consumers read via :func:`current_user_id` and write
# via :func:`scoped_user`. Keeping the variable itself private prevents
# drift where ad-hoc callers ``set()`` it without proper ``reset()``,
# which would leak state across requests.
_user_id_var: ContextVar[str | None] = ContextVar(
    "langchain_mongodb_agent_log_user_id", default=None
)


def current_user_id() -> str | None:
    """Return the active scoped ``user_id`` or ``None`` if unset.

    O(1). Each ``asyncio.Task`` and each ``threading.Thread`` sees its
    own value. Outside any :func:`scoped_user` block, returns ``None``.
    """
    return _user_id_var.get()


@contextmanager
def scoped_user(user_id: str) -> Iterator[None]:
    """Set the scoped ``user_id`` for the duration of the ``with`` block.

    Restores the previous value on exit, including when the block
    raises. Safe to nest — each exit pops the latest set, never the
    original.

    Args:
        user_id: The user id to make visible to
            :func:`current_user_id` and any code (notably
            :class:`AgentLogCallbackHandler`) that consults the scoped
            value.

    Yields:
        ``None``. The value is read via :func:`current_user_id`, not
        from the ``with`` binding.

    Example::

        with scoped_user("alice"):
            graph.invoke(payload, config={"callbacks": [handler]})
    """
    token = _user_id_var.set(user_id)
    try:
        yield
    finally:
        _user_id_var.reset(token)


__all__ = ["current_user_id", "scoped_user"]
