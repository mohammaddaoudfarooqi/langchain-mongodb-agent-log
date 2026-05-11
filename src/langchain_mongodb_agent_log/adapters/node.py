"""``agent_log_node`` — explicit graph-node adapter.

For users who want maximum control: wire a node into your ``StateGraph``
that, when reached, writes one log document and returns no state delta.
This adapter is the escape hatch for graphs whose hook semantics don't
match middleware or the callback handler.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.engine import AgentLog


def agent_log_node(log: AgentLog) -> Callable[[Any, Any], dict[str, Any]]:
    """Build a graph node that records one log document per invocation.

    The node returns ``{}`` (no state delta), so it's safe to wire
    anywhere in the graph: before ``END``, between supervisor and
    workers, or as a sibling to a tool node.

    Args:
        log: The :class:`AgentLog` engine instance.

    Returns:
        A ``(state, config) -> dict`` callable suitable for
        :py:meth:`langgraph.graph.StateGraph.add_node`.

    Example::

        from langgraph.graph import END, StateGraph
        from langchain_mongodb_agent_log import AgentLog, agent_log_node

        log = AgentLog(collection=db["agent_log"])
        builder = StateGraph(MyState)
        builder.add_node("agent", my_agent)
        builder.add_node("audit", agent_log_node(log))
        builder.add_edge("agent", "audit")
        builder.add_edge("audit", END)
    """

    def _node(state: Any, config: Any) -> dict[str, Any]:
        cfg = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = str(cfg.get("thread_id") or "")
        user_id = str(cfg.get("user_id") or "")
        messages = state.get("messages", []) if isinstance(state, dict) else []
        todos = state.get("todos") if isinstance(state, dict) else None
        agent_name = cfg.get("agent_name") or "main"
        correlation_id = cfg.get("correlation_id")
        log.record(
            thread_id=thread_id,
            user_id=user_id,
            messages=messages,
            todos=todos,
            agent_name=str(agent_name),
            correlation_id=str(correlation_id) if correlation_id else None,
        )
        return {}

    return _node
