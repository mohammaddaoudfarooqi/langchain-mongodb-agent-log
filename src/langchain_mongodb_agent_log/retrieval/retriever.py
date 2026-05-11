"""``AgentLogRetriever`` — per-user hybrid search over the agent log.

Wraps :class:`langchain_mongodb.retrievers.MongoDBAtlasHybridSearchRetriever`
(RRF fusion of ``$search`` + ``$vectorSearch``) with a mandatory per-user
``pre_filter``. The vector store handle is cached at module level (Atlas
reads the index lazily on first query); the retriever is built fresh on
every call so the per-user filter never leaks across users.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_mongodb.retrievers import MongoDBAtlasHybridSearchRetriever

from ..core.indexes import SEARCH_INDEX_NAME, VECTOR_INDEX_NAME

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from pymongo.collection import Collection


class AgentLogRetriever:
    """Hybrid retrieval over the agent log, scoped per ``user_id``.

    Args:
        collection: The agent-log collection.
        embeddings: Embeddings model. Used to embed the incoming query
            for ``$vectorSearch``.
        search_index: Atlas Search index name (default
            ``"agent_log_search_idx"``).
        vector_index: Atlas Vector Search index name (default
            ``"agent_log_vector_idx"``).
        top_k: Number of results to return (capped at 20).
    """

    _K_HARD_CAP = 20

    def __init__(
        self,
        collection: Collection[Any],
        embeddings: Embeddings,
        *,
        search_index: str = SEARCH_INDEX_NAME,
        vector_index: str = VECTOR_INDEX_NAME,
        top_k: int = 5,
    ) -> None:
        self._collection = collection
        self._embeddings = embeddings
        self._search_index = search_index
        self._vector_index = vector_index
        self._top_k = max(1, min(top_k, self._K_HARD_CAP))
        self._vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=vector_index,
            text_key="agent_log_text",
            embedding_key="agent_log_embedding",
            relevance_score_fn="cosine",
            auto_create_index=False,
        )

    def invoke(self, query: str, *, user_id: str) -> list[Document]:
        """Return up to ``top_k`` log documents ranked by RRF fusion.

        The per-user pre-filter is mandatory and is verified at the
        retriever level. The caller can never see another user's
        threads through this method.
        """
        retriever = MongoDBAtlasHybridSearchRetriever(
            vectorstore=self._vector_store,
            search_index_name=self._search_index,
            top_k=self._top_k,
            pre_filter={"user_id": {"$eq": user_id}},
        )
        return retriever.invoke(query)
