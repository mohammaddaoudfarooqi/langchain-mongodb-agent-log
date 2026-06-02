"""``AgentLogMiddleware`` — primary adapter for ``create_agent`` / deepagents.

Subclasses :class:`langchain.agents.middleware.AgentMiddleware` and uses the
``after_model`` / ``aafter_model`` hooks. Both hooks delegate to
:meth:`AgentLog.record`; the engine's worker absorbs the I/O so the agent
super-step is never blocked.

Configurable extraction order:
1. ``langgraph.config.get_config()`` (the LangGraph-native way to access the
   active ``RunnableConfig`` from inside a node) — when called inside a
   compiled graph, this returns the live config.
2. ``runtime.config["configurable"]`` for adapters and unit rigs that hand
   the middleware a ``Runtime``-shaped object carrying an explicit config.
3. ``runtime.execution_info.thread_id`` — the thread id LangGraph attaches
   directly to the node ``Runtime``. This is the last identity that survives
   when the ambient runnable-config context is unreachable, so it keeps the
   super-step from being silently dropped.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

from ..core.engine import AgentLog
from ._correlation import derive_correlation_id

if TYPE_CHECKING:  # pragma: no cover
    pass


def _configurable_from_runtime(runtime: Any) -> dict[str, Any]:
    """Best-effort extraction of ``RunnableConfig.configurable``."""
    # 1. LangGraph-native ambient config — populated in sync nodes and, on
    #    CPython >= 3.11, async nodes.
    try:
        from langgraph.config import get_config

        cfg = get_config()
        if isinstance(cfg, dict):
            inner = cfg.get("configurable", {})
            if isinstance(inner, dict) and inner:
                return dict(inner)
    except Exception:
        pass
    # 2. Explicit ``runtime.config`` (some adapters and test rigs set it).
    fallback = getattr(runtime, "config", None) or {}
    if isinstance(fallback, dict):
        inner = fallback.get("configurable", {})
        if isinstance(inner, dict) and inner:
            return dict(inner)
    # 3. Last resort: recover the thread id from the node Runtime. Custom
    #    configurable keys (user_id, agent_name, ...) are not carried here.
    info = getattr(runtime, "execution_info", None)
    thread_id = getattr(info, "thread_id", None)
    if isinstance(thread_id, str) and thread_id:
        return {"thread_id": thread_id}
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

    def __init__(self, log: AgentLog, *, agent_name: str | None = None) -> None:
        """Construct the middleware.

        Args:
            log: The :class:`AgentLog` engine instance to write through.
            agent_name: Optional constructor override (REQ-315). WHEN set it
                takes precedence over ``configurable["agent_name"]`` — the
                attribution seam for deepagents subagents: attach
                ``AgentLogMiddleware(log, agent_name="researcher")`` to that
                subagent's ``middleware=[...]`` list.
        """
        super().__init__()
        self.tools: list[Any] = []
        self._log = log
        self._agent_name = agent_name

    def after_model(self, state: Any, runtime: Any) -> None:
        cfg = _configurable_from_runtime(runtime)
        thread_id = str(cfg.get("thread_id") or "")
        user_id = str(cfg.get("user_id") or "")
        messages = state.get("messages", []) if isinstance(state, dict) else []
        todos = state.get("todos") if isinstance(state, dict) else None
        # REQ-315: constructor override beats configurable.
        agent_name = self._agent_name or cfg.get("agent_name")
        self._log.record(
            thread_id=thread_id,
            user_id=user_id,
            messages=messages,
            todos=todos,
            agent_name=str(agent_name) if agent_name else None,
            correlation_id=derive_correlation_id(cfg),
        )
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        # Identical projection. The actual MongoDB I/O lives on the engine's
        # worker thread regardless, so there's nothing async to await here.
        self.after_model(state, runtime)
        return None
