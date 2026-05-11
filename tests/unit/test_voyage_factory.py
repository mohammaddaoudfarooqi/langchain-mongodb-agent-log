"""Voyage factory tests — REQ-038."""
from __future__ import annotations

import pytest


def test_TC_038a_default_voyage_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langchain_voyageai")
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")

    from langchain_voyageai import VoyageAIEmbeddings

    from langchain_mongodb_agent_log import default_voyage

    emb = default_voyage()
    assert isinstance(emb, VoyageAIEmbeddings)


def test_TC_038b_default_voyage_raises_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    from langchain_mongodb_agent_log import default_voyage

    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        default_voyage()
