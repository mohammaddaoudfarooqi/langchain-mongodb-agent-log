"""``search_past_conversations`` — prebuilt LangChain ``@tool``.

Reads ``user_id`` from the active ``RunnableConfig.configurable`` and returns
a JSON string of past-conversation hits ranked by RRF fusion.

Two surface variants:

- :func:`build_tool` — factory bound to a specific collection + embedder.
  Use this in agent code; the resulting tool is added to ``tools=[...]``.
- :func:`search_past_conversations` — a thin module-level alias kept for
  documentation symmetry; calling it requires a manually-bound tool.

The tool returns ``"REFUSED: missing user_id in config"`` when the caller
does not propagate ``user_id`` (per-user scoping is mandatory) and ``"[]"``
when the underlying retriever raises (Atlas unreachable, malformed query,
etc.). The error is logged at warning level on the package's named logger.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from .._logging import get_logger
from .retriever import AgentLogRetriever

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.embeddings import Embeddings
    from pymongo.collection import Collection


_log = get_logger()
_RESULT_SNIPPET_MAX = 200


def build_tool(
    collection: Collection[Any],
    embeddings: Embeddings,
    *,
    top_k: int = 5,
) -> Any:
    """Return a LangChain tool bound to ``collection`` + ``embeddings``.

    The tool's input schema is ``{"query": str}`` (and optional ``k``).
    ``user_id`` is never an input parameter — it must come from the
    ``RunnableConfig`` so the agent cannot spoof another user's history.
    """
    retriever = AgentLogRetriever(collection, embeddings, top_k=top_k)

    @tool
    def search_past_conversations(
        query: str,
        config: RunnableConfig,
    ) -> str:
        """Search the calling user's past conversations and return a JSON
        list of ``{thread_id, step, ts, snippet, agent_name, model_id}``
        records ranked by RRF fusion of vector + lexical search."""
        user_id = _extract_user_id(config)
        if not user_id:
            return "REFUSED: missing user_id in config"
        try:
            docs = retriever.invoke(query, user_id=user_id)
        except Exception as exc:
            _log.warning(
                "search_past_conversations failed (user=%s): %s", user_id, exc
            )
            return "[]"
        out = [_doc_to_record(d) for d in docs]
        return json.dumps(out, ensure_ascii=False)

    return search_past_conversations


def _extract_user_id(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    configurable = config.get("configurable") or {}
    if not isinstance(configurable, dict):
        return None
    uid = configurable.get("user_id")
    return uid if isinstance(uid, str) and uid else None


def _doc_to_record(d: Any) -> dict[str, Any]:
    meta = dict(getattr(d, "metadata", None) or {})
    ts = meta.get("ts")
    ts_out: Any = ts.isoformat() if ts is not None and hasattr(ts, "isoformat") else ts
    page = getattr(d, "page_content", "") or ""
    return {
        "thread_id": meta.get("thread_id"),
        "step": meta.get("step"),
        "ts": ts_out,
        "snippet": page[:_RESULT_SNIPPET_MAX],
        "agent_name": meta.get("agent_name"),
        "model_id": meta.get("model_id"),
    }


# Module-level placeholder so ``from langchain_mongodb_agent_log import
# search_past_conversations`` resolves to *something*. Users should call
# ``build_tool(...)`` instead — the bound tool is what actually fires.
def search_past_conversations(*args: Any, **kwargs: Any) -> str:  # noqa: D401
    """Module-level alias.

    The real tool is created by :func:`build_tool`. This alias exists so
    static imports at the package root succeed; calling it directly raises
    an informative error.
    """
    raise RuntimeError(
        "search_past_conversations is a tool factory. Build a bound tool with "
        "`build_tool(collection, embeddings)` and add the result to your "
        "agent's `tools=[...]`."
    )


_ = logging  # silence "imported but unused" until structured logs land in v0.2
