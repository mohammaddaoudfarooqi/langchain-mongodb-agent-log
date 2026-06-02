"""Optional embedding-provider factory.

Returns a configured Voyage embedder when ``VOYAGE_API_KEY`` is set in the
environment. Voyage is a pluggable default — any
:class:`langchain_core.embeddings.Embeddings` instance can be passed
directly to :class:`AgentLog`. The Voyage extra is opt-in:

    pip install langchain-mongodb-agent-log[voyage]
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.embeddings import Embeddings


from typing import Literal

_DEFAULT_MODEL = "voyage-3"
_DEFAULT_DIM: Literal[256, 512, 1024, 2048] = 1024


def default_voyage(
    *,
    model: str = _DEFAULT_MODEL,
    dimensions: Literal[256, 512, 1024, 2048] = _DEFAULT_DIM,
    **kwargs: Any,
) -> Embeddings:
    """Construct a Voyage embedder from the environment.

    Args:
        model: Voyage model name. Defaults to ``"voyage-3"``.
        dimensions: Embedding dimensionality. Defaults to ``1024``.
        **kwargs: Forwarded to :class:`langchain_voyageai.VoyageAIEmbeddings`.

    Raises:
        RuntimeError: If ``VOYAGE_API_KEY`` is not set in the environment,
            or if ``langchain-voyageai`` is not installed.
    """
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is not set. Either set it in the environment, or "
            "pass an explicit ``embeddings=`` to AgentLog instead of relying "
            "on default_voyage()."
        )
    try:
        from langchain_voyageai import VoyageAIEmbeddings
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise RuntimeError(
            "langchain-voyageai is not installed. Install with "
            "`pip install langchain-mongodb-agent-log[voyage]` to use "
            "default_voyage(), or pass your own Embeddings instance."
        ) from exc
    embedder: Embeddings = VoyageAIEmbeddings(
        voyage_api_key=api_key,
        model=model,
        output_dimension=dimensions,
        **kwargs,
    )
    return embedder
