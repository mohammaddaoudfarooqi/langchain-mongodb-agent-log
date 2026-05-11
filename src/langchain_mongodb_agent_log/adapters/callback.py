"""``AgentLogCallbackHandler`` — secondary adapter for bare ``StateGraph``,
multi-agent supervisor graphs, and graphs that mix raw nodes with
``create_agent`` instances.

Subclasses :class:`langchain_core.callbacks.BaseCallbackHandler`. Hooks
``on_chain_start`` to capture the LangGraph-injected node metadata
(``metadata["langgraph_node"]``), then on ``on_chain_end`` writes one log
document per matching ``run_id``.

Why two hooks: LangGraph stamps the per-node ``langgraph_node`` /
``langgraph_step`` metadata on ``on_chain_start`` only. ``on_chain_end``
fires with empty metadata. To attribute the document correctly, we capture
on start (keyed by ``run_id``) and consume on end. Inner Runnables that
don't have ``langgraph_node`` set are ignored — so per-LLM-call,
per-tool-call events don't generate spurious documents.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from ..core.engine import AgentLog


class AgentLogCallbackHandler(BaseCallbackHandler):
    """Record one log document per top-level LangGraph node end.

    Args:
        log: The :class:`AgentLog` engine instance.

    Example::

        handler = AgentLogCallbackHandler(log)
        graph.invoke(
            {"messages": [...]},
            config={
                "configurable": {"thread_id": "t1", "user_id": "u1"},
                "callbacks": [handler],
            },
        )
    """

    def __init__(
        self,
        log: AgentLog,
        *,
        user_id: str | None = None,
    ) -> None:
        """Construct the handler.

        Args:
            log: The :class:`AgentLog` engine instance.
            user_id: Optional fallback ``user_id`` used when LangGraph
                does not elevate it from ``configurable`` to the
                callback metadata. In bare ``StateGraph`` graphs, only
                ``thread_id`` is auto-stamped on the per-node metadata;
                supply ``user_id`` here (or via
                ``config["metadata"]["user_id"]`` per invocation) so
                the per-user invariant is preserved.
        """
        super().__init__()
        self._log = log
        self._default_user_id = user_id
        # run_id -> { agent_name, thread_id, user_id, correlation_id }
        # Each entry is freed on the matching on_chain_end.
        self._pending: dict[UUID, dict[str, Any]] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        meta = metadata or {}
        node = meta.get("langgraph_node")
        if not node:
            return None  # not a top-level graph superstep
        self._pending[run_id] = {
            "agent_name": str(node),
            "thread_id": str(meta.get("thread_id") or ""),
            # LangGraph elevates ``thread_id`` to top-level metadata but
            # not ``user_id``; fall back to the constructor default if
            # the user didn't pass it via ``config["metadata"]``.
            "user_id": str(meta.get("user_id") or self._default_user_id or ""),
            "correlation_id": meta.get("correlation_id"),
        }
        return None

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        if run_id is None:
            return None
        captured = self._pending.pop(run_id, None)
        if captured is None:
            return None
        thread_id = captured["thread_id"]
        user_id = captured["user_id"]
        if not thread_id or not user_id:
            return None
        self._log.record(
            thread_id=thread_id,
            user_id=user_id,
            messages=self._extract_messages(outputs),
            todos=self._extract_todos(outputs),
            agent_name=captured["agent_name"],
            correlation_id=captured.get("correlation_id"),
        )
        return None

    async def on_chain_start_async(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.on_chain_start(
            serialized,
            inputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )

    async def on_chain_end_async(
        self,
        outputs: Any,
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.on_chain_end(
            outputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )

    @staticmethod
    def _extract_messages(outputs: Any) -> list[Any]:
        if isinstance(outputs, dict):
            msgs = outputs.get("messages", [])
            if isinstance(msgs, list):
                return msgs
        return []

    @staticmethod
    def _extract_todos(outputs: Any) -> list[Any] | None:
        if isinstance(outputs, dict):
            todos = outputs.get("todos")
            if isinstance(todos, list):
                return todos
        return None
