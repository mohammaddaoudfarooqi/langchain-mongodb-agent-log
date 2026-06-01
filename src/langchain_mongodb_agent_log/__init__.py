"""Queryable, hybrid-searchable agent activity log for LangChain agents on MongoDB Atlas.

Public API surface (locked by the public-API regression test):

    AgentLog
    AgentLogMiddleware
    AgentLogCallbackHandler
    agent_log_node
    AgentLogRetriever
    search_past_conversations
    ensure_agent_log_indexes
    ensure_search_indexes
    default_voyage

Adapter classes are exported via lazy ``__getattr__`` so importing the package
does not eagerly import ``langchain.agents.middleware`` for callers that only
use the callback or graph-node adapters.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._version import __version__
from .core.engine import AgentLog
from .core.indexes import ensure_agent_log_indexes, ensure_search_indexes, set_ttl

if TYPE_CHECKING:  # pragma: no cover
    from .adapters.callback import AgentLogCallbackHandler
    from .adapters.middleware import AgentLogMiddleware
    from .adapters.node import agent_log_node
    from .core.context import current_user_id, scoped_user
    from .embeddings.factory import default_voyage
    from .retrieval.retriever import AgentLogRetriever
    from .retrieval.tool import search_past_conversations

__all__ = [
    "AgentLog",
    "AgentLogMiddleware",
    "AgentLogCallbackHandler",
    "agent_log_node",
    "AgentLogRetriever",
    "search_past_conversations",
    "ensure_agent_log_indexes",
    "ensure_search_indexes",
    "set_ttl",
    "default_voyage",
    "scoped_user",
    "current_user_id",
    "__version__",
]


_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AgentLogMiddleware": (".adapters.middleware", "AgentLogMiddleware"),
    "AgentLogCallbackHandler": (".adapters.callback", "AgentLogCallbackHandler"),
    "agent_log_node": (".adapters.node", "agent_log_node"),
    "AgentLogRetriever": (".retrieval.retriever", "AgentLogRetriever"),
    "search_past_conversations": (".retrieval.tool", "search_past_conversations"),
    "default_voyage": (".embeddings.factory", "default_voyage"),
    "scoped_user": (".core.context", "scoped_user"),
    "current_user_id": (".core.context", "current_user_id"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_name, attr = _LAZY_IMPORTS[name]
        from importlib import import_module

        module = import_module(module_name, package=__name__)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
