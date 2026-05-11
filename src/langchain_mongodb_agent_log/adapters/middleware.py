"""``AgentLogMiddleware`` — primary adapter for ``create_agent`` / deepagents.

Subclasses :class:`langchain.agents.middleware.AgentMiddleware` and uses the
``after_model`` / ``aafter_model`` hooks. Both hooks delegate to
:meth:`AgentLog.record`; the engine's worker absorbs the I/O so the agent
super-step is never blocked.

Configurable extraction order:
1. ``langgraph.config.get_config()`` (the LangGraph-native way to access the
   active ``RunnableConfig`` from inside a node) — when called inside a
   compiled graph, this returns the live config.
2. Fallback to ``runtime.config["configurable"]`` for unit tests that
   construct a ``Runtime``-shaped mock without spinning up a graph.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

from ..core.engine import AgentLog

if TYPE_CHECKING:  # pragma: no cover
    pass


def _configurable_from_runtime(runtime: Any) -> dict[str, Any]:
    """Best-effort extraction of ``RunnableConfig.configurable``."""
    try:
        from langgraph.config import get_config

        cfg = get_config()
        if isinstance(cfg, dict):
            inner = cfg.get("configurable", {})
            if isinstance(inner, dict) and inner:
                return dict(inner)
    except Exception:
        pass
    fallback = getattr(runtime, "config", {}) or {}
    if isinstance(fallback, dict):
        inner = fallback.get("configurable", {})
        if isinstance(inner, dict):
            return dict(inner)
    return {}


class AgentLogMiddleware(AgentMiddleware[Any, Any, Any]):
    """Record one log document per ``after_model`` firing.

    Args:
        log: The :class:`AgentLog` engine instance to write through.

    Example::

        from langchain.agents import create_agent
        from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

        log = AgentLog(collection=db["agent_log"], embeddings=voyage)
        agent = create_agent(
            model=...,
            tools=[...],
            middleware=[AgentLogMiddleware(log)],
        )
    """

    def __init__(self, log: AgentLog) -> None:
        super().__init__()
        self.tools: list[Any] = []
        self._log = log

    def after_model(self, state: Any, runtime: Any) -> None:
        cfg = _configurable_from_runtime(runtime)
        thread_id = str(cfg.get("thread_id") or "")
        user_id = str(cfg.get("user_id") or "")
        messages = state.get("messages", []) if isinstance(state, dict) else []
        todos = state.get("todos") if isinstance(state, dict) else None
        agent_name = cfg.get("agent_name")
        correlation_id = cfg.get("correlation_id")
        self._log.record(
            thread_id=thread_id,
            user_id=user_id,
            messages=messages,
            todos=todos,
            agent_name=str(agent_name) if agent_name else None,
            correlation_id=str(correlation_id) if correlation_id else None,
        )
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        # Identical projection. The actual MongoDB I/O lives on the engine's
        # worker thread regardless, so there's nothing async to await here.
        self.after_model(state, runtime)
        return None
