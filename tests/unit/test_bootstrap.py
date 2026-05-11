"""Smoke test confirming the package imports and reports its version."""
from __future__ import annotations


def test_package_imports() -> None:
    import langchain_mongodb_agent_log as p

    assert p.__name__ == "langchain_mongodb_agent_log"
    assert p.__version__ == "0.1.0"


def test_public_api_names_listed() -> None:
    """Every name in __all__ must be a real string."""
    import langchain_mongodb_agent_log as p

    for name in p.__all__:
        assert isinstance(name, str) and name
